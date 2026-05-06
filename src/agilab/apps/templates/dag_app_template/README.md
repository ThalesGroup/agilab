# DAG App Template

Use this template when a new AGILAB app needs explicit worker-distribution
wiring before it needs a dataframe-specific implementation.

## What This Template Provides

- A minimal app manager package under `src/dag_app/`.
- Pydantic-backed runtime arguments in `dag_app_args.py`.
- A Streamlit argument form in `src/app_args_form.py`.
- Local worker defaults and service-health thresholds in `src/app_settings.toml`.
- A `build_distribution()` hook where the app-specific task graph belongs.

## Create A New App

1. Copy this directory to a new `<name>_project` directory.
2. Rename `your_dag_project` in `pyproject.toml`.
3. Rename the Python package from `dag_app` to the app package name.
4. Update `src/app_settings.toml` so `[args].data_in` points at the app dataset.
5. Replace the empty `build_distribution()` implementation with the real task graph.
6. Add tests beside the new app if the app has behavior beyond template wiring.

## First Local Check

From the repository root, install the app through the normal AGILAB installer,
then select it from the `PROJECT` page:

```bash
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py
```

Keep the first check local before enabling cluster execution.
