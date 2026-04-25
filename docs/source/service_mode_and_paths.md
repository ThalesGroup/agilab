# Service Mode And Paths

This note documents how an end-user (service) installation of AGILab wires the
different source trees together.  It complements the public documentation and
captures the expectations that baked-in automation (install scripts, the `AgiEnv`
bootstrapper, etc.) now assume.

## Terminology

- **Public checkout** – the open-source `agilab` repository containing the
  default apps and tooling.
- **Apps repository checkout** – an optional secondary repository referenced by
  the `APPS_REPOSITORY` environment variable. It can host additional app
  templates without requiring changes to the public checkout.
- **Service mode** – an end-user installation (`install_type == 0`) where the
  runtime lives under `~/agi-space` and pulls packages from wheels installed in
  a virtual environment.

## Key Files And Environment Variables

| Path / Variable | Purpose |
| ----------------| --------|
| `~/.local/share/agilab/.env` | Populated by the installer and read by
  `AgiEnv`.  When using an external apps repository it must contain the
  repository location via `APPS_REPOSITORY="/abs/path/to/apps-repository"`. |
| `~/.local/share/agilab/.agilab-path` | Records the canonical public checkout
  used when the installer ran.  When present it allows a fallback to the
  open-source apps. |
| `~/agi-space/.venv` | The virtual environment that executes the web interface in
  service mode. |
| `~/agi-space/apps` | Populated with links to selected built-in and repository app projects. |

## How App Symlinks Are Resolved

1. The installer discovers `apps` and `apps-pages` under `APPS_REPOSITORY`.
   Direct children are preferred; nested `src/agilab/apps` and
   `src/agilab/apps-pages` layouts are also accepted.
2. Every valid `*_project` folder inside the repository apps directory is linked
   into the active end-user workspace (for example `~/agi-space/apps`). Existing
   links are recreated on rerun.
3. If a selected repository app/page already exists locally as a real directory,
   the installer moves it to `<name>.previous.<timestamp>` and links the
   repository copy in its place. This makes app updates from the repository the
   source of truth while keeping the old local directory recoverable.
4. If the apps repository directory is missing or unset, `AgiEnv` falls back to
   the location stored in `~/.local/share/agilab/.agilab-path` and copies the
   public apps instead of linking them.

Because the apps repository (when configured) is the primary source of truth,
make sure the installer writes the up-to-date path to `APPS_REPOSITORY` and that
the repository exposes an installable apps tree:

```
${APPS_REPOSITORY}/
  src/
    agilab/
      apps/
      apps-pages/
      ...
```

## Updating App Links

During startup `AgiEnv.get_projects()` automatically removes dangling symlinks
under the end-user `apps` directory. If you move, rename, or update projects in
the apps repository, rerun the installer so repository links are refreshed and
any stale real directories are moved aside before the new links are created.

## Practical Checklist

1. Point `APPS_REPOSITORY` at the root of the apps repository (when used).
2. Run the installer (or rerun `install_apps.sh`) so `~/.local/share/agilab/.env`
   is refreshed and app/page links are updated.
3. Restart the end-user web interface app.  The sidebar project selector should now
   only list apps that resolve inside `APPS_REPOSITORY`.
