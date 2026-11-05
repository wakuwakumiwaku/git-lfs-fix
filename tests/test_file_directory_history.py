"""A filename can become a directory without making its descendants targets."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "gitlfsfix"
BASH = shutil.which("bash")
assert BASH is not None, "Bash is required"


class FileDirectoryHistoryTests(unittest.TestCase):
    def test_file_directory_transition_preserves_descendants_on_every_ref(self):
        for target in ("asset", "-asset [x]*?", "nested/asset"):
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="lfs-history-shape-") as temp:
                repo = Path(temp)
                env = {"PATH": "/usr/bin:/bin", "HOME": temp, "TMPDIR": temp,
                       "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                       "FILTER_BRANCH_SQUELCH_WARNING": "1", "GIT_TERMINAL_PROMPT": "0"}
                def git(*args, data=None):
                    return subprocess.run(["/usr/bin/git", *args], cwd=repo, env=env,
                                          input=data, capture_output=True, check=True, timeout=20).stdout
                git("init", "-q", "-b", "main")
                # Use fast-import, not staging or committing. All refs are fixture-owned.
                stream = ("blob\nmark :1\ndata 3\nold\n"
                          "blob\nmark :2\ndata 4\nkeep\n"
                          "commit refs/heads/main\nmark :3\ncommitter Fixture <fixture@example.invalid> 1700000000 +0000\ndata 3\none\n"
                          f"M 100644 :1 {target}\nM 100644 :2 keep.txt\n\n"
                          "commit refs/heads/main\nmark :4\ncommitter Fixture <fixture@example.invalid> 1700000001 +0000\ndata 3\ntwo\nfrom :3\n"
                          f"D {target}\nM 100644 :2 {target}/child.txt\n\n"
                          "reset refs/heads/old-file\nfrom :3\n\ndone\n").encode()
                git("fast-import", "--quiet", data=stream)
                git("reset", "--hard", "-q")
                original = git("rev-parse", "main").strip()
                result = subprocess.run([BASH, str(SCRIPT), "./" + target], cwd=repo,
                                        env=env, capture_output=True, timeout=40)
                self.assertEqual(result.returncode, 0, "file-to-directory history must filter successfully: " + result.stderr.decode())
                self.assertEqual(git("rev-parse", "refs/original/refs/heads/main").strip(), original)
                for ref in ("main", "old-file"):
                    for commit in git("rev-list", ref).splitlines():
                        entries = git("ls-tree", "-r", "--name-only", "-z", commit.decode()).split(b"\0")
                        self.assertNotIn(target.encode(), entries, "only the exact file entry is removed")
                        self.assertIn(b"keep.txt", entries)
                self.assertEqual(git("show", f"main:{target}/child.txt"), b"keep")


if __name__ == "__main__":
    unittest.main()
