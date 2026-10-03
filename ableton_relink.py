#!/usr/bin/env python3
"""ableton-relink: find the missing samples of an Ableton Live set and relink them.

Reads the .als file(s) of a project, lists every audio file Live can no longer find,
searches local folders (and optionally a remote machine over SSH) for the same file,
copies what it finds into <project>/Samples/Imported and rewrites the paths inside the
.als so Live opens the set without a "Missing Media Files" dialog.

  ableton-relink scan MyProject
  ableton-relink run  MyProject --search ~/Samples --dry-run
  ableton-relink run  MyProject --search ~/Samples --ssh nas --ssh-root /volume1/Samples

Standard library only. Python 3.8+.
"""
import argparse
import gzip
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

__version__ = '0.1.0'

AUDIO_EXT = ('.wav', '.aif', '.aiff', '.mp3', '.flac', '.ogg', '.m4a')
DEFAULT_SKIP_DIRS = ('Backup', '#snapshot', '#recycle', '@eaDir', '.Trash')
CONFIG_FILES = ('ableton-relink.json', '~/.config/ableton-relink.json')


def log(*a):
    print(*a, file=sys.stderr)


# --------------------------------------------------------------------------- .als I/O

def split_name(path):
    """Basename of a path written on any OS (Live stores the original machine's path)."""
    return re.split(r'[\\/]', path)[-1]


def field(block, key):
    m = re.search(r'<%s Value="(.*?)"' % key, block)
    return html.unescape(m.group(1)) if m else ''


def read_als(path):
    return gzip.open(path).read().decode('utf-8')


def write_als(path, text):
    """Write to a temp file, check it parses, then replace. The original survives any failure."""
    tmp = path + '.relink-tmp'
    try:
        with gzip.open(tmp, 'wb') as f:
            f.write(text.encode('utf-8'))
        ET.fromstring(gzip.open(tmp).read())  # raises if we produced invalid XML
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def als_files(project, only):
    files = sorted(f for f in os.listdir(project) if f.endswith('.als'))
    return [f for f in files if f in only] if only else files


def ref_exists(project, block):
    p = field(block, 'Path')
    if p and os.path.exists(p):
        return True
    rel = field(block, 'RelativePath')
    return bool(rel and field(block, 'RelativePathType') == '3'
                and os.path.exists(os.path.join(project, rel)))


def scan(project, als_names):
    """Return (missing, legacy_refs).

    missing: {(name, size): {'path': original path, 'als': [file names]}}
    legacy_refs: FileRef blocks in a format this tool cannot read (Live 10 and older).
    """
    missing, legacy = {}, 0
    for als in als_files(project, als_names):
        for m in re.finditer(r'<FileRef>.*?</FileRef>', read_als(os.path.join(project, als)), re.S):
            block = m.group(0)
            if '<Path Value=' not in block:
                legacy += 1
                continue
            path = field(block, 'Path')
            if not path.lower().endswith(AUDIO_EXT) or ref_exists(project, block):
                continue
            key = (split_name(path), int(field(block, 'OriginalFileSize') or 0))
            entry = missing.setdefault(key, {'path': path, 'als': []})
            if als not in entry['als']:
                entry['als'].append(als)
    return missing, legacy


# --------------------------------------------------------------------------- searching

def index_local(dirs, wanted, skip_dirs):
    """{name: [(size, path), ...]} for every wanted file name under dirs (search order kept)."""
    found = {}
    for root in dirs:
        for r, ds, fs in os.walk(root):
            ds[:] = [d for d in ds if d not in skip_dirs]
            for f in fs:
                if f in wanted:
                    p = os.path.join(r, f)
                    try:
                        found.setdefault(f, []).append((os.path.getsize(p), p))
                    except OSError:
                        pass
    return found


def ssh_search(remote, names, skip_dirs):
    """Run find on a remote host. Returns {name: [(size, 'ssh://host/abs/path'), ...]}."""
    host = remote['host']
    roots = ' '.join(shlex.quote(r) for r in remote['roots'])
    prune = ' -o '.join('-name %s' % shlex.quote(d) for d in skip_dirs)
    script = (
        'T=$(mktemp); cat > "$T"; '
        'find %s \\( %s \\) -prune -o -type f -print 2>/dev/null '
        "| awk -F/ 'NR==FNR{w[$0]=1;next} ($NF in w)' \"$T\" - "
        '| while IFS= read -r p; do printf "%%s\\t%%s\\n" "$(wc -c < "$p" | tr -d " ")" "$p"; done; '
        'rm -f "$T"' % (roots, prune))
    log('searching %s (%d names)...' % (host, len(names)))
    r = subprocess.run(['ssh', '-o', 'ConnectTimeout=10', host, script],
                       input='\n'.join(names) + '\n', capture_output=True, text=True)
    if r.returncode != 0 and not r.stdout:
        log('ssh search failed on %s: %s' % (host, r.stderr.strip()[:200]))
        return {}
    found = {}
    for line in r.stdout.splitlines():
        size, _, p = line.partition('\t')
        if p and size.isdigit():
            found.setdefault(split_name(p), []).append((int(size), 'ssh://%s%s' % (host, p)))
    return found


def choose(cands, size, loose):
    """First candidate whose size matches the size Live recorded (0 = unknown = any).

    Returns (source, exact, source_size). With loose=True a name-only match is accepted
    as a fallback.
    """
    for sz, p in cands:
        if not size or sz == size:
            return p, True, sz
    if loose and cands:
        return cands[0][1], False, cands[0][0]
    return None, False, 0


def resolve(missing, project, search_dirs, remotes, skip_dirs, loose):
    """Find a source for every missing key. Returns (sources, name_only_hints)."""
    sources, hints = {}, {}

    def run_step(label, cands_by_name):
        for key in [k for k in missing if k not in sources]:
            cands = cands_by_name.get(key[0], [])
            src, exact, sz = choose(cands, key[1], loose)
            if src:
                sources[key] = (src, exact, sz)
            elif cands:
                hints.setdefault(key, cands[0][1])
        log('%s: %d resolved so far' % (label, len(sources)))

    wanted = {k[0] for k in missing}
    run_step('project', index_local([project], wanted, [d for d in skip_dirs]))
    left = {k[0] for k in missing if k not in sources}
    if left and search_dirs:
        run_step('search dirs', index_local(search_dirs, left, skip_dirs))
    for remote in remotes:
        left = {k[0] for k in missing if k not in sources}
        if not left:
            break
        run_step('ssh ' + remote['host'], ssh_search(remote, sorted(left), skip_dirs))
    return sources, {k: v for k, v in hints.items() if k not in sources}


# --------------------------------------------------------------------------- copying

def local_view_of_remote(src, remotes):
    """Map ssh://host/path to a locally mounted copy if a mount mapping covers it."""
    host, _, rpath = src[len('ssh://'):].partition('/')
    rpath = '/' + rpath
    for remote in remotes:
        if remote['host'] != host:
            continue
        for rroot, lroot in remote.get('mounts', {}).items():
            if rpath.startswith(rroot.rstrip('/') + '/'):
                local = os.path.join(os.path.expanduser(lroot), rpath[len(rroot.rstrip('/')) + 1:])
                if os.path.exists(local):
                    return local
    return None


def fetch(src, dst, remotes, size):
    """Copy src to dst via a .part file; the file only appears under its final name if complete."""
    part = dst + '.part'
    try:
        local = local_view_of_remote(src, remotes) if src.startswith('ssh://') else src
        if local:
            shutil.copyfile(local, part)
            how = 'local' if local == src else 'mount'
        else:
            host, _, rpath = src[len('ssh://'):].partition('/')
            with open(part, 'wb') as f:
                subprocess.run(['ssh', host, 'cat ' + shlex.quote('/' + rpath)], stdout=f, check=True)
            how = 'ssh'
        if size and os.path.getsize(part) != size:
            raise IOError('incomplete copy of %s (%d of %d bytes)' % (src, os.path.getsize(part), size))
        os.replace(part, dst)
        return how
    finally:
        if os.path.exists(part):
            os.remove(part)


def destination_names(keys):
    """File name to use inside Samples/Imported. Same name + different size => size suffix."""
    sizes = {}
    for name, size in keys:
        sizes.setdefault(name, set()).add(size)
    out = {}
    for name, size in keys:
        if len(sizes[name]) == 1:
            out[(name, size)] = name
        else:
            stem, ext = os.path.splitext(name)
            out[(name, size)] = '%s__%d%s' % (stem, size, ext)
    return out


# --------------------------------------------------------------------------- patching

def patch(project, als_names, targets):
    """Rewrite FileRefs. targets: {(name, size): absolute path inside the project}.

    Backs up every changed .als to <project>/Backup/pre-relink_<timestamp>/ first.
    """
    backup = os.path.join(project, 'Backup', 'pre-relink_' + time.strftime('%Y%m%d_%H%M%S'))
    counts = {}
    for als in als_files(project, als_names):
        fp = os.path.join(project, als)
        text, fixed = read_als(fp), [0]

        def fix(m):
            block = m.group(0)
            if '<Path Value=' not in block or ref_exists(project, block):
                return block
            key = (split_name(field(block, 'Path')), int(field(block, 'OriginalFileSize') or 0))
            target = targets.get(key)
            if not target:
                return block
            rel = html.escape(os.path.relpath(target, project).replace(os.sep, '/'), quote=True)
            absolute = html.escape(target, quote=True)
            block = re.sub(r'<RelativePathType Value=".*?"', '<RelativePathType Value="3"', block)
            block = re.sub(r'<RelativePath Value=".*?"', lambda _: '<RelativePath Value="%s"' % rel, block)
            block = re.sub(r'<Path Value=".*?"', lambda _: '<Path Value="%s"' % absolute, block)
            fixed[0] += 1
            return block

        new = re.sub(r'<FileRef>.*?</FileRef>', fix, text, flags=re.S)
        if fixed[0]:
            os.makedirs(backup, exist_ok=True)
            shutil.copy2(fp, os.path.join(backup, als))
            write_als(fp, new)
        counts[als] = fixed[0]
    return counts, (backup if os.path.isdir(backup) else None)


def live_is_running():
    if not shutil.which('pgrep'):
        return False
    return subprocess.run(['pgrep', '-f', 'Ableton Live|Live [0-9]+'], capture_output=True).returncode == 0


# --------------------------------------------------------------------------- CLI

def load_config(path):
    candidates = [path] if path else [os.path.expanduser(p) for p in CONFIG_FILES]
    for p in candidates:
        if p and os.path.isfile(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    if path:
        sys.exit('config file not found: %s' % path)
    return {}


def build_parser():
    ap = argparse.ArgumentParser(
        prog='ableton-relink',
        description='Find and relink missing samples of Ableton Live sets.')
    ap.add_argument('--version', action='version', version=__version__)
    ap.add_argument('cmd', choices=['scan', 'run'],
                    help='scan: list missing samples. run: find, copy into the project, relink.')
    ap.add_argument('project', help='project folder (contains the .als files) or a single .als file')
    ap.add_argument('--search', action='append', default=[], metavar='DIR',
                    help='local folder to search (repeatable)')
    ap.add_argument('--ssh', metavar='HOST', help='also search this host over SSH')
    ap.add_argument('--ssh-root', action='append', default=[], metavar='DIR',
                    help='folder to search on the SSH host (repeatable)')
    ap.add_argument('--map', action='append', default=[], metavar='REMOTE=LOCAL',
                    help='remote folder that is also mounted locally (copy from the mount, not via ssh)')
    ap.add_argument('--als', nargs='*', help='only these .als file names (default: all in the folder)')
    ap.add_argument('--loose', action='store_true',
                    help='accept same-name files whose size differs from what Live recorded')
    ap.add_argument('--dry-run', action='store_true', help='show the plan, change nothing')
    ap.add_argument('--config', metavar='FILE', help='JSON config (default: ./ableton-relink.json, '
                                                     '~/.config/ableton-relink.json)')
    ap.add_argument('--json', action='store_true', help='print a JSON report on stdout')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)

    project = os.path.abspath(args.project)
    als_only = args.als
    if os.path.isfile(project) and project.endswith('.als'):
        project, als_only = os.path.dirname(project), [os.path.basename(project)]
    if not os.path.isdir(project) or not als_files(project, als_only):
        sys.exit('no .als file found in %s' % project)

    search_dirs = [os.path.abspath(os.path.expanduser(d)) for d in cfg.get('search', []) + args.search]
    skip_dirs = tuple(cfg.get('skip_dirs', DEFAULT_SKIP_DIRS))
    remotes = [dict(r) for r in cfg.get('ssh', [])]
    if args.ssh:
        mounts = dict(m.split('=', 1) for m in args.map)
        remotes.append({'host': args.ssh, 'roots': args.ssh_root, 'mounts': mounts})
    remotes = [r for r in remotes if r.get('roots')]

    missing, legacy = scan(project, als_only)
    log('%d missing sample(s)' % len(missing))
    if legacy and not missing:
        log('warning: %d file reference(s) use an older Live format (<= Live 10) that this tool '
            'cannot read; nothing was checked for them' % legacy)
    report = {'missing': len(missing), 'resolved': [], 'unresolved': [], 'name_only': [],
              'patched': {}, 'backup': None, 'remaining': []}

    if args.cmd == 'scan' or not missing:
        for (name, size), d in sorted(missing.items()):
            print('%10d  %s  [%s]' % (size, name, ', '.join(d['als'])))
            report['unresolved'].append(name)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1 if missing and args.cmd == 'scan' else 0

    say = (lambda *a: None) if args.json else print
    sources, hints = resolve(missing, project, search_dirs, remotes, skip_dirs, args.loose)
    dest_dir = os.path.join(project, 'Samples', 'Imported')
    names = destination_names(list(missing))
    plan = []
    for key, (src, exact, size) in sorted(sources.items()):
        inside = not src.startswith('ssh://') and os.path.abspath(src).startswith(project + os.sep)
        plan.append((key, src, exact, src if inside else os.path.join(dest_dir, names[key]), size))

    for key, src, exact, dst, _ in plan:
        say('%s %s%s\n       <- %s' % ('keep' if src == dst else 'copy', key[0],
                                         '' if exact else '   (name-only match, size differs)', src))
        report['resolved'].append({'name': key[0], 'from': src, 'to': dst, 'exact': exact})
    for key in sorted(k for k in missing if k not in sources):
        hint = hints.get(key)
        say('MISS %s%s' % (key[0], '   (same name found with a different size: %s; use --loose)' % hint
                             if hint else ''))
        report['unresolved'].append(key[0])
        if hint:
            report['name_only'].append({'name': key[0], 'candidate': hint})

    if args.dry_run:
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    os.makedirs(dest_dir, exist_ok=True)
    for key, src, exact, dst, size in plan:
        if src != dst and not os.path.exists(dst):
            how = fetch(src, dst, remotes, size)
            log('copied (%s) %s' % (how, key[0]))
    counts, backup = patch(project, als_only, {key: dst for key, _, _, dst, _ in plan})
    remaining, _ = scan(project, als_only)
    report.update(patched=counts, backup=backup, remaining=sorted(k[0] for k in remaining))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        say('\n== result')
        for als, c in counts.items():
            say('  %s: %d reference(s) rewritten' % (als, c))
        say('  backup: %s' % (backup or 'nothing changed'))
        say('  still missing: %d' % len(remaining))
        for k in sorted(remaining):
            say('    - %s' % k[0])
    if live_is_running():
        log('warning: Live is running. If one of these sets is open, close it WITHOUT saving and '
            'reopen it, otherwise saving overwrites the relinked paths.')
    return 2 if remaining else 0


if __name__ == '__main__':
    sys.exit(main())
