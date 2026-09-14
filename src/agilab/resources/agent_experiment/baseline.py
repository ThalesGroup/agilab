"""Deliberately biased baseline: missing measurements count as zero."""
import json
from pathlib import Path

values = json.loads(Path("inputs.json").read_text())["values"]
result = {"mean": sum(value or 0 for value in values) / len(values)}
Path("result.json").write_text(json.dumps(result, sort_keys=True) + "\n")
