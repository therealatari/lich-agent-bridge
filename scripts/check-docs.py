#!/usr/bin/env python3
"""Check that repository-local links in Markdown documentation resolve."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRECTORIES = {".git", ".lab-cache", "node_modules"}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in REPOSITORY_ROOT.rglob("*.md")
        if not any(part in IGNORED_DIRECTORIES for part in path.parts)
    )


def link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def broken_local_links() -> tuple[int, list[tuple[Path, str]]]:
    files = markdown_files()
    broken: list[tuple[Path, str]] = []
    for document in files:
        in_fence = False
        for line in document.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for raw_target in MARKDOWN_LINK.findall(line):
                target = link_target(raw_target)
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                relative_path = unquote(parsed.path)
                candidate = (
                    REPOSITORY_ROOT / relative_path.lstrip("/")
                    if relative_path.startswith("/")
                    else document.parent / relative_path
                ).resolve()
                if not candidate.is_relative_to(REPOSITORY_ROOT) or not candidate.exists():
                    broken.append((document.relative_to(REPOSITORY_ROOT), target))
    return len(files), broken


def main() -> int:
    file_count, broken = broken_local_links()
    print(f"checked {file_count} Markdown files")
    if not broken:
        print("broken local links: 0")
        return 0
    print(f"broken local links: {len(broken)}", file=sys.stderr)
    for document, target in broken:
        print(f"{document}: {target}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
