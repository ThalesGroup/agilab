#!/usr/bin/env python3
"""
Condense verbose task descriptions with GPT-OSS and cache the result locally.

Usage examples:

    uv run python tools/gpt_oss_prompt_helper.py --prompt "Explain how to..."
    echo "Long prompt" | uv run python tools/gpt_oss_prompt_helper.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

DEFAULT_ENDPOINT = "http://127.0.0.1:8000/v1/responses"
DEFAULT_MODEL = "gpt-oss-120b"
DEFAULT_CACHE = Path.home() / ".cache" / "agilab" / "gpt_oss_prompt_cache.json"
CONDENSE_INSTRUCTIONS = (
    "You condense engineering tasks into compact briefs. "
    "Rewrite the provided task using the following format:\n\n"
    "Summary: <one short sentence>\n"
    "Key Steps:\n"
    "- <bullet points with essential actions>\n"
    "Constraints:\n"
    "- <only include if strict requirements exist>\n"
    "Questions:\n"
    "- <list clarifying questions or 'None'>\n\n"
    "Keep the entire response under 120 tokens."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        help="Prompt text to condense. If omitted, stdin is used.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("GPT_OSS_ENDPOINT", DEFAULT_ENDPOINT),
        help="Responses API endpoint (default: %(default)s).",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GPT_OSS_MODEL", DEFAULT_MODEL),
        help="Model checkpoint to query (default: %(default)s).",
    )
    parser.add_argument(
        "--cache-path",
        default=os.getenv("GPT_OSS_CACHE", str(DEFAULT_CACHE)),
        help="Path to the prompt cache file (default: %(default)s).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass cache read/write for this invocation.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cached entry and refresh the summary.",
    )
    parser.add_argument(
        "--show-metadata",
        action="store_true",
        help="Print latency/token metadata to stderr.",
    )
    return parser.parse_args()


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt.strip()
    data = sys.stdin.read()
    if not data.strip():
        raise SystemExit("No prompt provided via --prompt or stdin.")
    return data.strip()


def load_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"entries": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return {"entries": {}}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2)


def cache_lookup(cache: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    return cache.get("entries", {}).get(key)


def cache_store(cache: Dict[str, Any], key: str, value: Dict[str, Any]) -> None:
    cache.setdefault("entries", {})[key] = value


def summarize_with_gpt_oss(prompt: str, *, endpoint: str, model: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
        "instructions": CONDENSE_INSTRUCTIONS,
        "stream": False,
    }
    start = time.perf_counter()
    response = requests.post(endpoint, json=payload, timeout=120)
    latency = time.perf_counter() - start
    response.raise_for_status()
    data = response.json()
    usage = data.get("usage", {})
    text = ""
    for entry in data.get("output", []):
        if entry.get("type") != "message":
            continue
        for part in entry.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                text += str(part.get("text", ""))
    return {
        "text": text.strip(),
        "latency_sec": latency,
        "usage": usage,
        "raw_response": data,
    }


def main() -> None:
    args = parse_args()
    prompt = read_prompt(args)
    cache_path = Path(args.cache_path)
    cache_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    cache = {"entries": {}}
    if not args.no_cache:
        cache = load_cache(cache_path)
        cached = None if args.force_refresh else cache_lookup(cache, cache_key)
        if cached:
            print(cached["text"])
            if args.show_metadata:
                usage = cached.get("usage", {})
                sys.stderr.write(
                    f"[cache] tokens={usage.get('total_tokens')} "
                    f"stored_at={cached.get('timestamp')}\n"
                )
            return

    try:
        result = summarize_with_gpt_oss(prompt, endpoint=args.endpoint, model=args.model)
    except requests.exceptions.RequestException as exc:
        raise SystemExit(f"Failed to contact GPT-OSS at {args.endpoint}: {exc}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SystemExit(f"Invalid JSON body from GPT-OSS at {args.endpoint}: {exc}") from exc

    if args.show_metadata:
        usage = result.get("usage", {})
        sys.stderr.write(
            f"[gpt-oss] latency={result['latency_sec']:.2f}s "
            f"tokens={usage.get('total_tokens')} "
            f"model={args.model}\n"
        )

    print(result["text"])

    if not args.no_cache:
        cache_store(
            cache,
            cache_key,
            {
                "text": result["text"],
                "usage": result.get("usage", {}),
                "model": args.model,
                "endpoint": args.endpoint,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        save_cache(cache_path, cache)


if __name__ == "__main__":
    main()
