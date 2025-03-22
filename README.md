# AGILAB Open Source Project

| Version Status                                                                               |
|----------------------------------------------------------------------------------------------|
| [![PyPI version](https://img.shields.io/pypi/v/agilab.svg)](https://pypi.org/project/agilab) |


## Get started

AGILAB project purpose is to explore AI for engineering. It is designed to help engineers quickly experiment with AI-driven methods.


## Install AGILAB for endusers

```bash
    mkdir agi-workspace && cd agi-workspace
    uv init && uv add agilab 
````

## Install AGILAB for contributors

#### Linux and MacOS

```bash
    
    git clone https://github.com/ThalesGroup/agilab.git
    cd agilab
    git checkout main
    ./install.sh --openai-api-key "your-api-key" --install-path "your-install-dir"
    then open agilab/src project preferably with Pycharm
 ```

#### Windows

```powershell
    go with your browser to https://github.com/ThalesGroup/agilab and download agilab-main.zip 
    unzip agilab-main.zip
    cd agilab-main
    powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 --openai-api-key "your-api-key" --install-path "your-install-dir"
    then open agilab/src project preferably with Pycharm
 ```

#### Execution

```bash
uv run agilab
 ```

## Documentation

Documentation is available at [documentation site](https://thalesgroup.github.io/agilab)
).
For additional guides and tutorials, consider checking our GitHub Pages.

## Contributing

If you are interested in contributing to the AGILAB project, start by reading the [Contributing guide](/CONTRIBUTING.md).

## License

This project is distributed under the New BSD License.
See the [License File](agi/LICENSE) for full details.