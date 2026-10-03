import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))

import ableton_relink as ar  # noqa: E402
import fixtures as fx  # noqa: E402

OLD = '/old-machine/Sample Library/'


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ar.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class RelinkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.proj = os.path.join(self.root, 'Song Project')
        self.lib = os.path.join(self.root, 'lib')
        os.makedirs(self.proj)
        self.als = os.path.join(self.proj, 'Song.als')

    def tearDown(self):
        self._tmp.cleanup()

    def project(self, refs, legacy=0):
        fx.make_als(self.als, refs, legacy)

    # -- scan -----------------------------------------------------------------
    def test_scan_lists_only_missing_audio(self):
        here = fx.write(os.path.join(self.root, 'present', 'here.wav'), 10)
        self.project([(here, 10), (OLD + 'gone.wav', 20)])
        missing, legacy = ar.scan(self.proj, None)
        self.assertEqual(list(missing), [('gone.wav', 20)])
        self.assertEqual(legacy, 0)
        code, out, _ = run('scan', self.proj)
        self.assertEqual(code, 1)
        self.assertIn('gone.wav', out)

    def test_windows_style_original_path(self):
        self.project([('C:\\Users\\someone\\Samples\\kick.wav', 5)])
        missing, _ = ar.scan(self.proj, None)
        self.assertEqual(list(missing), [('kick.wav', 5)])

    def test_legacy_format_is_reported_not_crashed(self):
        self.project([], legacy=2)
        code, _, err = run('scan', self.proj)
        self.assertEqual(code, 0)
        self.assertIn('older Live format', err)

    # -- run ------------------------------------------------------------------
    def test_run_copies_from_search_dir_and_relinks(self):
        fx.write(os.path.join(self.lib, 'pack', 'a.wav'), 100)
        self.project([(OLD + 'a.wav', 100)])
        code, out, _ = run('run', self.proj, '--search', self.lib)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'Samples', 'Imported', 'a.wav')))
        self.assertEqual(ar.scan(self.proj, None)[0], {})
        backups = os.listdir(os.path.join(self.proj, 'Backup'))
        self.assertEqual(len(backups), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'Backup', backups[0], 'Song.als')))

    def test_dry_run_changes_nothing(self):
        fx.write(os.path.join(self.lib, 'a.wav'), 100)
        self.project([(OLD + 'a.wav', 100)])
        before = open(self.als, 'rb').read()
        code, out, _ = run('run', self.proj, '--search', self.lib, '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('copy a.wav', out)
        self.assertEqual(open(self.als, 'rb').read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.proj, 'Samples', 'Imported', 'a.wav')))

    def test_file_already_in_project_is_relinked_without_copy(self):
        fx.write(os.path.join(self.proj, 'Samples', 'Elsewhere', 'b.wav'), 7)
        self.project([(OLD + 'b.wav', 7)])
        code, out, _ = run('run', self.proj)
        self.assertEqual(code, 0)
        self.assertIn('keep b.wav', out)
        self.assertEqual(ar.scan(self.proj, None)[0], {})
        self.assertFalse(os.path.exists(os.path.join(self.proj, 'Samples', 'Imported', 'b.wav')))

    def test_size_mismatch_needs_loose(self):
        fx.write(os.path.join(self.lib, 'c.wav'), 99)
        self.project([(OLD + 'c.wav', 100)])
        code, out, _ = run('run', self.proj, '--search', self.lib)
        self.assertEqual(code, 2)
        self.assertIn('--loose', out)
        code, out, _ = run('run', self.proj, '--search', self.lib, '--loose')
        self.assertEqual(code, 0)
        self.assertIn('name-only', out)

    def test_same_name_different_sizes_get_distinct_files(self):
        fx.write(os.path.join(self.lib, 'one', 'kick.wav'), 10)
        fx.write(os.path.join(self.lib, 'two', 'kick.wav'), 20)
        self.project([(OLD + 'x/kick.wav', 10), (OLD + 'y/kick.wav', 20)])
        code, out, _ = run('run', self.proj, '--search', self.lib)
        self.assertEqual(code, 0, out)
        imported = sorted(os.listdir(os.path.join(self.proj, 'Samples', 'Imported')))
        self.assertEqual(imported, ['kick__10.wav', 'kick__20.wav'])

    def test_unresolved_is_reported_and_exit_code_2(self):
        self.project([(OLD + 'nowhere.wav', 1)])
        code, out, _ = run('run', self.proj, '--search', self.root, '--json')
        self.assertEqual(code, 2)
        report = json.loads(out)
        self.assertEqual(report['unresolved'], ['nowhere.wav'])
        self.assertEqual(report['remaining'], ['nowhere.wav'])

    def test_backup_dir_is_not_searched(self):
        fx.write(os.path.join(self.proj, 'Backup', 'old', 'd.wav'), 3)
        self.project([(OLD + 'd.wav', 3)])
        code, _, _ = run('run', self.proj)
        self.assertEqual(code, 2)

    def test_single_als_path_only_touches_that_file(self):
        fx.write(os.path.join(self.lib, 'e.wav'), 4)
        self.project([(OLD + 'e.wav', 4)])
        other = os.path.join(self.proj, 'Other.als')
        fx.make_als(other, [(OLD + 'e.wav', 4)])
        run('run', self.als, '--search', self.lib)
        self.assertEqual(ar.scan(self.proj, ['Song.als'])[0], {})
        self.assertEqual(len(ar.scan(self.proj, ['Other.als'])[0]), 1)

    def test_names_with_xml_special_characters(self):
        fx.write(os.path.join(self.lib, 'a&b #1.wav'), 6)
        self.project([(OLD + 'a&amp;b #1.wav', 6)])
        code, out, _ = run('run', self.proj, '--search', self.lib)
        self.assertEqual(code, 0, out)
        self.assertEqual(ar.scan(self.proj, None)[0], {})

    # -- ssh (a shim runs the "remote" command locally) -------------------------
    def test_ssh_search_with_mount_mapping(self):
        remote_root = os.path.join(self.root, 'remote', 'samples')
        fx.write(os.path.join(remote_root, 'pack', 'f.wav'), 11)
        shim_dir = os.path.join(self.root, 'bin')
        os.makedirs(shim_dir)
        shim = os.path.join(shim_dir, 'ssh')
        with open(shim, 'w') as f:
            f.write('#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\nexec sh -c "$*"\n')
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)
        old_path = os.environ['PATH']
        os.environ['PATH'] = shim_dir + os.pathsep + old_path
        try:
            self.project([(OLD + 'f.wav', 11)])
            code, out, _ = run('run', self.proj, '--ssh', 'fakehost', '--ssh-root', remote_root,
                               '--map', '%s=%s' % (remote_root, remote_root))
        finally:
            os.environ['PATH'] = old_path
        self.assertEqual(code, 0, out)
        self.assertIn('ssh://fakehost', out)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'Samples', 'Imported', 'f.wav')))

    def test_incomplete_copy_leaves_no_file(self):
        src = fx.write(os.path.join(self.lib, 'g.wav'), 10)
        dst = os.path.join(self.root, 'out', 'g.wav')
        os.makedirs(os.path.dirname(dst))
        with self.assertRaises(IOError):
            ar.fetch(src, dst, [], 999)
        self.assertEqual(os.listdir(os.path.dirname(dst)), [])

    def test_failed_write_keeps_original(self):
        self.project([(OLD + 'h.wav', 1)])
        before = open(self.als, 'rb').read()
        real = ar.ET.fromstring
        ar.ET.fromstring = lambda *_: (_ for _ in ()).throw(ValueError('boom'))
        try:
            with self.assertRaises(ValueError):
                ar.write_als(self.als, 'not xml')
        finally:
            ar.ET.fromstring = real
        self.assertEqual(open(self.als, 'rb').read(), before)
        self.assertEqual([f for f in os.listdir(self.proj) if f.endswith('tmp')], [])

    def test_invalid_project_exits(self):
        with self.assertRaises(SystemExit):
            run('scan', self.root)


if __name__ == '__main__':
    unittest.main()
