from pathlib import Path
import pytest
import tempfile
from agi_env import AgiEnv

agipath = AgiEnv.locate_agi_installation()

# Fixture to create the environment once for all test.
@pytest.fixture
def env():
    default_module_file = agipath / Path("apps/my-code-project/src/my_code/my_code.py")
    return AgiEnv(default_module_file, with_lab=True, verbose=1)


def test_envcreated(env):
    # Test that the environment is created.
    assert env, "Environment should be created successfully."


def test_projects_found(env):
    # Test that multiple projects are found.
    apps_root = agipath / "apps/"
    projects_found = env.get_projects(apps_root)
    nb_projects = len(projects_found)
    assert nb_projects > 1, f"Expected more than 1 project, but found {nb_projects}."


def test_modules_found(env):
    # Test that multiple modules are found.
    modules_found = env.get_modules()
    nb_modules = len(modules_found)
    assert nb_modules > 1, f"Expected more than 1 module, but found {nb_modules}."


def test_resource_dir_exists(env):
    # Test that the deployed resources directory exists.
    resource_dir = env.deployed_resources_abs
    assert resource_dir.exists(), f"Resource directory {resource_dir} does not exist."


def test_varenvfile_exists(env):
    # Test that the .env file exists in the resources directory.
    resource_dir = env.deployed_resources_abs
    varenvfile = resource_dir / ".env"
    assert varenvfile.exists(), f"'.env' file {varenvfile} does not exist."


def test_resources_files_count(env):
    # Test that there are more than 11 files in the resources directory.
    resource_dir = env.deployed_resources_abs
    files_found = list(resource_dir.rglob("*"))
    nb_files = len(files_found)
    assert nb_files > 11, f"Expected more than 11 resource files, but found {nb_files}."


def test_create_symlink():
    # Create a temporary source file and a destination for the symlink.
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "src.txt"
        dest_link = Path(tmpdir) / "dest_link.txt"
        src_file.write_text("hello world")
        # Create the symlink using the AGI method.
        AgiEnv.create_symlink(src_file, dest_link)
        # Verify that dest_link is a symlink and resolves to the source.
        assert dest_link.is_symlink(), "Destination should be a symlink."
        assert dest_link.resolve() == src_file.resolve(), "Symlink does not resolve to the source."


if __name__ == '__main__':
    pytest.main()