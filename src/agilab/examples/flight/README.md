# Flight Example

## Purpose

Runs `flight_project`, the default public AGILAB first-run app for file-based
flight ingestion and map analysis.

## Install

```bash
python ~/log/execute/flight/AGI_install_flight.py
```

## Run

```bash
python ~/log/execute/flight/AGI_run_flight.py
```

## Expected Input

The default run reads one file from `flight/dataset` in AGILAB shared storage.
If the dataset is missing, install the built-in apps or run the first-proof path
that seeds the public flight sample.

## Expected Output

The run writes dataframe artifacts under `flight/dataframe` for the default
`view_maps` analysis page.
