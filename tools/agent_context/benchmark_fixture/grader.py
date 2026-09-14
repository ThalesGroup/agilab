"""Check packet integrity and declared retrieval acceptance on the frozen cohort."""

import hashlib
import json
from pathlib import Path
import sys

import tiktoken

encoding = tiktoken.get_encoding("o200k_base")

corpus = json.loads(Path("contexts.json").read_text(encoding="utf-8"))
result = json.loads((Path(sys.argv[1]) / "measurements.json").read_text())
variant = result["variant"]
rows = {row["task"]: row for row in result["rows"]}
checks = {
    "exact_tasks": len(rows) == len(result["rows"])
    and set(rows) == {case["task"] for case in corpus["cases"]},
    "context_intact": True,
    "mandatory_policy_intact": True,
    "selected_sources_complete": True,
    "within_context_budget": True,
}
for case in corpus["cases"]:
    packet = case[variant]
    row = rows.get(case["task"], {})
    actual_count = len(encoding.encode(packet["context_text"], disallowed_special=()))
    checks["context_intact"] &= (
        row.get("reference_tokens") == actual_count
        and packet["actual_tokens"] == actual_count
        and row.get("text_sha256")
        == hashlib.sha256(packet["context_text"].encode()).hexdigest()
    )
    required = {
        item["selector"]: item["sha256"]
        for item in packet["selected"]
        if item["required"]
    }
    checks["mandatory_policy_intact"] &= (
        required == case["required_policy"] and packet["status"] == "pass"
    )
    checks["selected_sources_complete"] &= packet["complete"]
    checks["within_context_budget"] &= (
        type(row.get("reference_tokens")) is int
        and 0 <= actual_count <= corpus["context_budget"]
    )
print(
    json.dumps(
        {"schema": "agilab.agent_experiment_acceptance.v1", "checks": checks},
        sort_keys=True,
    )
)
