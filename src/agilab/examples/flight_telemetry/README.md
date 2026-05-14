# Flight Example

## Purpose

Runs `flight_telemetry_project`, the default public AGILAB first-run app for file-based
flight ingestion and map analysis.

## What You Learn

- How the recommended first proof maps to a plain Python install/run pair.
- How `RunRequest` points to a share-root input directory and output directory.
- How AGILAB turns one flight input file into analysis-ready dataframe artifacts.

## Install

```bash
python ~/log/execute/flight_telemetry/AGI_install_flight_telemetry.py
```

## Run

```bash
python ~/log/execute/flight_telemetry/AGI_run_flight_telemetry.py
```

## Expected Input

The default run reads one file from `flight/dataset` in AGILAB shared storage.
If the dataset is missing, install the built-in apps or run the first-proof path
that seeds the public flight sample.

## Expected Output

The run writes dataframe artifacts under `flight/dataframe` for the default
`view_maps` analysis page.

## Read The Script

Open `AGI_run_flight_telemetry.py` and look for these lines first:

- `APP = "flight_telemetry_project"` selects the built-in app.
- `data_in="flight/dataset"` names the input folder.
- `data_out="flight/dataframe"` names the generated artifacts.
- `mode=LOCAL_RUN_MODES` runs the stable public local worker modes.

## Change One Thing

After the default run works, change `nfile` from `1` to another small value and
rerun the script. Keep `data_in` and `data_out` unchanged for the first
experiment so you can compare only the effect of the file count.

## Troubleshooting

- If the script cannot find `.agilab-path`, run the AGILAB installer first.
- If no flight files are found, rerun `agilab first-proof --json` or reinstall
  the built-in examples.
- If the map view is empty, check that `flight/dataframe` contains fresh files.
