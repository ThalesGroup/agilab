"""Independent acceptance using the frozen cohort and Python's statistics module."""
import json
import math
from pathlib import Path
import statistics
import sys

values = json.loads(Path("inputs.json").read_text())["values"]
actual = json.loads((Path(sys.argv[1]) / "result.json").read_text())["mean"]
expected = statistics.mean(value for value in values if value is not None)
checks = {"finite_mean": math.isfinite(actual), "missing_values_excluded": actual == expected}
print(json.dumps({"schema": "agilab.agent_experiment_acceptance.v1", "checks": checks}, sort_keys=True))
