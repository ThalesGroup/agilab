installation:

- Linux/MacOS:<br>
  chmod +x ./install.sh<br>
  ./install

- Python

uv run -_project ..\agilab\cluster python .\install.py <module>

Example with uv run -_project ../agilab/cluster python ./install.py flight<br>
uv run -_project ..\agilab\cluster python .\install.py agilab\cluster python .\install.py /uv
run
-_project ../agilab/cluster/manager python ./install.py flight

## Example App service/priority hints

When running `example_app_project`, you can steer synthetic demand generation by
dropping a `service.json` next to your dataset (defaults to `data_in/service.json`
or set `services_conf`). Each entry can set `name`, optional `priority`, `latency_ms`,
`bandwidth_min`/`bandwidth_max`, and `weight` (selection bias). The generator uses
those values to fill `ilp_demands.json`, so ILP and training runs inherit your
service mix and priorities without code changes.
