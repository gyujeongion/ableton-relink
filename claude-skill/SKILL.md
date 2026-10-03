---
name: ableton-relink
description: Find and relink missing samples of an Ableton Live project. Use when the user mentions Missing Media Files, missing samples, a broken sample path in a Live set, relinking, moving or collecting samples, or shares a Missing Media Files screenshot. Searches local folders and optionally a remote host over SSH, copies matches into the project and rewrites the .als paths.
---

# ableton-relink

Wraps `ableton_relink.py` (this repo). Producer Pal / the Live Object Model cannot relink samples; editing the `.als` XML is the reliable way.

## Steps

1. **Scan.** Locate the project folder (contains the `.als`). Close the set in Live first, or tell the user to close it without saving.
   ```bash
   ableton-relink scan "<project>"
   ```
   Compare the count with the number in Live's Missing Media Files dialog if a screenshot was provided.
2. **Find the user's sample folders.** Ask where their library lives if there is no `ableton-relink.json`; do not guess paths. Optional remote host: `--ssh HOST --ssh-root DIR [--map REMOTE=LOCAL]`.
3. **Dry run**, then show the plan (`copy` / `keep` / `MISS` lines) in one message:
   ```bash
   ableton-relink run "<project>" --search "<dir>" --dry-run
   ```
4. **Run** without `--dry-run`. It backs up each `.als` to `Backup/pre-relink_<timestamp>/` first.
5. **Verify.** The tool re-scans and prints "still missing". Optionally open the set in Live and confirm no dialog appears; tell the user to save once.

## Leftovers (`MISS`)

- Report them first. Do not substitute a similar-sounding sample.
- If a sample-service MCP server (for example Splice) is connected: search by the **exact file name**, accept only an identical name, and tell the user how many download credits it may cost before downloading. Save into `<project>/Samples/Imported/` under the original name, check the size against the one `scan` printed, then run again.
- `--loose` accepts same-name files with a different size. Only use it if the user agrees.

## Rules

- Never modify files in the user's library; the tool only copies.
- Never overwrite an existing project file; name clashes get a `__<size>` suffix.
- If the set is open in Live, do not patch it.
