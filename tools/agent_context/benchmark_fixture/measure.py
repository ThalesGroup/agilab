"""Count frozen context packets; no provider calls or fabricated usage events."""

import hashlib
import json
from pathlib import Path
import time

import tiktoken


def run(variant):
    corpus = json.loads(Path("contexts.json").read_text(encoding="utf-8"))
    encoding = tiktoken.get_encoding("o200k_base")
    rows = []
    for case in corpus["cases"]:
        packet = case[variant]
        text = packet["context_text"]
        started = time.perf_counter()
        count = len(encoding.encode(text, disallowed_special=()))
        rows.append(
            {
                "task": case["task"],
                "reference_tokens": count,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "count_seconds": time.perf_counter() - started,
                "within_budget": count <= corpus["context_budget"],
            }
        )
    Path("measurements.json").write_text(
        json.dumps({"variant": variant, "rows": rows}, indent=2) + "\n"
    )
