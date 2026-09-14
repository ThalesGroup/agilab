"""Candidate: exclude missing measurements from both numerator and denominator."""
import json
from pathlib import Path

values = [value for value in json.loads(Path("inputs.json").read_text())["values"] if value is not None]
result = {"mean": sum(values) / len(values)}
Path("result.json").write_text(json.dumps(result, sort_keys=True) + "\n")
