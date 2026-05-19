# View Demo

This AGILAB analysis page template is app-agnostic. When it is created from the
Analysis page, AGILAB passes the active project path to the Streamlit page.

Quick start:

- Open the page from Analysis after selecting a project.
- Use the embedded AGILAB sidecar runner; the active project is passed automatically.
- Run the project workflow first, then refresh this page to inspect dataset outputs.

Files:

- `pyproject.toml`: page-specific dependency declaration.
- `src/view_demo/__init__.py`: package module marker.
- `src/view_demo/view_demo.py`: Streamlit page script.
