# ableton-relink

Find and relink the missing samples of Ableton Live sets, from local folders or a remote machine (NAS, another Mac) over SSH.

![demo](demo/demo.gif)

Live's own *Missing Media Files* dialog stops being useful when you moved your sample library, switched machines, changed cloud storage, or opened a set that was made on someone else's computer. `ableton-relink` reads the `.als` file(s), lists every audio file Live can no longer find, searches for the same file, **copies it into the project** (`Samples/Imported`), and rewrites the paths inside the set. The relinked samples live inside the project afterwards, so those references do not break again (other dependencies such as plugins or presets are not touched).

- Matches by file name **and** the file size Live recorded. That is a strong hint, not proof of identical audio (it is not a content hash); `scan` prints the sizes so you can check suspicious ones.
- Handles every `.als` in a project folder at once (`Set.als`, `Set2.als`, `Set3.als`, ...).
- Searches several local folders and, optionally, a remote host over SSH. Remote folders that are also mounted locally are copied from the mount (fast); otherwise it streams the file through `ssh`.
- Backs up every `.als` it touches before changing it.
- Standard library only. Python 3.8+. One file.

> **Status: beta.** It edits your project files. A backup is made every time, writes are atomic, and the result is validated, but see [Limits](#limits) and keep your own copy of sets you care about.

## Install

```bash
pip install git+https://github.com/gyujeongion/ableton-relink
# or just download ableton_relink.py and run it with python3
```

## Usage

```bash
# 1. list what is missing (exit code 1 if anything is)
ableton-relink scan "My Song Project"

# 2. see what it would do, change nothing
ableton-relink run "My Song Project" --search ~/Music/Samples --dry-run

# 3. do it
ableton-relink run "My Song Project" --search ~/Music/Samples --search /Volumes/SampleDrive
```

`PROJECT` is the project folder (the one containing the `.als` files) or a single `.als` file. With a single file, only that set is changed.

### Searching a NAS or another machine

```bash
ableton-relink run "My Song Project" \
  --ssh my-nas --ssh-root /volume1/Samples \
  --map /volume1/Samples=/Volumes/Samples
```

`--ssh` uses your normal SSH setup (`~/.ssh/config`, keys), so the host needs key-based login. `--map REMOTE=LOCAL` tells the tool that the remote folder is also mounted on this machine; files are then copied from the mount instead of through SSH.

### Config file

Put your usual folders in `./ableton-relink.json` or `~/.config/ableton-relink.json` (see [`examples/ableton-relink.example.json`](examples/ableton-relink.example.json)) and the command line shrinks to `ableton-relink run "My Song Project"`.

### Options

| Option | Meaning |
|---|---|
| `--search DIR` | local folder to search (repeatable) |
| `--ssh HOST`, `--ssh-root DIR`, `--map REMOTE=LOCAL` | search a remote host |
| `--als NAME.als ...` | only these sets |
| `--loose` | accept same-name files whose size differs from what Live recorded |
| `--dry-run` | print the plan, change nothing |
| `--json` | machine-readable report on stdout |
| `--config FILE` | config file path |

Exit codes: `0` everything resolved, `2` something is still missing, `1` from `scan` when anything is missing.

## How it works

A `.als` file is gzip-compressed XML. Every sample is a `<FileRef>` with the path from the machine that made the set, a project-relative path, and the original file size. The tool

1. finds the `<FileRef>`s whose file exists neither at the stored path nor at the project-relative path,
2. looks for each name in the project folder, your search folders, then the remote host, and keeps the first candidate whose size matches,
3. copies it to `Samples/Imported` (a name clash with a different size gets a `__<size>` suffix),
4. backs up the set to `<project>/Backup/pre-relink_<timestamp>/`, rewrites the three path fields of each matched reference, and checks the result is valid XML,
5. scans again and reports what is still missing.

Audio files and your library are never modified; files are only copied into the project.

## Undo / restore

Every changed set is copied to `<project>/Backup/pre-relink_<timestamp>/` before it is modified. To undo, close the set in Live and copy the file from that folder back over the `.als` in the project folder. Samples copied into `Samples/Imported` can stay; they are not referenced by the restored set.

Safety details: the new `.als` is written to a temp file, parsed to confirm it is valid XML, and only then moved over the original, so a failed write leaves the original untouched. Samples are copied to a `.part` file, size-checked, and renamed only when complete. Existing files in the project are never overwritten.

## Missing samples that exist nowhere

Whatever `run` could not find is listed as `MISS` (and in `--json` under `unresolved`). If the missing files come from a sample service you subscribe to, download them by exact file name into `<project>/Samples/Imported/` and run the command again; they are picked up from the project folder in the first step. Check that the downloaded file has the size Live recorded (`scan` prints it); a same-named file from a different pack can differ.

## Use it from Claude Code

[`claude-skill/SKILL.md`](claude-skill/SKILL.md) is a skill that drives this tool and, for the leftovers, searches and downloads from a sample-service MCP server if you have one connected. Copy the folder into `~/.claude/skills/ableton-relink/`.

## Limits

- Tested with sets saved by **Live 12.2** on macOS. Live 11 uses the same text-path schema and should work, but I have not tested it.
- **Live 10 and older** store paths in a different structure. The tool detects this, tells you, and does not touch those references.
- Windows-style paths stored in a set are understood (the file name is extracted from either separator), but running the tool on Windows is untested.
- Only audio references are handled (`.wav .aif .aiff .mp3 .flac .ogg .m4a`). Presets, devices, and packs are not.
- **Close the set in Live first.** If a set is open and you save it afterwards, Live writes its own in-memory paths back and undoes the relink. Reopen after running the tool.
- The set is edited with text substitution, not a full XML round-trip, to keep Live's formatting. A backup is always made, but keep your own as well for sets you care about.

## Development

```bash
python3 -m unittest discover -s tests -v
vhs demo/demo.tape      # re-record the GIF (needs https://github.com/charmbracelet/vhs)
```

The tests build small fake `.als` files and silent placeholder samples; no real audio or sets are in the repo.

## License

MIT
