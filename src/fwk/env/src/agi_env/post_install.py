from pathlib import Path
import tomli
import tomli_w

def resolve_packages_path_in_toml(dir_path):
    pyproject_file = Path(dir_path) / "pyproject.toml"

    if not pyproject_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {dir_path}")

    # Load the TOML content using tomli
    with pyproject_file.open("rb") as f:
        content = tomli.load(f)

    # Calculate paths for agi-env and agi-core
    agi_env = Path(__file__).parent.parent.parent
    agi_core = agi_env.parent / "core"

    # Safely retrieve and update the agi-env dictionary if it exists
    agi_env_dict = content.get("tool", {}).get("uv", {}).get("sources", {}).get("agi-env")
    if isinstance(agi_env_dict, dict) and "path" in agi_env_dict:
        agi_env_dict["path"] = str(agi_env)

    # Safely retrieve and update the agi-core dictionary if it exists
    agi_core_dict = content.get("tool", {}).get("uv", {}).get("sources", {}).get("agi-core")
    if isinstance(agi_core_dict, dict) and "path" in agi_core_dict:
        agi_core_dict["path"] = str(agi_core)

    # Write the updated content back using tomli_w
    with pyproject_file.open("wb") as f:
        tomli_w.dump(content, f)

    print("Updated", pyproject_file)

if __name__ == '__main__':
    resolve_packages_path_in_toml("../core")
    resolve_packages_path_in_toml("../gui")