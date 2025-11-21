## AGILAB Roadmap

- Migrate to uv 1.0 once available.
- Rework documentation published on GitHub.
- Explore shared virtualenv reuse for workers and apps-pages via symlink +
  dependency-hash checks: reuse when Python version and lock/deps match; on
  mismatch or failure, create a fresh env and repoint the symlink to reduce
  redundant venvs without sacrificing isolation.
