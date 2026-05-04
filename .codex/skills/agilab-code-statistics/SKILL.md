---
name: agilab-code-statistics
description: Generate fast, reproducible AGILAB code statistics. Use when the user asks for code stats, LOC, file counts, language breakdowns, test/docs/source ratios, churn summaries, or a concise repository size/code footprint report without running builds.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-29
---

# AGILAB Code Statistics

Use this skill to answer code-statistics questions quickly and reproducibly.
Default to tracked files only, so ignored caches, virtualenvs, local datasets,
generated docs output, and untracked scratch files do not distort the numbers.

## Defaults

- Start with `git status --short --branch` and say whether the tree is dirty.
- Use `git ls-files` for file lists unless the user explicitly asks for
  untracked/local files too.
- Report the counting boundary: tracked files, selected extensions, and any
  excluded generated/vendor paths.
- Prefer fast local commands. Do not run tests, installers, docs builds, or
  package builds for statistics.
- If a tool is missing (`tokei`, `cloc`), fall back to the Python snippet below
  instead of installing dependencies.

## Quick Commands

Tracked file count and extension breakdown:

```bash
git ls-files | awk '
  {
    n=$0
    sub(/^.*\//, "", n)
    ext=n
    if (ext !~ /\./) ext="[no extension]"
    else { sub(/^.*\./, ".", ext) }
    count[ext] += 1
  }
  END { for (ext in count) print count[ext], ext }
' | sort -nr
```

Tracked LOC by common AGILAB source/doc/config extensions:

```bash
git ls-files \
  | rg '\.(py|toml|md|rst|yml|yaml|sh|json|css|html|svg)$' \
  | xargs wc -l
```

If available, use one of these for language-aware stats:

```bash
git ls-files -z | xargs -0 tokei
cloc --vcs=git
```

Use `tools/repo_footprint.py audit` for storage footprint, not LOC:

```bash
uv --preview-features extra-build-dependencies run python tools/repo_footprint.py audit
```

## Portable Python Fallback

Use this when shell tooling is missing or when you need grouped AGILAB counts:

```bash
python3 - <<'PY'
from collections import Counter, defaultdict
from pathlib import Path
import subprocess

paths = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
skip_prefixes = ("docs/html/",)
code_exts = {".py", ".pyi", ".sh"}
doc_exts = {".md", ".rst"}
config_exts = {".toml", ".yaml", ".yml", ".json"}

files = [Path(p) for p in paths if not p.startswith(skip_prefixes)]
by_ext = Counter(p.suffix or "[no extension]" for p in files)
groups = defaultdict(lambda: {"files": 0, "lines": 0})

for path in files:
    ext = path.suffix
    if ext in code_exts:
        group = "code"
    elif ext in doc_exts:
        group = "docs"
    elif ext in config_exts:
        group = "config"
    elif "/test/" in f"/{path.as_posix()}" or path.name.startswith("test_"):
        group = "tests"
    else:
        group = "other"
    groups[group]["files"] += 1
    try:
        groups[group]["lines"] += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        pass

print("Tracked files:", len(files))
print("\nBy group:")
for name, data in sorted(groups.items()):
    print(f"{name:>8}: {data['files']:5d} files {data['lines']:8d} lines")
print("\nTop extensions:")
for ext, count in by_ext.most_common(20):
    print(f"{ext:>12}: {count}")
PY
```

## Churn And Diff Stats

For current changes:

```bash
git diff --stat
git diff --shortstat
git diff --cached --stat
git diff --cached --shortstat
```

For recent history:

```bash
git log --since='30 days ago' --numstat --pretty='%H' -- . \
  | awk 'NF==3 { add+=$1; del+=$2; files[$3]=1 } END { print "added", add, "deleted", del, "files", length(files) }'
```

## Reporting Format

Keep the answer compact:

- `Scope`: tracked files only, plus exclusions.
- `Headline`: total files and total counted lines.
- `Breakdown`: code/docs/config/tests/other or language table.
- `Caveats`: generated files, binary assets, LFS data, dirty tree, or missing tools.
- `Next`: one suggested follow-up only, for example “run cloc/tokei if installed”
  or “separate generated docs from source docs”.
