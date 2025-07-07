[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?color=informational)](https://pypi.org/project/agilab)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![pypi_dl](https://img.shields.io/pypi/dm/agilab)]()
[![tests](https://thalesgroup.github.io/agilab/tests.svg)](https://thalesgroup.github.io/agilab/tests.svg)
[![coverage](https://thalesgroup.github.io/agilab/coverage.svg)](https://thalesgroup.github.io/agilab/coverage.svg)
[![GitHub stars](https://img.shields.io/github/stars/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab)
[![black](https://img.shields.io/badge/code%20style-black-000000.svg)]()
[![docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid)](https://orcid.org/0009-0003-5375-368X)


# AGILAB Open Source Project

AGILAB [BSD license](https://github.com/ThalesGroup/agilab/blob/main/LICENSE) project purpose is to explore AI for engineering. It is designed to help engineers quickly experiment with AI-driven methods.
See [documentation](https://thalesgroup.github.io/agilab).

## Install and Execution for enduser

```bash
mkdir agi-space && cd agi-workspace
uv init --bare --no-workspace
uv add -p 3.13 --upgrade agilab agi-env agi-cluster agi-node agi-gui
uv run agilab --openai-api-key "your-api-key"
```

## Install for developers

<details open> 
<summary>
    <strong> Linux and MacOs </strong>
</summary>

```bash
git clone https://github.com/ThalesGroup/agilab
cd agilab/src/fwk/core/gui
./install.sh --openai-api-key "your-api-key" --cluster-ssh-credentials "username:[password]"
```
</details>

<details> 
<summary>
    <strong>Windows</strong>
</summary>

```powershell
unzip agilab.zip
cd agilab/src/agi/fwk/gui
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 --openai-api-key "your-api-key"
```
</details>

## AGILab Execution

### Linux and MacOS and Windows:

```bash
cd agilab/src/fwk/core/gui
uv run agilab
```