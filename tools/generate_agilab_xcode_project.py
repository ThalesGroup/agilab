#!/usr/bin/env python3
"""Generate local Xcode schemes from AGILAB's canonical PyCharm configurations.

Build checks configuration; Run executes the selected workflow through uv.
This is an IDE adapter, not a second build system or a Python language server.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from generate_vscode_tasks import (
    RunConfiguration,
    expand_for_vscode,
    load_runconfig,
    option_is_truthy,
    pytest_arguments,
    resolve_debug_module,
    sanitize_name,
    tracked_runconfigs,
)

PROJECT_NAME = "AGILAB.xcodeproj"
MANIFEST = "agilab-xcode-generated-files.json"
GENERATOR = "tools/generate_agilab_xcode_project.py"


@dataclass(frozen=True)
class LaunchPlan:
    argv: list[str]
    cwd: Path
    env: dict[str, str]


def prompt_key(label: str) -> str:
    return "AGILAB_XCODE_INPUT_" + sanitize_name(label).upper()


def decode_option(value: str) -> str:
    """JetBrains serializes pytest _new_* values as JSON strings in XML."""
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, str):
            return decoded
    return value


def configuration_inputs(config: RunConfiguration) -> dict[str, dict[str, str]]:
    inputs: dict[str, dict[str, str]] = {}
    for value in [*config.options.values(), *config.env_map.values(), config.workdir]:
        expand_for_vscode(value, inputs)
    return inputs


def expand_value(
    value: str, root: Path, environment: dict[str, str],
    inputs: dict[str, dict[str, str]],
) -> str:
    value = expand_for_vscode(value, inputs)
    for identifier, definition in inputs.items():
        marker = "${input:" + identifier + "}"
        if marker not in value:
            continue
        key = "AGILAB_XCODE_FILE" if identifier == "file_prompt" else prompt_key(definition["description"])
        default = "" if identifier == "file_prompt" else definition.get("default", "")
        answer = environment.get(key, default)
        if not answer:
            raise ValueError(f"Set {key} in Xcode Edit Scheme > Run > Arguments > Environment Variables.")
        value = value.replace(marker, answer)
    value = value.replace("${workspaceFolder}", str(root))
    value = value.replace("${env:HOME}", environment.get("HOME", str(Path.home())))
    value = value.replace("$USER_HOME$", environment.get("HOME", str(Path.home())))
    value = value.replace("$PROJECT_DIR$", str(root)).replace("$ProjectFileDir$", str(root))
    if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\{input:", value):
        raise ValueError(f"Unsupported IDE macro in {value!r}")
    return value


def argument_tokens(
    value: str, root: Path, environment: dict[str, str],
    inputs: dict[str, dict[str, str]],
) -> list[str]:
    # Protect whole prompt macros before shlex; expand paths and answers only
    # afterwards. Never interpret arguments or environment values as shell code.
    protected = expand_for_vscode(value, inputs)
    return [expand_value(token, root, environment, inputs) for token in shlex.split(protected)]


def sdk_project(config: RunConfiguration, root: Path, environment: dict[str, str]) -> Path:
    sdk = config.options.get("SDK_NAME", "")
    if not sdk or sdk in {"uv (agilab)", f"uv ({root.name})"}:
        return root
    match = re.fullmatch(r"uv \(([A-Za-z0-9_-]+)\)", sdk)
    if not match:
        raise ValueError(f"Unsupported Python SDK {sdk!r}; use an AGILAB uv SDK or explicit SDK_HOME.")
    name = match.group(1)
    if name in {"agi-env", "agi-node", "agi-core", "agi-cluster"}:
        return root / "src/agilab/core" / name
    if name == "agi-space":
        return root.parent / name
    if name.endswith("_worker"):
        return Path(environment.get("HOME", str(Path.home()))) / "wenv" / name
    candidates = [root / "src/agilab/apps" / name, root / "src/agilab/apps/builtin" / name]
    existing = [candidate for candidate in candidates if (candidate / "pyproject.toml").is_file()]
    if len(existing) != 1:
        raise ValueError(f"SDK {sdk!r} needs one installed app project under src/agilab/apps (found {len(existing)}).")
    return existing[0]


def build_launch(
    config: RunConfiguration, repo_root: Path, uv_path: str,
    environment: dict[str, str] | None = None, *, pdb: bool = False,
) -> LaunchPlan:
    root = repo_root.resolve()
    environment = dict(os.environ if environment is None else environment)
    inputs = configuration_inputs(config)
    env = dict(environment)
    for name, value in config.env_map.items():
        if name != "VIRTUAL_ENV":
            env[name] = expand_value(value, root, environment, inputs)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_RUN_RECURSION_DEPTH", None)
    cwd_value = expand_value(config.workdir, root, environment, inputs) if config.workdir else str(root)
    cwd = Path(cwd_value)
    if not cwd.is_absolute():
        cwd = root / cwd
    sdk_home = config.options.get("SDK_HOME", "")
    if sdk_home:
        python = Path(expand_value(sdk_home, root, environment, inputs))
        if not python.is_absolute() or python.parent.name != "bin":
            raise ValueError("SDK_HOME must name an absolute macOS virtualenv bin/python executable.")
        project = root
        venv = python.parent.parent
    else:
        project = sdk_project(config, root, environment)
        venv = project / ".venv"
        python = venv / "bin/python"
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    # IDE Run must preserve the prepared SDK, without resolving dependencies.
    argv = [uv_path, "--preview-features", "extra-build-dependencies", "run", "--no-sync",
            "--project", str(project), "--python", str(python), "python"]
    argv.extend(argument_tokens(config.options.get("INTERPRETER_OPTIONS", ""), root, environment, inputs))
    if config.config_type == "tests" and config.factory_name == "py.test":
        normalized = replace(config, options={
            key: decode_option(value) if key.startswith("_new_") else value
            for key, value in config.options.items()
        })
        argv += ["-m", "pytest"]
        argv += [expand_value(token, root, environment, inputs) for token in pytest_arguments(normalized, inputs)]
        if pdb:
            argv.append("--pdb")
    elif config.config_type == "PythonConfigurationType":
        script = config.options.get("SCRIPT_NAME", "")
        module = resolve_debug_module(config)
        if option_is_truthy(config.options.get("MODULE_MODE", "false")) and not module:
            raise ValueError(f"{config.name}: module mode needs a Python module name.")
        if pdb:
            argv += ["-m", "pdb"]
        if module:
            argv += ["-m", expand_value(module, root, environment, inputs)]
        elif script:
            argv.append(expand_value(script, root, environment, inputs))
        else:
            raise ValueError(f"{config.name}: no script or module configured.")
        argv.extend(argument_tokens(config.options.get("PARAMETERS", ""), root, environment, inputs))
    else:
        raise ValueError(f"Unsupported run configuration {config.name!r}: {config.config_type}/{config.factory_name}")
    return LaunchPlan(argv, cwd, env)


def collect_configurations(root: Path) -> list[RunConfiguration]:
    directory = root / ".idea/runConfigurations"
    if not directory.is_dir():
        raise ValueError(f"No canonical run configurations at {directory}")
    configs = []
    names: set[str] = set()
    for path in tracked_runconfigs(root, directory):
        if path.name.startswith("_"):
            continue
        try:
            tree = ET.parse(path)
        except ET.ParseError as error:
            raise ValueError(f"Invalid run configuration {path}: {error}") from error
        if tree.find(".//configuration") is None:
            continue
        config = load_runconfig(path)
        if config is None:
            raise ValueError(f"Cannot load run configuration {path}")
        if config.config_type != "PythonConfigurationType" and not (
            config.config_type == "tests" and config.factory_name == "py.test"
        ):
            raise ValueError(f"Unsupported run configuration type in {path}: {config.config_type}")
        if config.name in names:
            raise ValueError(f"Duplicate run configuration name: {config.name}")
        names.add(config.name)
        configs.append(config)
    if not configs:
        raise ValueError("No supported run configurations found.")
    return sorted(configs, key=lambda config: config.name)


def object_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24].upper()


def configuration_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    paths = tracked_runconfigs(root, root / ".idea/runConfigurations")
    paths += [root / GENERATOR, root / "tools/generate_vscode_tasks.py"]
    for path in sorted(paths):
        if path.is_file() and not path.name.startswith("_"):
            digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def check_project_freshness(root: Path) -> None:
    manifest = root / PROJECT_NAME / MANIFEST
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        if data.get("configuration_sha256") != configuration_fingerprint(root):
            raise ValueError("Xcode project is stale; rerun tools/generate_agilab_xcode_project.py before Build/Run.")


def navigator_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=root, capture_output=True, check=False,
    )
    if result.returncode:
        # Exported source trees also work, without recursively indexing caches.
        return sorted(str(path.relative_to(root)) for path in root.iterdir() if path.is_file())
    suffixes = {".py", ".pyi", ".pyx", ".c", ".h", ".rs", ".sh", ".ps1", ".toml",
                ".json", ".yml", ".yaml", ".xml", ".md", ".rst", ".txt", ".ini", ".cfg"}
    return sorted({
        value for value in result.stdout.decode().split("\0")
        if value and not value.startswith(("docs/html/", "reports/", "AGILAB.xcodeproj/"))
        and (Path(value).suffix in suffixes or Path(value).name in {"dev", ".gitignore"})
        and (root / value).is_file()
    })


def scheme_xml(config: RunConfiguration, root: Path, uv_path: str, target_id: str) -> str:
    scheme = ET.Element("Scheme", LastUpgradeVersion="2640", version="1.3")
    build = ET.SubElement(scheme, "BuildAction", parallelizeBuildables="YES", buildImplicitDependencies="YES")
    entries = ET.SubElement(build, "BuildActionEntries")
    entry = ET.SubElement(entries, "BuildActionEntry", buildForTesting="NO", buildForRunning="YES",
                          buildForProfiling="NO", buildForArchiving="NO", buildForAnalyzing="YES")

    def reference(parent: ET.Element) -> None:
        ET.SubElement(parent, "BuildableReference", BuildableIdentifier="primary",
                      BlueprintIdentifier=target_id, BuildableName="AGILAB Configuration Check",
                      BlueprintName="AGILAB Configuration Check", ReferencedContainer=f"container:{PROJECT_NAME}")
    reference(entry)
    launch = ET.SubElement(
        scheme, "LaunchAction", buildConfiguration="Debug", selectedDebuggerIdentifier="",
        selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.PosixSpawn", launchStyle="0",
        useCustomWorkingDirectory="YES", customWorkingDirectory=str(root),
        ignoresPersistentStateOnLaunch="NO", debugDocumentVersioning="NO", allowLocationSimulation="NO",
    )
    ET.SubElement(launch, "PathRunnable", runnableDebuggingMode="0", FilePath=uv_path)
    reference(ET.SubElement(launch, "MacroExpansion"))
    args = ET.SubElement(launch, "CommandLineArguments")
    for value in ["--preview-features", "extra-build-dependencies", "run", "--no-sync",
                  "--project", str(root), "python", str(root / GENERATOR), "--uv", uv_path, "--run", config.name]:
        ET.SubElement(args, "CommandLineArgument", argument=shlex.quote(value), isEnabled="YES")
    variables = ET.SubElement(launch, "EnvironmentVariables")
    values = {"VIRTUAL_ENV": "", "UV_PROJECT_ENVIRONMENT": str(root / ".venv"), "PYTHONUNBUFFERED": "1"}
    for identifier, definition in configuration_inputs(config).items():
        key = "AGILAB_XCODE_FILE" if identifier == "file_prompt" else prompt_key(definition["description"])
        values[key] = "" if identifier == "file_prompt" else definition.get("default", "")
    for key, value in sorted(values.items()):
        ET.SubElement(variables, "EnvironmentVariable", key=key, value=value, isEnabled="YES")
    ET.SubElement(scheme, "AnalyzeAction", buildConfiguration="Debug")
    ET.indent(scheme, space="   ")
    return ET.tostring(scheme, encoding="unicode", xml_declaration=True) + "\n"


def generate_project(root: Path, uv_path: str) -> dict[str, str]:
    root = root.resolve()
    configs = collect_configurations(root)
    objects: dict[str, dict] = {}
    main_group, target, project = (object_id(name) for name in ("main", "check-target", "project"))
    objects[main_group] = {"isa": "PBXGroup", "children": [], "sourceTree": "<group>"}
    groups = {"": main_group}
    for filename in navigator_files(root):
        path = Path(filename)
        for parent in reversed(path.parents):
            name = "" if parent == Path(".") else parent.as_posix()
            if name in groups:
                continue
            group_id = object_id("group:" + name)
            groups[name] = group_id
            objects[group_id] = {"isa": "PBXGroup", "children": [], "name": parent.name, "sourceTree": "<group>"}
            parent_name = "" if parent.parent == Path(".") else parent.parent.as_posix()
            objects[groups[parent_name]]["children"].append(group_id)
        file_id = object_id("file:" + filename)
        file_type = "text.script.python" if path.suffix in {".py", ".pyi"} else "text"
        objects[file_id] = {"isa": "PBXFileReference", "lastKnownFileType": file_type,
                            "name": path.name, "path": filename, "sourceTree": "SOURCE_ROOT"}
        parent_name = "" if path.parent == Path(".") else path.parent.as_posix()
        objects[groups[parent_name]]["children"].append(file_id)

    def configuration_list(name: str) -> str:
        list_id = object_id(name + ":configs")
        config_ids = []
        for label in ("Debug", "Release"):
            identity = object_id(name + ":" + label)
            config_ids.append(identity)
            objects[identity] = {"isa": "XCBuildConfiguration", "name": label, "buildSettings": {
                "CODE_SIGNING_ALLOWED": "NO", "SDKROOT": "macosx", "SUPPORTED_PLATFORMS": "macosx",
            }}
        objects[list_id] = {"isa": "XCConfigurationList", "buildConfigurations": config_ids,
                            "defaultConfigurationIsVisible": "0", "defaultConfigurationName": "Debug"}
        return list_id

    objects[target] = {
        "isa": "PBXLegacyTarget", "name": "AGILAB Configuration Check", "productName": "AGILAB",
        "buildConfigurationList": configuration_list("target"), "buildPhases": [], "dependencies": [],
        "buildToolPath": "/usr/bin/env", "buildWorkingDirectory": str(root),
        "passBuildSettingsInEnvironment": "1",
        "buildArgumentsString": shlex.join([
            "-u", "VIRTUAL_ENV", "-u", "UV_PROJECT_ENVIRONMENT", "-u", "UV_RUN_RECURSION_DEPTH",
            uv_path, "--preview-features", "extra-build-dependencies", "run", "--no-sync",
            "--project", str(root), "python", str(root / GENERATOR), "--uv", uv_path, "--check",
        ]),
    }
    objects[project] = {
        "isa": "PBXProject", "attributes": {"LastUpgradeCheck": "2640"},
        "buildConfigurationList": configuration_list("project"), "compatibilityVersion": "Xcode 14.0",
        "developmentRegion": "en", "knownRegions": ["en", "Base"], "mainGroup": main_group,
        "projectDirPath": "", "projectRoot": "", "targets": [target],
    }
    payload = {"archiveVersion": "1", "classes": {}, "objectVersion": "56",
               "objects": objects, "rootObject": project}
    result = {"project.pbxproj": plistlib.dumps(payload, sort_keys=True).decode()}
    filenames: set[str] = set()
    for config in configs:
        filename = config.name.replace("/", " - ").replace(":", " - ").strip().lstrip(".") or "AGILAB"
        if filename.casefold() in filenames:
            filename += "-" + object_id(config.name)[:8].lower()
        filenames.add(filename.casefold())
        result[f"xcshareddata/xcschemes/{filename}.xcscheme"] = scheme_xml(config, root, uv_path, target)
    return result


def write_project(root: Path, files: dict[str, str]) -> Path:
    project = root / PROJECT_NAME
    manifest_path = project / MANIFEST
    old: list[str] = []
    if project.exists():
        if project.is_symlink() or not manifest_path.is_file():
            raise ValueError(f"Refusing to overwrite unmanaged Xcode project: {project}")
        previous = json.loads(manifest_path.read_text())
        if previous.get("generator") != GENERATOR:
            raise ValueError(f"Refusing to overwrite an unrelated project manifest: {manifest_path}")
        old = previous["files"]
    project.mkdir(exist_ok=True)
    for filename in sorted(set(old) | set(files)):
        path = project / filename
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError(f"Generated path escapes the Xcode project: {filename}")
        if filename in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(files[filename], encoding="utf-8")
        elif filename.startswith("xcshareddata/xcschemes/") and path.is_file():
            path.unlink()
    manifest_path.write_text(json.dumps({
        "generator": GENERATOR, "configuration_sha256": configuration_fingerprint(root),
        "files": sorted(files),
    }, indent=2) + "\n")
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", help="Absolute uv executable, recorded in local Xcode schemes.")
    parser.add_argument("--check", action="store_true", help="Validate configurations without executing workflows.")
    parser.add_argument("--run", metavar="CONFIGURATION", help="Run a named canonical PyCharm configuration.")
    parser.add_argument("--print-command", action="store_true", help="Show argv/cwd for --run without executing.")
    parser.add_argument("--pdb", action="store_true", help="Use pdb in the console, or pytest --pdb.")
    parser.add_argument("--open", action="store_true", help="Open the generated project in Xcode.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    uv = args.uv or shutil.which("uv")
    if not uv or not Path(uv).is_file():
        parser.error("uv is required; install it or pass --uv /absolute/path/to/uv.")
    try:
        configs = collect_configurations(root)
        if args.run:
            check_project_freshness(root)
            config = next((item for item in configs if item.name == args.run), None)
            if config is None:
                raise ValueError(f"Unknown configuration {args.run!r}; regenerate the Xcode project after renames.")
            plan = build_launch(config, root, uv, pdb=args.pdb)
            if args.print_command:
                print(json.dumps({"configuration": config.name, "argv": plan.argv, "cwd": str(plan.cwd)}, indent=2))
                return 0
            if not plan.cwd.is_dir():
                raise ValueError(f"Working directory is missing: {plan.cwd}. Complete this configuration's install/setup first.")
            python = Path(plan.argv[plan.argv.index("--python") + 1])
            if not python.is_file():
                raise ValueError(f"SDK interpreter is missing: {python}. Prepare that project's environment with uv sync first.")
            os.chdir(plan.cwd)
            os.execve(uv, plan.argv, plan.env)
        if args.check:
            check_project_freshness(root)
            for config in configs:
                environment = dict(os.environ)
                for identifier, definition in configuration_inputs(config).items():
                    key = "AGILAB_XCODE_FILE" if identifier == "file_prompt" else prompt_key(definition["description"])
                    environment.setdefault(key, definition.get("default") or "__REQUIRED_AT_RUN__")
                    if not environment[key]:
                        environment[key] = "__REQUIRED_AT_RUN__"
                build_launch(config, root, uv, environment)
            print(f"Validated {len(configs)} Xcode run configurations; no workflows executed.")
            return 0
        project = write_project(root, generate_project(root, uv))
        print(f"Generated {len(configs)} shared schemes and source navigator: {project}")
        print("Build validates configuration. Run executes the selected workflow. Python debugging uses --pdb, not LLDB.")
        if args.open:
            subprocess.run(["open", "-a", "Xcode", str(project)], check=True)
        return 0
    except (ValueError, OSError) as error:
        print(f"AGILAB Xcode: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
