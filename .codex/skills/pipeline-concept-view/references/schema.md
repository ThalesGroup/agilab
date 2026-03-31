# Conceptual View Contract

## Supported files

- `pipeline_view.dot`
- `pipeline_view.json`

## Placement

Prefer storing the file at the app root.
Fallback placement may be the app source dir or current lab dir, depending on the host UI.

## JSON shape

Either:

- direct `dot` string
- or graph schema with:
  - `direction`
  - `nodes`
  - `edges`
  - optional `graph`, `node`, `edge` defaults
