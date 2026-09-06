# Optional upstream patches

These are narrow overlays for external Lich scripts, not complete upstream
scripts or required LAB dependencies. Check the installed version, inspect the
diff, and run a dry run before applying anything. Preserve upstream attribution
and verify redistribution terms.

Use paths for your own source checkouts. For example, from the Lich root:

```sh
patch --dry-run -p1 < /path/to/lich-agent-bridge/patches/PATCH_FILE
```

Apply only after review and authorization. If a patch is already applied or its
context no longer matches, inspect the current upstream source rather than
forcing it.

## ELoot

- `eloot-value-appraisal-bulk-sale.patch` guards a bulk-sale path from bypassing
  configured per-item appraisal.
- `eloot-disk-routing.patch` handles current-run disk references and rescanning
  after disk arrival at the locksmith pool.
- `eloot-refresh-sell-containers.patch` is an experimental seller-only forced
  scan, not evidence of a general stale-container defect. It adds round trips
  and is independent of the disk-routing fix.

The corresponding ELoot harnesses require an explicit external script path:

```sh
ELOOT_SOURCE=/path/to/Lich5/scripts/eloot.lic ruby tests/eloot_disk_run_state_test.rb
```

Run from the LAB checkout and select the harness matching the reviewed overlay.
These tests are optional; they cannot run without the external source.
A test that proves a forced scan occurs does not prove a cache was stale.
See [container compatibility](../wiki/lich/Lich-5.20-Container-Compatibility.md).

## Bigshot

`bigshot-flee-depth.patch` adds a profile-controlled movement count while
preserving the default behavior. LAB does not distribute personal values,
routes, or hunting profiles for this option.

Local overlays may be overwritten or superseded by upstream updates. Recheck
each one independently; a patch file's presence does not mean it is installed,
needed, or verified in the current game environment.
