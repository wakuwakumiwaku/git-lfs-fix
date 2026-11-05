"""Run real history filtering in disposable repositories populated by fast-import."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'gitlfsfix'
LEGACY = 'ORDR1.103_reforged.w3x'
TARGET = '-invoice [x]*?.bin'
NEIGHBOR = '-invoice x12.bin'


class LiteralTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='git-lfs-fix-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.env = dict(os.environ, FILTER_BRANCH_SQUELCH_WARNING='1',
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0')
        self.git('init', '-q', '-b', 'main')
        # No staging or git commit; every object/ref belongs to this synthetic fixture.
        files = [LEGACY, TARGET, NEIGHBOR, 'normal.bin', 'keep.txt']
        stream = b''
        for i, name in enumerate(files, 1):
            payload = ('fixture ' + name).encode()
            stream += b'blob\nmark :' + str(i).encode() + b'\ndata ' + str(len(payload)).encode() + b'\n' + payload + b'\n'
        stream += b'commit refs/heads/main\ncommitter Fixture <fixture@example.invalid> 1700000000 +0000\ndata 7\nfixture\n'
        for i, name in enumerate(files, 1):
            stream += ('M 100644 :' + str(i) + ' ' + name + '\n').encode()
        stream += b'\ndone\n'
        self.git('fast-import', '--quiet', input=stream)
        self.git('reset', '--hard', '-q')
        self.original_tip = self.git('rev-parse', 'HEAD').stdout

    def git(self, *args, input=None):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env,
                              input=input, capture_output=True, check=True, timeout=20)

    def invoke(self, *args, cwd=None):
        return subprocess.run([shutil.which('bash'), str(SCRIPT), *args], cwd=cwd or self.repo,
                              env=self.env, capture_output=True, timeout=30)

    def names(self):
        return self.git('ls-tree', '-r', '--name-only', '-z', 'HEAD').stdout.split(b'\0')[:-1]

    def test_explicit_literal_target_does_not_remove_legacy_or_glob_neighbor(self):
        result = self.invoke(TARGET)
        self.assertEqual(result.returncode, 0, result.stderr)
        names = self.names()
        self.assertNotIn(TARGET.encode(), names, 'the requested literal filename must be removed')
        self.assertIn(LEGACY.encode(), names, 'unrequested legacy filename must remain')
        self.assertIn(NEIGHBOR.encode(), names, 'pathspec metacharacters must not expand')
        self.assertIn(b'keep.txt', names)
        self.assertEqual(self.git('rev-parse', 'refs/original/refs/heads/main').stdout, self.original_tip)

    def test_ordinary_target_is_repo_relative_even_from_subdirectory(self):
        nested = self.repo / 'subdir'
        nested.mkdir()
        result = self.invoke('normal.bin', cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b'normal.bin', self.names())
        self.assertIn(LEGACY.encode(), self.names())

    def test_missing_argument_refuses_without_rewriting_any_ref(self):
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0, 'no argument must never trigger a hardcoded history rewrite')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout, self.original_tip)
        self.assertIn(LEGACY.encode(), self.names())
        self.assertEqual(self.git('for-each-ref', '--format=%(refname)', 'refs/original').stdout, b'')

    def test_unsafe_or_extra_arguments_refuse_before_mutation(self):
        for args in [('',), ('../outside',), ('/absolute',), ('.',), ('folder/',),
                     ('folder/../file',), ('normal.bin', 'keep.txt')]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git('rev-parse', 'HEAD').stdout, self.original_tip)
                self.assertIn(LEGACY.encode(), self.names())

    def test_existing_original_refs_are_not_force_overwritten(self):
        self.git('update-ref', 'refs/original/refs/heads/main', self.original_tip.decode().strip())
        result = self.invoke('normal.bin')
        self.assertNotEqual(result.returncode, 0, 'backup refs require deliberate manual recovery, not --force')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout, self.original_tip)
        self.assertEqual(self.git('rev-parse', 'refs/original/refs/heads/main').stdout, self.original_tip)


if __name__ == '__main__':
    unittest.main()
