# Polars App Template

Use this template for an AGILAB app whose first implementation is a local or
distributed Polars-oriented data pipeline.

## What This Template Provides

- A minimal app manager package under `src/polars_app/`.
- Pydantic-backed runtime arguments in `polars_app_args.py`.
- A Streamlit argument form in `src/app_args_form.py`.
- Local worker defaults and service-health thresholds in `src/app_settings.toml`.
- Dataset bootstrap wiring for an optional `data.7z` archive.
- Empty `work_pool()`, `work_done()`, and `build_distribution()` hooks for app logic.

## Create A New App

1. Copy this directory to a new `<name>_project` directory.
2. Rename `your_polars_project` in `pyproject.toml`.
3. Rename the Python package from `polars_app` to the app package name.
4. Update `src/app_settings.toml` so `[args].data_in` points at the app dataset.
5. Replace the template hooks with the real Polars pipeline and output contract.
6. Add focused tests for argument loading, dataset bootstrapping, and exported artifacts.

## First Local Check

From the repository root, install the app through the normal AGILAB installer,
then select it from the `PROJECT` page:

```bash
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py
```

Keep the first check local before enabling cluster execution.
