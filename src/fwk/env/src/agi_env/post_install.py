from re import sub, MULTILINE
from os import path as os_path
from pathlib import Path
import toml


def resolve_packages_path_in_toml(dir_path):
    pyproject_file = Path(dir_path + "/pyproject.toml")

    if not pyproject_file.exists():
        raise FileNotFoundError("pyproject.toml not found in", dir_path)

    content = toml.load(pyproject_file)
    agi_env = Path(__file__).parent.parent.parent
    agi_core = agi_env.parent / "core"

    if "path" in content["tool"]["uv"]["sources"]["agi-env"]:
        content["tool"]["uv"]["sources"]["agi-env"]["path"] = str(agi_env)
    if "path" in content["tool"]["uv"]["sources"]["agi-core"]:
        content["tool"]["uv"]["sources"]["agi-core"]["path"] = str(agi_core)

    with pyproject_file.open("w") as f:
        toml.dump(content, f)

    print("Updated", pyproject_file)


if __name__ == '__main__':
    resolve_packages_path_in_toml("../core")
    resolve_packages_path_in_toml("../lab")
