"""Root discovery must not redirect history filtering into a sibling repository."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "gitlfsfix"
BASH = shutil.which("bash")
GIT = shutil.which("git")
assert BASH is not None and GIT is not None
SPY = r'''import json, os, sys
from pathlib import Path
root = Path(os.environ["ROOT_SPY_ROOT"]).resolve()
assert Path.cwd().resolve().is_relative_to(root)
assert Path(sys.argv[0]).resolve() == root / "bin" / "git"
assert sys.argv[1] in ("rev-parse", "filter-branch")
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
os.execv(os.environ["ROOT_SPY_REAL_GIT"], [os.environ["ROOT_SPY_REAL_GIT"], *sys.argv[1:]])
'''


class RepositoryRootTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="git-root-spy-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        tools = self.root / "bin"
        tools.mkdir()
        spy = tools / "git"
        spy.write_text(f"#!{sys.executable}\n" + SPY)
        spy.chmod(0o700)
        self.env = {"PATH": str(tools) + os.pathsep + "/usr/bin:/bin", "HOME": str(self.root),
                    "TMPDIR": str(self.root), "XDG_CACHE_HOME": str(self.root / "cache"),
                    "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0", "FILTER_BRANCH_SQUELCH_WARNING": "1",
                    "ROOT_SPY_ROOT": str(self.root), "ROOT_SPY_REAL_GIT": GIT}

    def git(self, repo, *args, input=None):
        assert GIT is not None
        return subprocess.run([GIT, "-C", str(repo), *args], env=self.env, input=input,
                              capture_output=True, check=True, timeout=20).stdout

    def repository(self, name):
        repo = self.root / name
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        # No staging, commits, remotes, hooks or user configuration.
        stream = (b"blob\nmark :1\ndata 7\nfixture\n"
                  b"commit refs/heads/main\ncommitter Fixture <fixture@example.invalid> 1700000000 +0000\n"
                  b"data 7\nfixture\nM 100644 :1 target.bin\nM 100644 :1 keep.txt\n\ndone\n")
        self.git(repo, "fast-import", "--quiet", input=stream)
        self.git(repo, "reset", "--hard", "-q")
        (repo / "subdir").mkdir()
        return repo, self.git(repo, "rev-parse", "HEAD")

    def invoke(self, repo):
        assert BASH is not None
        result = subprocess.run([BASH, str(SCRIPT), "target.bin"], cwd=repo / "subdir",
                                env=self.env, capture_output=True, timeout=30)
        log = self.root / "calls.jsonl"
        self.assertTrue(log.exists(), "the real CLI must resolve git to the owned executable spy")
        receipts = os.environ.get("GIT_ROOT_TEST_RECEIPTS")
        if receipts:
            out = Path(receipts) / self._testMethodName
            out.mkdir(parents=True, exist_ok=False)
            (out / "stdout.bin").write_bytes(result.stdout)
            (out / "stderr.bin").write_bytes(result.stderr)
            (out / "git.jsonl").write_bytes(log.read_bytes())
            (out / "receipt.json").write_text(json.dumps({"argv": result.args, "cwd": str(repo / "subdir"),
                "environment": self.env, "exit": result.returncode, "timeout_seconds": 30,
                "source_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest()}, indent=2) + "\n")
        return result

    def test_trailing_newline_root_never_rewrites_the_sibling_repository(self):
        sibling, sibling_tip = self.repository("repo")
        current, current_tip = self.repository("repo\n")
        result = self.invoke(current)
        self.assertEqual(self.git(sibling, "rev-parse", "HEAD"), sibling_tip,
                         "root discovery must never redirect a rewrite into a sibling repository")
        self.assertEqual(self.git(current, "rev-parse", "HEAD"), current_tip)
        for repo in (current, sibling):
            self.assertEqual(self.git(repo, "for-each-ref", "--format=%(refname)", "refs/original"), b"")
            self.assertEqual((repo / "target.bin").read_bytes(), b"fixture")
        self.assertNotEqual(result.returncode, 0, "unsupported upstream roots must refuse before mutation")
        self.assertIn(b"newline", result.stderr.lower())

    def check_supported_root(self, name):
        repo, before = self.repository(name)
        result = self.invoke(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.git(repo, "rev-parse", "HEAD"), before)
        self.assertEqual(self.git(repo, "ls-tree", "--name-only", "HEAD"), b"keep.txt\n")
        self.assertEqual(self.git(repo, "rev-parse", "refs/original/refs/heads/main"), before)

    def test_ordinary_repository_root_still_filters_from_a_subdirectory(self):
        self.check_supported_root("ordinary repo")

    def test_internal_newline_in_root_remains_supported(self):
        self.check_supported_root("repo\nwith-suffix")


if __name__ == "__main__":
    unittest.main()
