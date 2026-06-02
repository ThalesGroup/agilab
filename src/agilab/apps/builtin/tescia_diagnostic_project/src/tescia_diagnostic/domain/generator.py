"""Standalone-AI diagnostic case generation for the TeSciA app."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .diagnostic import CASE_SCHEMA, validate_case_payload

SUPPORTED_PROVIDERS = ("gpt-oss", "ollama")
DEFAULT_GPT_OSS_ENDPOINT = "http://127.0.0.1:8000/v1/responses"
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_GPT_OSS_MODEL = "gpt-oss-120b"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:latest"

HttpPostJson = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]


class DiagnosticCaseGenerationError(RuntimeError):
    """Raised when standalone AI cannot produce valid diagnostic case JSON."""


def build_generation_prompt(*, topic: str, case_count: int) -> str:
    """Return the strict JSON-only prompt sent to the standalone engine."""

    return f"""Generate {case_count} TeSciA-style diagnostic case(s) for AGILAB.

Topic:
{topic.strip() or "AGILAB engineering diagnostics"}

Return only one JSON object. Do not wrap it in Markdown. The JSON object must
match this schema:
{{
  "schema": "{CASE_SCHEMA}",
  "cases": [
    {{
      "case_id": "short_snake_case_id",
      "title": "student-facing exercise title",
      "difficulty": "intro|intermediate|advanced",
      "topic_tags": ["topic", "diagnostic-skill"],
      "estimated_minutes": 20,
      "learner_level": "engineering student",
      "student_prompt": "prompt shown to the student before they answer",
      "symptom": "operator-visible failure symptom",
      "proposed_diagnosis": "diagnosis to challenge",
      "root_cause": "evidence-backed root cause",
      "plain_repro": "first discriminator command or UI action",
      "weak_assumptions": ["weak assumption 1", "weak assumption 2"],
      "evidence": [
        {{
          "id": "short_evidence_id",
          "description": "specific evidence item",
          "confidence": 0.9,
          "relevance": 0.9
        }}
      ],
      "candidate_fixes": [
        {{
          "id": "short_fix_id",
          "summary": "stronger fix",
          "expected_impact": 0.9,
          "blast_radius": 0.3,
          "reversibility": 0.8
        }},
        {{
          "id": "weaker_fix_id",
          "summary": "weaker or obvious fix",
          "expected_impact": 0.4,
          "blast_radius": 0.7,
          "reversibility": 0.5
        }}
      ],
      "regression_tests": [
        {{
          "id": "short_test_id",
          "description": "test that proves or disproves the diagnosis",
          "automated": true,
          "discriminator": true
        }}
      ]
    }}
  ]
}}

Constraints:
- Include exactly {case_count} case(s).
- Use confidence, relevance, expected_impact, blast_radius, and reversibility
  values between 0.0 and 1.0.
- Each case must include at least two evidence items, two candidate fixes, and
  two regression tests.
- Do not include student_answer unless the caller asks for an answer key sample;
  TeSciA accepts student_answer later when a learner submits their response.
- Prefer concrete AGILAB diagnostics over generic software advice.
"""


def _post_json(url: str, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - user-configured local endpoint.
            body = response.read().decode("utf-8")
    except (OSError, URLError, TimeoutError) as exc:
        raise DiagnosticCaseGenerationError(
            f"Unable to reach standalone AI endpoint {url!r}: {exc}"
        ) from exc
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DiagnosticCaseGenerationError(
            f"Standalone AI endpoint {url!r} returned invalid JSON."
        ) from exc
    if not isinstance(loaded, Mapping):
        raise DiagnosticCaseGenerationError(
            f"Standalone AI endpoint {url!r} returned a non-object response."
        )
    return loaded


def _gpt_oss_text(response: Mapping[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = response.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        if chunks:
            return "\n".join(chunks)
    raise DiagnosticCaseGenerationError("GPT-OSS response did not contain text output.")


def _ollama_text(response: Mapping[str, Any]) -> str:
    text = response.get("response")
    if isinstance(text, str):
        return text
    raise DiagnosticCaseGenerationError("Ollama response did not contain a response string.")


def _extract_json_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise DiagnosticCaseGenerationError("Standalone AI returned empty text.")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise DiagnosticCaseGenerationError("Standalone AI did not return a JSON object.")
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DiagnosticCaseGenerationError("Standalone AI returned malformed JSON.") from exc
    if not isinstance(payload, Mapping):
        raise DiagnosticCaseGenerationError("Standalone AI JSON must be an object.")
    return payload


def validate_generated_cases(payload: Mapping[str, Any], *, expected_case_count: int | None = None) -> dict[str, Any]:
    """Validate generated case JSON and return a normalized dict."""

    try:
        return validate_case_payload(payload, expected_case_count=expected_case_count)
    except ValueError as exc:
        raise DiagnosticCaseGenerationError(str(exc)) from exc


def _gpt_oss_payload(*, model: str, prompt: str, temperature: float) -> dict[str, Any]:
    return {"model": model, "input": prompt, "temperature": temperature}


def _ollama_payload(*, model: str, prompt: str, temperature: float) -> dict[str, Any]:
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }


def _ollama_generate_url(endpoint: str) -> str:
    cleaned = endpoint.strip().rstrip("/") or DEFAULT_OLLAMA_ENDPOINT
    if cleaned.endswith("/api/generate"):
        return cleaned
    return f"{cleaned}/api/generate"


def generate_cases_with_engine(
    *,
    provider: str,
    endpoint: str,
    model: str,
    topic: str,
    case_count: int,
    temperature: float = 0.2,
    timeout_s: float = 120.0,
    post_json: HttpPostJson = _post_json,
) -> dict[str, Any]:
    """Generate and validate TeSciA diagnostic cases with a local AI endpoint."""

    provider_normalized = provider.strip().lower()
    if provider_normalized not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise DiagnosticCaseGenerationError(
            f"Unsupported standalone AI provider {provider!r}. Supported values: {supported}."
        )
    prompt = build_generation_prompt(topic=topic, case_count=case_count)
    if provider_normalized == "gpt-oss":
        url = endpoint.strip() or DEFAULT_GPT_OSS_ENDPOINT
        response = post_json(url, _gpt_oss_payload(model=model, prompt=prompt, temperature=temperature), timeout_s)
        text = _gpt_oss_text(response)
    else:
        url = _ollama_generate_url(endpoint)
        response = post_json(url, _ollama_payload(model=model, prompt=prompt, temperature=temperature), timeout_s)
        text = _ollama_text(response)
    return validate_generated_cases(
        _extract_json_object(text),
        expected_case_count=case_count,
    )


def generate_case_file(
    output_dir: Path | str,
    *,
    filename: str,
    provider: str,
    endpoint: str,
    model: str,
    topic: str,
    case_count: int,
    temperature: float,
    timeout_s: float,
    post_json: HttpPostJson = _post_json,
) -> Path:
    """Generate diagnostic cases and write them as a validated JSON file."""

    output_path = Path(output_dir) / filename
    payload = generate_cases_with_engine(
        provider=provider,
        endpoint=endpoint,
        model=model,
        topic=topic,
        case_count=case_count,
        temperature=temperature,
        timeout_s=timeout_s,
        post_json=post_json,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


__all__ = [
    "CASE_SCHEMA",
    "DEFAULT_GPT_OSS_ENDPOINT",
    "DEFAULT_GPT_OSS_MODEL",
    "DEFAULT_OLLAMA_ENDPOINT",
    "DEFAULT_OLLAMA_MODEL",
    "DiagnosticCaseGenerationError",
    "SUPPORTED_PROVIDERS",
    "build_generation_prompt",
    "generate_case_file",
    "generate_cases_with_engine",
    "validate_generated_cases",
]
