"""Synchronize a highly rated, read-only Lich script corpus."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from typing import BinaryIO, Iterable, Mapping, Protocol
from uuid import uuid4


DEFAULT_HOST = "repo.lichproject.org"
DEFAULT_PORT = 7157
DEFAULT_CLIENT_VERSION = "2.74"
DEFAULT_OUTPUT = Path(".lab-cache/lich-community-corpus")
MAX_HEADER_BYTES = 64 * 1024
MAX_LIST_BYTES = 32 * 1024 * 1024
MAX_SCRIPT_BYTES = 20 * 1024 * 1024
ALLOWED_CERTIFICATE_COMMON_NAMES = frozenset({"lichproject.org", "Lich Repository"})


# Copied from repository.lic v2.74. The repository protocol trusts this private
# root rather than the operating system CA bundle; it is valid through 2044.
REPOSITORY_CA = """-----BEGIN CERTIFICATE-----
MIIDoDCCAoigAwIBAgIUYwhIyTlqWaEd5mYGXoQQoC+ndKcwDQYJKoZIhvcNAQEL
BQAwYTELMAkGA1UEBhMCVVMxETAPBgNVBAgMCElsbGlub2lzMRIwEAYDVQQKDAlN
YXR0IExvd2UxDzANBgNVBAMMBlJvb3RDQTEaMBgGCSqGSIb3DQEJARYLbWF0dEBp
bzQudXMwHhcNMjQwNjA1MTM1NzUxWhcNNDQwNTMxMTM1NzUxWjBhMQswCQYDVQQG
EwJVUzERMA8GA1UECAwISWxsaW5vaXMxEjAQBgNVBAoMCU1hdHQgTG93ZTEPMA0G
A1UEAwwGUm9vdENBMRowGAYJKoZIhvcNAQkBFgttYXR0QGlvNC51czCCASIwDQYJ
KoZIhvcNAQEBBQADggEPADCCAQoCggEBAJwhGfQgwI1h4vlqAqaR152AlewjJMlL
yoqtjoS9Cyri23SY7c6v0rwhoOXuoV1D2d9InmmE2CgLL3Bn2sNa/kWFjkyedUca
vd8JrtGQzEkVH83CIPiKFCWLE5SXLvqCVx7Jz/pBBL1s173p69kOy0REYAV/OAdj
ioCXK6tHqYG70xvLIJGiTrExGeOttMw2S+86y4bSxj2i35IscaBTepPv7BWH8JtZ
yN4Xv9DBr/99sWSarlzUW6+FTcNqdJLP5W5a508VLJnevmlisswlazKiYNriCQvZ
snmPJrYFYMxe9JIKl1CA8MiUKUx8AUt39KzxkgZrq40VxIrpdxrnUKUCAwEAAaNQ
ME4wHQYDVR0OBBYEFJxuCVGIbPP3LO6GAHAViOCKZ4HIMB8GA1UdIwQYMBaAFJxu
CVGIbPP3LO6GAHAViOCKZ4HIMAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQELBQAD
ggEBAGKn0vYx9Ta5+/X1WRUuADuie6JuNMHUxzYtxwEba/m5lA4nE5f2yoO6Y/Y3
LZDX2Y9kWt+7pGQ2SKOT79gNcnOSc3SGYWkX48J6C1hihhjD3AfD0hb1mgvlJuij
zNnZ7vczOF8AcvBeu8ww5eIrkN6TTshjICg71/deVo9HvjhiCGK0XvL+WL6EQwLe
6/nVVFrPfd0sRZZ5OTJR5nM1kA71oChUw9mHCyrAc3zYyW37k+p8ADRFfON8th8M
1Blel1SpgqlQ22WpYoHbUCSjGt6JKC/HrSHdKBezTuRahOSfqwncAE77Dz4FJaQ5
WD2mk3SZbB2ytAHUDEy3xr697EI=
-----END CERTIFICATE-----"""


class CorpusError(RuntimeError):
    """A repository or corpus invariant failed."""


@dataclass(frozen=True, slots=True)
class RepositoryEntry:
    filename: str
    game: str
    size: int
    last_update: int
    author: str
    downloads: int
    rating_total: int
    rating_count: int
    tags: str

    @property
    def average_rating(self) -> float:
        if self.rating_count == 0:
            return 0.0
        return self.rating_total / self.rating_count


@dataclass(frozen=True, slots=True)
class CorpusCriteria:
    games: tuple[str, ...] = ("gs", "any")
    minimum_average: float = 10.0
    vote_count_greater_than: int = 10
    minimum_downloads: int = 0


class CorpusRepository(Protocol):
    host: str
    port: int
    client_version: str

    def list_entries(self) -> tuple[RepositoryEntry, ...]: ...

    def download(self, entry: RepositoryEntry) -> tuple[bytes, Mapping[str, str]]: ...


class LichRepositoryClient:
    """Read-only client for the protocol implemented by repository.lic."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        client_version: str = DEFAULT_CLIENT_VERSION,
        timeout_seconds: float = 20.0,
    ):
        self.host = host
        self.port = port
        self.client_version = client_version
        self.timeout_seconds = timeout_seconds

    def list_entries(self) -> tuple[RepositoryEntry, ...]:
        response, payload = self._request(
            {
                "action": "list",
                "supported compressions": "gzip",
                "client": self.client_version,
            },
            maximum=MAX_LIST_BYTES,
        )
        if response.get("error"):
            raise CorpusError(f"repository list failed: {response['error']}")
        return parse_repository_list(payload)

    def download(self, entry: RepositoryEntry) -> tuple[bytes, Mapping[str, str]]:
        response, payload = self._request(
            {
                "action": "download",
                "file": entry.filename,
                "game": entry.game,
                "supported compressions": "gzip",
                "client": self.client_version,
            },
            maximum=MAX_SCRIPT_BYTES,
        )
        if response.get("error"):
            raise CorpusError(
                f"repository download failed for {entry.filename}: {response['error']}"
            )
        if response.get("file") != entry.filename:
            raise CorpusError(f"repository returned the wrong file for {entry.filename}")
        expected_md5 = response.get("md5sum", "").casefold()
        actual_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{32}", expected_md5) or actual_md5 != expected_md5:
            raise CorpusError(f"repository MD5 mismatch for {entry.filename}")
        return payload, response

    def _request(
        self, request: Mapping[str, str], *, maximum: int
    ) -> tuple[dict[str, str], bytes]:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=REPOSITORY_CA)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED

        raw_socket = socket.create_connection(
            (self.host, self.port), timeout=self.timeout_seconds
        )
        try:
            with context.wrap_socket(raw_socket, server_hostname=self.host) as secure:
                secure.settimeout(self.timeout_seconds)
                self._verify_peer(secure)
                with secure.makefile("rwb", buffering=0) as stream:
                    stream.write(_encode_header(request))
                    response = _read_header(stream)
                    if "error" in response and "size" not in response:
                        return response, b""
                    size = _bounded_size(response.get("size"), maximum)
                    encoded = _read_exact(stream, size)
        finally:
            raw_socket.close()

        compression = response.get("compression")
        if compression is None:
            payload = encoded
        elif compression == "gzip":
            payload = _decompress_gzip(encoded, maximum)
        else:
            raise CorpusError(f"unsupported repository compression: {compression}")
        if len(payload) > maximum:
            raise CorpusError("decompressed repository payload exceeds configured limit")
        return response, payload

    @staticmethod
    def _verify_peer(secure: ssl.SSLSocket) -> None:
        certificate = secure.getpeercert()
        common_names = {
            value
            for group in certificate.get("subject", ())
            for key, value in group
            if key == "commonName"
        }
        if not common_names.intersection(ALLOWED_CERTIFICATE_COMMON_NAMES):
            raise CorpusError("repository certificate common name is not allowlisted")


def parse_repository_list(payload: bytes) -> tuple[RepositoryEntry, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CorpusError("repository list is not valid UTF-8") from error
    rows = [line.split("\t") for line in text.splitlines() if line]
    if not rows:
        raise CorpusError("repository returned an empty list")
    headers = rows[0]
    required = (
        "file",
        "game",
        "size",
        "last update",
        "author",
        "downloads",
        "rating total",
        "rating count",
        "tags",
    )
    missing = [name for name in required if name not in headers]
    if missing:
        raise CorpusError(f"repository list lacks columns: {', '.join(missing)}")
    indexes = {name: headers.index(name) for name in required}
    entries: list[RepositoryEntry] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) < len(headers):
            raise CorpusError(f"repository list row {number} is truncated")
        try:
            entry = RepositoryEntry(
                filename=row[indexes["file"]],
                game=row[indexes["game"]].casefold(),
                size=int(row[indexes["size"]]),
                last_update=int(row[indexes["last update"]]),
                author=row[indexes["author"]],
                downloads=int(row[indexes["downloads"]]),
                rating_total=int(row[indexes["rating total"]] or 0),
                rating_count=int(row[indexes["rating count"]] or 0),
                tags=row[indexes["tags"]],
            )
        except ValueError as error:
            raise CorpusError(f"repository list row {number} has invalid numbers") from error
        entries.append(entry)
    return tuple(entries)


def select_entries(
    entries: Iterable[RepositoryEntry], criteria: CorpusCriteria
) -> tuple[RepositoryEntry, ...]:
    games = {game.casefold() for game in criteria.games}
    selected = (
        entry
        for entry in entries
        if entry.game in games
        and entry.filename.casefold().endswith(".lic")
        and entry.rating_count > criteria.vote_count_greater_than
        and entry.average_rating >= criteria.minimum_average
        and entry.downloads >= criteria.minimum_downloads
    )
    return tuple(sorted(selected, key=lambda item: (item.game, item.filename.casefold())))


def synchronize_corpus(
    repository: CorpusRepository,
    output: Path,
    criteria: CorpusCriteria,
    *,
    workers: int = 2,
    attempts: int = 3,
) -> dict[str, object]:
    if workers < 1 or workers > 16:
        raise ValueError("workers must be between 1 and 16")
    if attempts < 1 or attempts > 10:
        raise ValueError("attempts must be between 1 and 10")
    entries = select_entries(repository.list_entries(), criteria)
    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    cached_records = _load_cached_records(output / "manifest.json")

    def fetch(entry: RepositoryEntry) -> dict[str, object]:
        game = _safe_game(entry.game)
        filename = _safe_filename(entry.filename)
        destination = output / game / filename
        cached = _cached_record(cached_records, entry, destination)
        if cached is not None:
            return cached
        payload, response = _download_with_retries(
            repository, entry, attempts=attempts
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination, payload)
        record = asdict(entry)
        record.update(
            {
                "average_rating": entry.average_rating,
                "path": str(destination.relative_to(output)),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "repository_md5": response.get("md5sum"),
                "uploaded_by": response.get("uploaded by"),
                "repository_timestamp": _optional_int(response.get("timestamp")),
            }
        )
        return record

    records: list[dict[str, object]] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                records.append(future.result())
            except Exception as error:  # collect all bounded download failures
                failures.append(f"{entry.game}/{entry.filename}: {error}")
    records.sort(key=lambda item: (str(item["game"]), str(item["filename"]).casefold()))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "complete": not failures,
        "source": {
            "host": repository.host,
            "port": repository.port,
            "client_version": repository.client_version,
            "rating_scale_maximum": 10,
        },
        "criteria": {
            "games": list(criteria.games),
            "minimum_average": criteria.minimum_average,
            "vote_count_greater_than": criteria.vote_count_greater_than,
            "minimum_downloads": criteria.minimum_downloads,
            "file_extension": ".lic",
        },
        "selected_count": len(entries),
        "count": len(records),
        "failures": sorted(failures),
        "scripts": records,
    }
    _atomic_write(
        output / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    if failures:
        raise CorpusError("corpus synchronization failed:\n" + "\n".join(sorted(failures)))
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--game", action="append", dest="games")
    result.add_argument("--minimum-average", type=float, default=10.0)
    result.add_argument("--more-than-votes", type=int, default=10)
    result.add_argument("--minimum-downloads", type=int, default=0)
    result.add_argument("--workers", type=int, default=2)
    result.add_argument("--attempts", type=int, default=3)
    result.add_argument("--host", default=DEFAULT_HOST)
    result.add_argument("--port", type=int, default=DEFAULT_PORT)
    result.add_argument("--client-version", default=DEFAULT_CLIENT_VERSION)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 0 <= args.minimum_average <= 10:
        raise SystemExit("--minimum-average must be between 0 and 10")
    if args.more_than_votes < 0:
        raise SystemExit("--more-than-votes must not be negative")
    if args.minimum_downloads < 0:
        raise SystemExit("--minimum-downloads must not be negative")
    criteria = CorpusCriteria(
        games=tuple(args.games or ("gs", "any")),
        minimum_average=args.minimum_average,
        vote_count_greater_than=args.more_than_votes,
        minimum_downloads=args.minimum_downloads,
    )
    repository = LichRepositoryClient(
        host=args.host,
        port=args.port,
        client_version=args.client_version,
    )
    try:
        manifest = synchronize_corpus(
            repository,
            args.output,
            criteria,
            workers=args.workers,
            attempts=args.attempts,
        )
    except (CorpusError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        f"synchronized {manifest['count']} scripts to {args.output}; "
        f"manifest: {args.output / 'manifest.json'}"
    )
    return 0


def _encode_header(values: Mapping[str, str]) -> bytes:
    fields: list[str] = []
    for key, value in values.items():
        if "\t" in key or "\n" in key or "\t" in value or "\n" in value:
            raise CorpusError("repository header contains a control delimiter")
        fields.extend((key, value))
    return ("\t".join(fields) + "\n").encode("utf-8")


def _read_header(stream: BinaryIO) -> dict[str, str]:
    encoded = stream.readline(MAX_HEADER_BYTES + 1)
    if not encoded or len(encoded) > MAX_HEADER_BYTES or not encoded.endswith(b"\n"):
        raise CorpusError("repository response header is missing or oversized")
    try:
        fields = encoded.rstrip(b"\r\n").decode("utf-8").split("\t")
    except UnicodeDecodeError as error:
        raise CorpusError("repository response header is not UTF-8") from error
    if len(fields) % 2:
        raise CorpusError("repository response header has an odd field count")
    return {fields[index].casefold(): fields[index + 1] for index in range(0, len(fields), 2)}


def _bounded_size(value: str | None, maximum: int) -> int:
    if value is None or not value.isdigit():
        raise CorpusError("repository response has no valid size")
    size = int(value)
    if size > maximum:
        raise CorpusError("repository response exceeds configured size limit")
    return size


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise CorpusError("repository response ended before the declared size")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _decompress_gzip(encoded: bytes, maximum: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as compressed:
            payload = compressed.read(maximum + 1)
            trailing = compressed.read(1)
    except (OSError, EOFError) as error:
        raise CorpusError("repository returned invalid gzip data") from error
    if len(payload) > maximum or trailing:
        raise CorpusError("decompressed repository payload exceeds configured limit")
    return payload


def _safe_filename(filename: str) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise CorpusError("repository supplied an unsafe filename")
    return filename


def _safe_game(game: str) -> str:
    if not re.fullmatch(r"[a-z0-9_-]+", game):
        raise CorpusError("repository supplied an unsafe game identifier")
    return game


def _atomic_write(destination: Path, payload: bytes) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)


def _download_with_retries(
    repository: CorpusRepository,
    entry: RepositoryEntry,
    *,
    attempts: int,
) -> tuple[bytes, Mapping[str, str]]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return repository.download(entry)
        except (CorpusError, OSError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _load_cached_records(manifest_path: Path) -> dict[tuple[str, str], Mapping[str, object]]:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    scripts = document.get("scripts") if isinstance(document, dict) else None
    if not isinstance(scripts, list):
        return {}
    records: dict[tuple[str, str], Mapping[str, object]] = {}
    for record in scripts:
        if not isinstance(record, dict):
            continue
        game = record.get("game")
        filename = record.get("filename")
        if isinstance(game, str) and isinstance(filename, str):
            records[(game.casefold(), filename)] = record
    return records


def _cached_record(
    records: Mapping[tuple[str, str], Mapping[str, object]],
    entry: RepositoryEntry,
    destination: Path,
) -> dict[str, object] | None:
    record = records.get((entry.game, entry.filename))
    if record is None or record.get("last_update") != entry.last_update:
        return None
    expected_sha = record.get("sha256")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        return None
    try:
        actual_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    except OSError:
        return None
    if actual_sha != expected_sha:
        return None
    refreshed = asdict(entry)
    refreshed.update(
        {
            "average_rating": entry.average_rating,
            "path": str(Path(entry.game) / entry.filename),
            "sha256": actual_sha,
            "repository_md5": record.get("repository_md5"),
            "uploaded_by": record.get("uploaded_by"),
            "repository_timestamp": record.get("repository_timestamp"),
        }
    )
    return refreshed


if __name__ == "__main__":
    raise SystemExit(main())
