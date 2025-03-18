# AGILAB Open Source Project

| Version Status                                                                               |
|----------------------------------------------------------------------------------------------|
| [![PyPI version](https://img.shields.io/pypi/v/agilab.svg)](https://pypi.org/project/agilab) |


## Get started

AGILAB project purpose is to explore AI for engineering. It is designed to help engineers quickly experiment with AI-driven methods.

## Install AGILAB for contributors

#### Linux and MacOS

```bash
    unzip agilab-main.zip
    cd agilab-main/src
    ./install.sh --openai-api-key
"your-api-key" --install-path "your-install-dir"
 ```

#### Windows

```powershell
    unzip agilab-main.zip
    cd agilab-main/agi
    powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 --openai-api-key
"your-api-key" --install-path "your-install-dir"
 ```

#### Execution

```bash
cd agilab-main/src/fwk/lab
uv run python -m streamlit run src/agi_lab/AGILAB.py
 ```

## Documentation

Documentation is available at [documentation site](https://thalesgroup.github.io/agilab/docs/html/index.html
).
For additional guides and tutorials, consider checking our GitHub Pages.

## Contributing

If you are interested in contributing to the AGILAB project, start by reading the [Contributing guide](/CONTRIBUTING.md).

## License

This project is distributed under the New BSD License.
See the [License File](agi/LICENSE) for full details.