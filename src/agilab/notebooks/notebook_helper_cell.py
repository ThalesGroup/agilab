# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.

"""Source template for the AGILAB notebook helper cell.

`_helper_cell` is a single ~1250-line f-string holding the Python that exported
notebooks run to locate their app, rebuild stage context, and render analysis
pages. It carried a third of notebook_export_support.py while sharing nothing
with it -- the only value interpolated from the caller is `payload_literal`, and
every other brace in the template is `{{`-escaped and belongs to the generated
code.

Keeping it here leaves the export logic readable and lets this file be reviewed
as what it is: emitted source, not control flow.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any


def _helper_cell(payload: dict[str, Any]) -> str:
    payload_literal = repr(json.dumps(payload, ensure_ascii=False))
    return textwrap.dedent(
        f"""
        import json
        import ast
        import importlib
        import importlib.util
        import os
        import shlex
        import shutil
        import socket
        import subprocess
        import sys
        import tempfile
        import time
        import tomllib
        import traceback
        from pathlib import Path

        AGILAB_NOTEBOOK_EXPORT = json.loads({payload_literal})


        def _normalized_path(value):
            if not value:
                return ""
            try:
                return str(Path(value).expanduser())
            except Exception:
                return str(value)


        def _is_valid_active_app_root(path_value):
            if not path_value:
                return False
            try:
                root = Path(path_value).expanduser()
            except Exception:
                return False
            try:
                return root.is_dir() and (
                    (root / "pyproject.toml").is_file() or
                    (root / "src" / "app_settings.toml").is_file()
                )
            except OSError:
                return False


        def _active_app_matches_project(path_value, project_name):
            if not project_name:
                return True
            if not path_value:
                return False
            try:
                return Path(path_value).expanduser().name in _project_name_candidates(project_name)
            except Exception:
                return False


        def _project_name_candidates(project_name):
            text = str(project_name or "").strip()
            if not text:
                return []
            candidates = []

            def add(candidate):
                candidate = str(candidate or "").strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

            add(text)
            if text.endswith("_project"):
                add(text.removesuffix("_project"))
            else:
                add(f"{{text}}_project")
            aliases = {{
                "weather_forecast_legacy": ("weather_forecast", "weather_forecast_project"),
                "weather_forecast": ("weather_forecast_legacy", "weather_forecast_legacy_project"),
            }}
            for candidate in list(candidates):
                base = candidate.removesuffix("_project") if candidate.endswith("_project") else candidate
                for alias in aliases.get(base, ()):
                    add(alias)
            return candidates


        def _truthy_env(name):
            return str(os.environ.get(name) or "").strip().lower() in {{"1", "true", "yes", "y", "on"}}


        def _allow_workspace_sibling_apps():
            return bool(AGILAB_NOTEBOOK_EXPORT.get("allow_workspace_sibling_apps")) or _truthy_env(
                "AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS"
            )


        def _looks_like_source_checkout(path_value):
            try:
                root = Path(path_value).expanduser()
            except Exception:
                return False
            try:
                return (root / "src" / "agilab").exists() and ((root / ".git").exists() or (root / ".idea").exists())
            except OSError:
                return False


        def _candidate_checkout_roots():
            seen = set()

            def emit(seed):
                if not seed:
                    return
                try:
                    path = Path(_normalized_path(seed)).expanduser()
                except Exception:
                    return
                for candidate in (path, *path.parents):
                    candidate_text = _normalized_path(candidate)
                    if not candidate_text or candidate_text in seen:
                        continue
                    if _looks_like_source_checkout(candidate):
                        seen.add(candidate_text)
                        yield candidate

            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("repo_root"))
            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("pycharm_mirror_path"))
            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("pages_root"))


        def _candidate_apps_directories():
            seen = set()

            def emit(candidate):
                if not candidate:
                    return
                candidate_text = _normalized_path(candidate)
                if not candidate_text or candidate_text in seen:
                    return
                try:
                    path = Path(candidate_text)
                except Exception:
                    return
                if not path.exists():
                    return
                seen.add(candidate_text)
                yield path

            for repo_root in _candidate_checkout_roots():
                yield from emit(repo_root / "src" / "agilab" / "apps")
                yield from emit(repo_root / "apps")

                if _allow_workspace_sibling_apps():
                    workspace_root = repo_root.parent
                    try:
                        siblings = sorted(
                            candidate
                            for candidate in workspace_root.iterdir()
                            if candidate.is_dir() and candidate != repo_root
                        )
                    except OSError:
                        siblings = []
                    for sibling in siblings:
                        yield from emit(sibling / "apps")
                        yield from emit(sibling / "src" / "agilab" / "apps")

            for env_key in ("APPS_REPOSITORY",):
                apps_repository = str(os.environ.get(env_key) or "").strip()
                if apps_repository:
                    repo_path = Path(apps_repository).expanduser()
                    yield from emit(repo_path)
                    yield from emit(repo_path / "apps")
                    yield from emit(repo_path / "src" / "agilab" / "apps")


        def resolve_active_app_root(app_name=None):
            active_app = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("active_app"))
            project_name = str(app_name or AGILAB_NOTEBOOK_EXPORT.get("project_name") or "").strip()
            if _is_valid_active_app_root(active_app) and _active_app_matches_project(active_app, project_name):
                AGILAB_NOTEBOOK_EXPORT["active_app"] = active_app
                return active_app

            if project_name:
                for apps_dir in _candidate_apps_directories():
                    for project_candidate in _project_name_candidates(project_name):
                        for candidate in (apps_dir / project_candidate, apps_dir / "builtin" / project_candidate):
                            candidate_text = _normalized_path(candidate)
                            if _is_valid_active_app_root(candidate_text):
                                AGILAB_NOTEBOOK_EXPORT["active_app"] = candidate_text
                                return candidate_text

            raise ValueError(
                "Unable to resolve a valid AGILAB app root for exported notebook "
                f"project={{project_name or app_name or '<unknown>'}}. "
                f"Current active_app={{active_app or '<missing>'}}. "
                "Re-export the notebook from AGILAB with the correct project selected, "
                "or set APPS_REPOSITORY so the project root can be discovered."
            )


        def _read_mutable_toml(candidate):
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    with candidate.open("rb") as stream:
                        return tomllib.load(stream)
                except PermissionError:
                    if os.name != "nt":
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    time.sleep(min(0.01, remaining))


        def _load_app_settings_args(active_app):
            settings_candidates = []

            configured = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("app_settings_file"))
            if configured:
                settings_candidates.append(Path(configured))

            try:
                active_root = Path(active_app).expanduser()
            except Exception:
                active_root = None
            if active_root is not None:
                settings_candidates.append(active_root / "src" / "app_settings.toml")
                settings_candidates.append(active_root / "app_settings.toml")

            for candidate in settings_candidates:
                try:
                    if not candidate.exists():
                        continue
                    payload = _read_mutable_toml(candidate)
                except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
                    continue
                args_payload = payload.get("args")
                if isinstance(args_payload, dict):
                    return json.loads(json.dumps(args_payload, ensure_ascii=False))
            return {{}}


        def _merge_shorthand_run_args(assignments, active_app):
            flat_assignments = dict(assignments)
            run_args = _load_app_settings_args(active_app)
            trainer_name = str(flat_assignments.pop("trainer", "") or "").strip()

            if not run_args:
                return dict(assignments)

            if "args" in run_args:
                raise ValueError("Legacy run settings key 'args' is no longer supported; use 'stages'.")
            nested_trainers = run_args.get("stages")
            if trainer_name and isinstance(nested_trainers, list):
                selected = None
                for item in nested_trainers:
                    if isinstance(item, dict) and str(item.get("name", "") or "").strip() == trainer_name:
                        selected = json.loads(json.dumps(item, ensure_ascii=False))
                        break
                if selected is None:
                    selected = {{"name": trainer_name, "args": {{}}}}
                selected_args = selected.get("args")
                if not isinstance(selected_args, dict):
                    selected_args = {{}}

                for key, value in flat_assignments.items():
                    if key in run_args and key != "stages":
                        run_args[key] = value
                    else:
                        selected_args[key] = value

                selected["args"] = selected_args
                run_args["stages"] = [selected]
                return run_args

            for key, value in flat_assignments.items():
                run_args[key] = value
            return run_args


        def show_agilab_export_summary():
            related = [page.get("module", "") for page in AGILAB_NOTEBOOK_EXPORT.get("related_pages", [])]
            summary = {{
                "project_name": AGILAB_NOTEBOOK_EXPORT.get("project_name"),
                "module_path": AGILAB_NOTEBOOK_EXPORT.get("module_path"),
                "artifact_dir": AGILAB_NOTEBOOK_EXPORT.get("artifact_dir"),
                "active_app": AGILAB_NOTEBOOK_EXPORT.get("active_app"),
                "export_mode": AGILAB_NOTEBOOK_EXPORT.get("export_mode"),
                "stages": len(AGILAB_NOTEBOOK_EXPORT.get("stages", [])),
                "related_pages": related,
            }}
            print(json.dumps(summary, indent=2))
            return summary


        def export_handoff_markdown():
            stages = AGILAB_NOTEBOOK_EXPORT.get("stages", [])
            related_pages = AGILAB_NOTEBOOK_EXPORT.get("related_pages", [])
            worker_stage_count = 0
            env_path_count = 0
            if isinstance(stages, list):
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    runtime = str(stage.get("runtime") or "")
                    role = "worker" if runtime in {{"agi.run", "agi"}} else "manager"
                    if role == "worker":
                        worker_stage_count += 1
                    if str(stage.get("env") or "").strip():
                        env_path_count += 1
            project_bound = bool(
                worker_stage_count
                or env_path_count
                or str(AGILAB_NOTEBOOK_EXPORT.get("active_app") or "").strip()
            )
            portability_status = "project-bound" if project_bound else "notebook-local"
            portability_note = (
                "The notebook is runnable, but AGILAB app/runtime paths remain part of the contract."
                if project_bound
                else "No AGILAB worker/runtime path was recorded, but validation is still required."
            )
            lines = [
                "# AGILAB notebook handoff: " + str(AGILAB_NOTEBOOK_EXPORT.get("project_name") or "AGILAB project"),
                "",
                "This notebook is a durable exit path from AGILAB. Keep the editable STAGE_###_CODE cells, run validation before execution, and use the runner cells only when you want to replay the workflow.",
                "",
                "## Run Order",
                "",
                "1. Run validate_agilab_export().",
                "2. Run one runner cell or run_agilab_pipeline().",
                "3. Render related analysis pages if configured.",
                "4. If you edit stage code, re-import the notebook into AGILAB when you want lab_stages.toml to become the source of truth again.",
                "",
                "## Paths",
                "",
                "- Artifact directory: `" + str(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir") or "(not set)") + "`",
                "- Active app root: `" + str(AGILAB_NOTEBOOK_EXPORT.get("active_app") or "(not set)") + "`",
                "- Stages file: `" + str(AGILAB_NOTEBOOK_EXPORT.get("stages_file") or "(not set)") + "`",
                "",
                "## Portability Review",
                "",
                "- Status: **" + portability_status + "**",
                "- Critic note: " + portability_note,
                "- Worker/runtime stages: " + str(worker_stage_count),
                "- Recorded stage environments: " + str(env_path_count),
                "- Recommended check: run validate_agilab_export() after moving or editing the notebook.",
                "",
                "## Stages",
                "",
                "| Stage | Role | Runtime | Description |",
                "|---:|---|---|---|",
            ]
            if isinstance(stages, list) and stages:
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    runtime = str(stage.get("runtime") or "runpy")
                    role = "worker" if runtime in {{"agi.run", "agi"}} else "manager"
                    description = str(stage.get("description") or "(no description)").replace("|", "\\\\|")
                    lines.append(
                        "| "
                        + str(stage.get("index", ""))
                        + " | "
                        + role
                        + " | "
                        + runtime
                        + " | "
                        + description
                        + " |"
                    )
            else:
                lines.append("| - | - | - | No executable stages exported. |")

            if isinstance(related_pages, list) and related_pages:
                lines.extend(["", "## Related Analysis Pages", ""])
                for page in related_pages:
                    if not isinstance(page, dict):
                        continue
                    label = str(page.get("label") or page.get("module") or "analysis page")
                    module = str(page.get("module") or "")
                    lines.append("- " + label + " (`" + module + "`)")
            return "\\n".join(lines)


        def show_agilab_export_handoff():
            markdown = export_handoff_markdown()
            try:
                from IPython.display import Markdown, display
            except Exception:
                print(markdown)
                return markdown
            display(Markdown(markdown))
            return markdown


        def _path_exists(path_value):
            if not path_value:
                return False
            try:
                return Path(path_value).expanduser().exists()
            except Exception:
                return False


        def _file_sha256(path_value):
            if not path_value:
                return ""
            try:
                path = Path(path_value).expanduser()
                if not path.is_file():
                    return ""
                import hashlib

                return hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                return ""


        def _view_sync_source_drift():
            view_sync = AGILAB_NOTEBOOK_EXPORT.get("view_sync", {{}})
            if not isinstance(view_sync, dict):
                return 0, [], [], 0
            raw_sources = view_sync.get("sources", [])
            if not isinstance(raw_sources, list):
                return 0, [], [], 0

            checked = 0
            changed = []
            unavailable = []
            for source in raw_sources:
                if not isinstance(source, dict):
                    continue
                path = str(source.get("path") or "").strip()
                expected = str(source.get("sha256") or "").strip()
                if not path or not expected:
                    continue
                actual = _file_sha256(path)
                record = {{
                    "kind": str(source.get("kind") or ""),
                    "module": str(source.get("module") or ""),
                    "path": path,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                }}
                if not actual:
                    unavailable.append(record)
                    continue
                checked += 1
                if actual != expected:
                    changed.append(record)
            return checked, changed, unavailable, len(raw_sources)


        def _command_or_path_exists(value):
            text = str(value or "").strip()
            if not text:
                return False
            try:
                if Path(text).expanduser().exists():
                    return True
            except Exception:
                pass
            return shutil.which(text) is not None


        def _validation_check(checks, check_id, ok, summary, *, severity="error", **details):
            status = "pass" if ok else "fail"
            checks.append(
                {{
                    "id": check_id,
                    "status": status,
                    "severity": severity,
                    "summary": summary,
                    "details": details,
                }}
            )
            return ok or severity != "error"


        def _inline_renderer_target_exists(target):
            target_text = str(target or "").strip()
            if not target_text:
                return False
            module_target, _, _ = target_text.partition(":")
            module_target = module_target.strip()
            if not module_target:
                return False
            try:
                path_target = Path(module_target).expanduser()
            except Exception:
                return True
            if path_target.suffix == ".py" or "/" in module_target or "\\\\" in module_target:
                return path_target.exists()
            return True


        def _resolve_pages_root():
            configured = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("pages_root"))
            if configured and _path_exists(configured):
                return configured

            try:
                from agi_env import AgiEnv

                env = AgiEnv()
                pages_root = _normalized_path(getattr(env, "AGILAB_PAGES_ABS", ""))
                if pages_root and _path_exists(pages_root):
                    AGILAB_NOTEBOOK_EXPORT["pages_root"] = pages_root
                    return pages_root
            except Exception:
                pass

            try:
                import agi_pages

                pages_root = _normalized_path(agi_pages.bundles_root())
                if pages_root and _path_exists(pages_root):
                    AGILAB_NOTEBOOK_EXPORT["pages_root"] = pages_root
                    return pages_root
            except Exception:
                pass

            return configured


        def _bundle_to_record(bundle):
            if bundle is None:
                return {{}}
            if hasattr(bundle, "as_dict"):
                try:
                    raw_record = bundle.as_dict()
                except Exception:
                    raw_record = {{}}
            elif isinstance(bundle, dict):
                raw_record = bundle
            else:
                raw_record = {{
                    "name": getattr(bundle, "name", ""),
                    "module": getattr(bundle, "module", "") or getattr(bundle, "name", ""),
                    "root_path": getattr(bundle, "root_path", ""),
                    "script_path": getattr(bundle, "script_path", ""),
                    "inline_renderer": getattr(bundle, "inline_renderer", ""),
                }}

            record = {{
                "name": str(raw_record.get("name", "") or raw_record.get("module", "") or ""),
                "module": str(raw_record.get("module", "") or raw_record.get("name", "") or ""),
                "root_path": _normalized_path(raw_record.get("root_path", "")),
                "script_path": _normalized_path(raw_record.get("script_path", "")),
                "inline_renderer": str(raw_record.get("inline_renderer", "") or ""),
            }}
            return record if record.get("script_path") else {{}}


        def _resolve_agi_pages_bundle(page, pages_root=None):
            try:
                import agi_pages
            except Exception:
                return {{}}

            resolver = getattr(agi_pages, "resolve_bundle", None)
            if callable(resolver):
                try:
                    bundle = resolver(page, pages_root=pages_root or None)
                except TypeError:
                    try:
                        bundle = resolver(page)
                    except Exception:
                        bundle = None
                except Exception:
                    bundle = None
                record = _bundle_to_record(bundle)
                if record:
                    return record

            script_resolver = getattr(agi_pages, "script_path", None)
            if not callable(script_resolver):
                return {{}}
            try:
                script = script_resolver(page, pages_root=pages_root or None)
            except TypeError:
                try:
                    script = script_resolver(page)
                except Exception:
                    script = ""
            except Exception:
                script = ""
            if not script:
                return {{}}
            inline_renderer = ""
            inline_resolver = getattr(agi_pages, "inline_renderer_target", None)
            if callable(inline_resolver):
                try:
                    inline_renderer = str(inline_resolver(page, pages_root=pages_root or None) or "")
                except TypeError:
                    try:
                        inline_renderer = str(inline_resolver(page) or "")
                    except Exception:
                        inline_renderer = ""
                except Exception:
                    inline_renderer = ""
            return {{
                "name": str(page),
                "module": str(page),
                "root_path": "",
                "script_path": _normalized_path(script),
                "inline_renderer": inline_renderer,
            }}


        def _inline_renderer_target_for_script(script):
            if not script:
                return ""
            try:
                candidate = Path(script).expanduser().resolve().with_name("notebook_inline.py")
            except Exception:
                return ""
            if not candidate.exists():
                return ""
            return f"{{candidate}}:render_inline"


        def _resolve_page_bundle_from_root(page, pages_root):
            root_text = _normalized_path(pages_root)
            page_name = str(page or "").strip()
            if not root_text or not page_name:
                return {{}}
            try:
                root = Path(root_text).expanduser()
            except Exception:
                return {{}}
            direct_file = root / f"{{page_name}}.py"
            if direct_file.exists() and direct_file.is_file():
                script = direct_file.resolve()
                return {{
                    "name": page_name,
                    "module": page_name,
                    "root_path": str(root.resolve()),
                    "script_path": str(script),
                    "inline_renderer": _inline_renderer_target_for_script(script),
                }}
            bundle_dir = root / page_name
            if not bundle_dir.exists() or not bundle_dir.is_dir():
                return {{}}
            candidates = []
            for pattern_root in (bundle_dir, bundle_dir / "src" / page_name):
                candidates.extend(
                    [
                        pattern_root / f"{{page_name}}.py",
                        pattern_root / "main.py",
                        pattern_root / "app.py",
                    ]
                )
            script = None
            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    script = candidate.resolve()
                    break
            if script is None:
                fallback = sorted((bundle_dir / "src").glob("*/view_*.py"))
                if fallback:
                    script = fallback[0].resolve()
            if script is None:
                return {{}}
            return {{
                "name": page_name,
                "module": page_name,
                "root_path": str(bundle_dir.resolve()),
                "script_path": str(script),
                "inline_renderer": _inline_renderer_target_for_script(script),
            }}


        def _resolve_page_bundle_record(page):
            pages_root = _resolve_pages_root()
            record = _resolve_agi_pages_bundle(page, pages_root=pages_root)
            if record:
                return record
            if pages_root:
                record = _resolve_page_bundle_from_root(page, pages_root)
                if record:
                    return record
            return _resolve_agi_pages_bundle(page)


        def _enrich_page_record(record):
            resolved = dict(record)
            page = str(resolved.get("module") or resolved.get("name") or "").strip()
            if not page:
                return resolved
            script_path = _normalized_path(resolved.get("script_path"))
            inline_renderer = str(resolved.get("inline_renderer") or "").strip()
            script_missing = not script_path or not _path_exists(script_path)
            inline_missing = bool(inline_renderer) and not _inline_renderer_target_exists(inline_renderer)
            if script_missing or not inline_renderer or inline_missing:
                provider_record = _resolve_page_bundle_record(page)
                if provider_record:
                    if script_missing and provider_record.get("script_path"):
                        resolved["script_path"] = provider_record["script_path"]
                    if (not inline_renderer or inline_missing) and provider_record.get("inline_renderer"):
                        resolved["inline_renderer"] = provider_record["inline_renderer"]
            return resolved


        def _page_record(page):
            for record in AGILAB_NOTEBOOK_EXPORT.get("related_pages", []):
                if record.get("module") == page:
                    return _enrich_page_record(record)
            raise KeyError(f"Unknown analysis page: {{page}}")


        def _display_inline_result(result):
            if result is None:
                return None
            try:
                from IPython.display import Markdown, display
            except Exception:
                return result
            if isinstance(result, str):
                display(Markdown(result))
                return result
            if isinstance(result, (list, tuple)):
                for item in result:
                    _display_inline_result(item)
                return result
            display(result)
            return result


        def _load_inline_renderer(target):
            target_text = str(target or "").strip()
            if not target_text:
                raise ValueError("Inline renderer target is empty.")
            module_target, _, attr_name = target_text.partition(":")
            module_target = module_target.strip()
            attr_name = attr_name or "render_inline"
            path_target = Path(module_target).expanduser()
            if path_target.suffix == ".py" or path_target.exists():
                module_path = path_target.resolve()
                synthetic_name = f"agilab_notebook_inline_{{module_path.stem}}_{{abs(hash(str(module_path)))}}"
                spec = importlib.util.spec_from_file_location(synthetic_name, module_path)
                if spec is None or spec.loader is None:
                    raise ModuleNotFoundError(f"Unable to load inline renderer module from {{module_path}}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            else:
                module = importlib.import_module(module_target)
            renderer = getattr(module, attr_name)
            if not callable(renderer):
                raise TypeError(f"Inline renderer {{target_text!r}} is not callable.")
            return renderer


        def _resolve_stage_python(stage):
            controller_python = AGILAB_NOTEBOOK_EXPORT.get("controller_python") or sys.executable
            try:
                from agilab.pipeline.pipeline_runtime import python_for_stage
            except Exception:
                return controller_python
            try:
                resolved = python_for_stage(
                    stage.get("env") or None,
                    engine=stage.get("runtime") or None,
                    code=stage.get("code") or "",
                    sys_executable=controller_python,
                )
            except TypeError:
                resolved = python_for_stage(
                    stage.get("env") or None,
                    engine=stage.get("runtime") or None,
                    code=stage.get("code") or "",
                )
            return str(resolved)


        def _stage_assignments(code_text):
            try:
                tree = ast.parse(code_text or "")
            except SyntaxError:
                return {{}}
            assignments = {{}}
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    return {{}}
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    return {{}}
                assignments[node.targets[0].id] = value
            return assignments


        def _stage_shorthand_method(stage, code_text):
            runtime = str(stage.get("runtime") or "").strip().lower()
            if runtime.startswith("agi."):
                return runtime.split(".", 1)[1]
            lowered = str(code_text or "").lower()
            if "agi.install(" in lowered:
                return "install"
            if "agi.run(" in lowered:
                return "run"
            if "APP" in _stage_assignments(code_text):
                return "run"
            return ""


        def _stage_app_name(stage):
            assignments = _stage_assignments(stage.get("code") or "")
            return str(assignments.get("APP") or "").strip()


        def validate_agilab_export(*, verbose=True):
            stages = AGILAB_NOTEBOOK_EXPORT.get("stages", [])
            related_pages = AGILAB_NOTEBOOK_EXPORT.get("related_pages", [])
            checks = []
            ok = True

            ok = _validation_check(
                checks,
                "schema",
                AGILAB_NOTEBOOK_EXPORT.get("schema") == "agilab.notebook_export.v1",
                "AGILAB notebook export schema is supported.",
                schema=AGILAB_NOTEBOOK_EXPORT.get("schema"),
            ) and ok
            stage_count = len(stages) if isinstance(stages, list) else 0
            ok = _validation_check(
                checks,
                "stages",
                stage_count > 0,
                f"Notebook declares {{stage_count}} workflow stage(s).",
                stage_count=stage_count,
            ) and ok

            artifact_dir = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir"))
            artifact_parent = ""
            artifact_ok = False
            if artifact_dir:
                try:
                    artifact_path = Path(artifact_dir).expanduser()
                    artifact_parent = str(artifact_path.parent)
                    artifact_ok = artifact_path.exists() or artifact_path.parent.exists()
                except Exception:
                    artifact_ok = False
            ok = _validation_check(
                checks,
                "artifact_dir",
                bool(artifact_dir) and artifact_ok,
                "Artifact directory or its parent is reachable.",
                artifact_dir=artifact_dir,
                artifact_parent=artifact_parent,
            ) and ok

            for stage_index, stage in enumerate(stages if isinstance(stages, list) else []):
                if not isinstance(stage, dict):
                    ok = _validation_check(
                        checks,
                        f"stage_{{stage_index}}_record",
                        False,
                        "Stage record is not a dictionary.",
                        stage_index=stage_index,
                    ) and ok
                    continue

                python_exe = _resolve_stage_python(stage)
                python_ok = _command_or_path_exists(python_exe)
                ok = _validation_check(
                    checks,
                    f"stage_{{stage_index}}_python",
                    python_ok,
                    f"Stage {{stage_index}} Python interpreter is reachable.",
                    stage_index=stage_index,
                    python=python_exe,
                    runtime=stage.get("runtime") or "",
                    env=stage.get("env") or "",
                ) and ok

                app_name = _stage_app_name(stage)
                if app_name:
                    try:
                        active_app = resolve_active_app_root(app_name)
                        app_ok = True
                        app_error = ""
                    except Exception as exc:
                        active_app = ""
                        app_ok = False
                        app_error = str(exc)
                    ok = _validation_check(
                        checks,
                        f"stage_{{stage_index}}_active_app",
                        app_ok,
                        f"Stage {{stage_index}} app root is resolvable.",
                        stage_index=stage_index,
                        app_name=app_name,
                        active_app=active_app,
                        error=app_error,
                    ) and ok

            for page in related_pages if isinstance(related_pages, list) else []:
                if not isinstance(page, dict):
                    continue
                page_name = str(page.get("module") or "").strip()
                if not page_name:
                    continue
                record = _enrich_page_record(page)
                script_path = _normalized_path(record.get("script_path"))
                inline_renderer = str(record.get("inline_renderer") or "").strip()
                page_ok = bool(script_path) and _path_exists(script_path)
                inline_ok = not inline_renderer or _inline_renderer_target_exists(inline_renderer)
                ok = _validation_check(
                    checks,
                    f"analysis_page_{{page_name}}",
                    page_ok and inline_ok,
                    f"Analysis page {{page_name}} can be resolved.",
                    page=page_name,
                    script_path=script_path,
                    inline_renderer=inline_renderer,
                    inline_renderer_exists=inline_ok,
                ) and ok

            checked_sources, changed_sources, unavailable_sources, total_sources = _view_sync_source_drift()
            if total_sources:
                ok = _validation_check(
                    checks,
                    "view_sync_sources",
                    not changed_sources,
                    "Reachable app settings, page manifests, and analysis page sources match the notebook export snapshot.",
                    source_count=total_sources,
                    checked_count=checked_sources,
                    changed_sources=changed_sources,
                    unavailable_sources=unavailable_sources,
                ) and ok

            report = {{
                "ok": ok,
                "project_name": AGILAB_NOTEBOOK_EXPORT.get("project_name"),
                "export_mode": AGILAB_NOTEBOOK_EXPORT.get("export_mode"),
                "stage_count": stage_count,
                "related_page_count": len(related_pages) if isinstance(related_pages, list) else 0,
                "checks": checks,
            }}
            if verbose:
                print(json.dumps(report, indent=2))
            return report


        def _build_shorthand_agi_script(stage, code_text):
            assignments = _stage_assignments(code_text)
            app_name = str(assignments.pop("APP", "") or "").strip()
            if not app_name:
                return None
            method = _stage_shorthand_method(stage, code_text)
            if method not in {{"run", "install"}}:
                return None
            active_app = resolve_active_app_root(app_name)
            explicit_mode = assignments.pop("mode", None) if method == "run" else None
            run_args = _merge_shorthand_run_args(assignments, active_app)
            run_mode = 0
            if method == "run":
                if explicit_mode not in (None, ""):
                    run_mode = explicit_mode
                else:
                    inherited_mode = run_args.pop("mode", None)
                    if inherited_mode not in (None, ""):
                        run_mode = inherited_mode
            run_params = dict(run_args)
            run_stages_payload = run_params.pop("stages", []) or []
            if "args" in run_params:
                raise ValueError("Legacy run settings key 'args' is no longer supported; use 'stages'.")
            run_data_in = run_params.pop("data_in", None)
            run_data_out = run_params.pop("data_out", None)
            run_reset_target = run_params.pop("reset_target", None)
            run_args_literal = json.dumps(
                run_args,
                ensure_ascii=False,
                sort_keys=True,
            )
            run_params_literal = json.dumps(
                run_params,
                ensure_ascii=False,
                sort_keys=True,
            )
            run_stages_literal = json.dumps(
                run_stages_payload,
                ensure_ascii=False,
                sort_keys=True,
            )
            prelude = (
                "import asyncio\\n"
                "import json\\n"
                "from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest\\n"
                "from agi_env import AgiEnv\\n\\n"
                f"ACTIVE_APP = {{active_app!r}}\\n"
                f"RUN_ARGS = json.loads({{run_args_literal!r}})\\n"
                f"RUN_PARAMS = json.loads({{run_params_literal!r}})\\n"
                f"RUN_STAGES_PAYLOAD = json.loads({{run_stages_literal!r}})\\n"
                f"RUN_DATA_IN = json.loads({{json.dumps(run_data_in, ensure_ascii=False)!r}})\\n"
                f"RUN_DATA_OUT = json.loads({{json.dumps(run_data_out, ensure_ascii=False)!r}})\\n"
                f"RUN_RESET_TARGET = json.loads({{json.dumps(run_reset_target, ensure_ascii=False)!r}})\\n"
            )
            if method == "run":
                mode_literal = json.dumps(run_mode, ensure_ascii=False)
                prelude += f"RUN_MODE = json.loads({{mode_literal!r}})\\n"
            prelude += "\\n"
            if method == "run":
                invoke = (
                    "    run_stages = [\\n"
                    "        StageRequest(name=stage['name'], args=stage.get('args') or {{}})\\n"
                    "        for stage in RUN_STAGES_PAYLOAD\\n"
                    "    ]\\n"
                    "    request = RunRequest(\\n"
                    "        params=RUN_PARAMS,\\n"
                    "        stages=run_stages,\\n"
                    "        data_in=RUN_DATA_IN,\\n"
                    "        data_out=RUN_DATA_OUT,\\n"
                    "        reset_target=RUN_RESET_TARGET,\\n"
                    "        mode=RUN_MODE,\\n"
                    "    )\\n"
                    "    res = await AGI.run(app_env, request=request)\\n"
                )
            else:
                invoke = "    res = await AGI.install(app_env, **RUN_ARGS)\\n"
            return (
                prelude
                + "async def main():\\n"
                + "    app_env = AgiEnv(active_app=ACTIVE_APP, verbose=1)\\n"
                + invoke
                + "    print(res)\\n"
                + "    return res\\n\\n"
                + 'if __name__ == "__main__":\\n'
                + "    asyncio.run(main())\\n"
            )


        def _stage_script_text(stage, code_text):
            shorthand = _build_shorthand_agi_script(stage, code_text)
            if shorthand:
                return shorthand
            return code_text or ""


        def _stage_automation(stage):
            raw = stage.get("automation")
            automation = dict(raw) if isinstance(raw, dict) else {{}}
            for key in (
                "enabled",
                "skip",
                "skip_if_outputs_exist",
                "skip_if_outputs_current",
                "outputs",
                "output_paths",
                "inputs",
                "input_paths",
            ):
                if key in stage and key not in automation:
                    automation[key] = stage[key]
            return automation


        def _deep_merge_stage_mapping(base, override):
            merged = dict(base)
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = _deep_merge_stage_mapping(merged[key], value)
                else:
                    merged[key] = value
            return merged


        def _stage_with_selected_profile(stage):
            module_automation = AGILAB_NOTEBOOK_EXPORT.get("module_automation", {{}})
            profile = str(module_automation.get("profile", "balanced") or "balanced").strip().lower()
            if profile not in {{"balanced", "smoke", "fast", "evidence", "custom"}}:
                profile = "balanced"
            for key in ("profiles", "pipeline_profiles", "automation_profiles"):
                profile_map = stage.get(key)
                if not isinstance(profile_map, dict):
                    continue
                override = profile_map.get(profile)
                if isinstance(override, dict):
                    effective = _deep_merge_stage_mapping(stage, override)
                    if "C" in effective:
                        effective["code"] = effective["C"]
                    if "R" in effective:
                        effective["runtime"] = effective["R"]
                    if "E" in effective:
                        effective["env"] = effective["E"]
                    return effective
            return dict(stage)


        def _truthy_stage_flag(value):
            if isinstance(value, bool):
                return value
            return str(value or "").strip().lower() in {{"1", "true", "yes", "on"}}


        def _iter_stage_path_values(value):
            if isinstance(value, str):
                return [value] if value.strip() else []
            if isinstance(value, dict):
                paths = []
                for key in sorted(value, key=str):
                    paths.extend(_iter_stage_path_values(value[key]))
                return paths
            if isinstance(value, (list, tuple)):
                paths = []
                for item in value:
                    paths.extend(_iter_stage_path_values(item))
                return paths
            return []


        def _stage_output_paths(stage, workdir):
            automation = _stage_automation(stage)
            raw_values = []
            for key in ("outputs", "output_paths"):
                raw_values.extend(_iter_stage_path_values(automation.get(key)))
            paths = []
            for raw_value in raw_values:
                path = Path(raw_value).expanduser()
                paths.append(path if path.is_absolute() else workdir / path)
            return paths


        def _stage_skip_reason(stage, workdir):
            automation = _stage_automation(stage)
            if stage.get("enabled") is False or automation.get("enabled") is False:
                return "disabled by the AGILAB stage contract"
            if stage.get("skip") is True or automation.get("skip") is True:
                return "skipped by the AGILAB stage contract"
            skip_outputs = automation.get(
                "skip_if_outputs_exist",
                automation.get("skip_if_outputs_current"),
            )
            outputs = _stage_output_paths(stage, workdir)
            if _truthy_stage_flag(skip_outputs) and outputs and all(path.exists() for path in outputs):
                return "all declared output artifacts already exist"
            return ""


        def run_agilab_stage(stage_index, *, check=True, capture_output=True, code_override=None):
            stages = AGILAB_NOTEBOOK_EXPORT.get("stages", [])
            base_stage = stages[stage_index]
            stage = _stage_with_selected_profile(base_stage)
            workdir = Path(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir") or ".").expanduser()
            workdir.mkdir(parents=True, exist_ok=True)
            skip_reason = _stage_skip_reason(stage, workdir)
            if skip_reason:
                print(f"== Skipping AGILAB stage {{stage_index}}: {{skip_reason}} ==")
                return None
            base_code = base_stage.get("code") or ""
            effective_code = stage.get("code") or ""
            code_text = (
                code_override
                if code_override is not None and code_override != base_code
                else effective_code
            )
            script_text = _stage_script_text(stage, code_text)
            stage_for_python = dict(stage)
            stage_for_python["code"] = code_text
            python_exe = _resolve_stage_python(stage_for_python)
            with tempfile.TemporaryDirectory(prefix="agilab_notebook_stage_") as tmpdir:
                script_path = Path(tmpdir) / f"stage_{{stage_index:03d}}.py"
                script_path.write_text(script_text, encoding="utf-8")
                result = subprocess.run(
                    [python_exe, str(script_path)],
                    cwd=str(workdir),
                    text=True,
                    capture_output=capture_output,
                    check=False,
                )
            if capture_output and result.stdout:
                print(result.stdout, end="")
            if capture_output and result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            if check:
                result.check_returncode()
            return result

        def run_agilab_pipeline(stage_indices=None, *, check=True):
            indices = list(stage_indices) if stage_indices is not None else list(range(len(AGILAB_NOTEBOOK_EXPORT.get("stages", []))))
            results = []
            for stage_index in indices:
                print(f"== Running AGILAB stage {{stage_index}} ==")
                results.append(run_agilab_stage(stage_index, check=check))
            return results


        def analysis_launch_command(page, *, port=None):
            argv = analysis_launch_argv(page, port=port)
            if isinstance(argv, str):
                return argv
            return shlex.join(argv)


        def analysis_launch_argv(page, *, port=None):
            record = _page_record(page)
            active_app = resolve_active_app_root()
            script_path = record.get("script_path") or ""
            if not script_path or not _path_exists(script_path):
                return f"# Missing page script for analysis page {{page}}"
            cmd = [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "streamlit",
                "run",
            ]
            if port is not None:
                cmd.extend(["--server.port", str(port)])
            cmd.extend([script_path, "--", "--active-app", active_app])
            return cmd


        def _find_free_streamlit_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]


        def launch_analysis_page(page, *, port=None, wait=False):
            resolved_port = port if port is not None else _find_free_streamlit_port()
            argv = analysis_launch_argv(page, port=resolved_port)
            print(analysis_launch_command(page, port=resolved_port))
            if isinstance(argv, str) and argv.startswith("#"):
                return argv
            if wait:
                return subprocess.run(argv, check=False)
            return subprocess.Popen(argv)


        def render_analysis_page(page, *, fallback_launch=True, port=None):
            record = _page_record(page)
            target = str(record.get("inline_renderer") or "").strip()
            if target:
                try:
                    renderer = _load_inline_renderer(target)
                    result = renderer(
                        page=page,
                        record=record,
                        export_payload=AGILAB_NOTEBOOK_EXPORT,
                    )
                    return _display_inline_result(result)
                except Exception as exc:
                    print(f"Inline analysis failed for {{page}}: {{exc}}", file=sys.stderr)
                    traceback.print_exc()
                    if not fallback_launch:
                        raise
            if fallback_launch:
                return launch_analysis_page(page, port=port)
            return None


        show_agilab_export_summary()
        """
    ).strip() + "\n"
