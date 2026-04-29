# AGILAB Packaged Examples

These examples are small Python entry points copied by the app installer into
`~/log/execute/<app>/`. They are meant to be readable first-run snippets for the
public built-in apps, not a separate workflow engine.

| Example | App | Purpose |
|---|---|---|
| `flight` | `flight_project` | Install and run the public flight ingestion path. |
| `mycode` | `mycode_project` | Minimal worker template and execution smoke. |
| `meteo_forecast` | `meteo_forecast_project` | Forecasting notebook-to-project migration demo. |
| `data_io_2026` | `data_io_2026_project` | Deterministic autonomous mission-data decision demo. |

Typical use:

```bash
python ~/log/execute/flight/AGI_install_flight.py
python ~/log/execute/flight/AGI_run_flight.py
```

Run `agilab first-proof --json` when you want the shortest packaged product
proof. Use these scripts when you want to inspect or adapt the generated
programmatic calls.
