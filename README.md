# git-lfs-fix

Remove one explicitly named file from local Git history:

```sh
bash /path/to/gitlfsfix 'path/to/large file.bin'
```

**This rewrites history across all local refs.** Work in a disposable clone with a
clean index and worktree, back up the repository first, and review the resulting
history before deciding whether to publish it. This script never pushes.

The argument is one repository-root-relative filename, even when invoked from a
subdirectory. Quote spaces and shell metacharacters. Leading dashes, brackets,
asterisks and question marks are literal filename characters, not options or Git
pathspec patterns. Absolute paths, parent traversal, directory-shaped paths,
missing arguments and extra arguments are refused. No hardcoded filename is
removed when the argument is omitted. The index filter removes only the exact file entry in each historical tree. If that path later becomes a directory, its descendants are left intact; no recursive removal is requested.

`git filter-branch` is intentionally run without `--force`, preserving its refusal
when `refs/original` backups already exist. Inspect and recover those refs
manually rather than automatically overwriting them. This is a history-removal
utility, not a Git LFS migration or a guarantee that a remote size-limit error is
fixed. Git recommends modern filtering tools for large/complex repositories.

Offline regression tests (Bash, Git and Python 3 required):

```sh
python3 -m unittest discover -s tests -v
```

Tests rewrite only temporary synthetic repositories and never contact a remote.
