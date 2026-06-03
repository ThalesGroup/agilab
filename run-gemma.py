#!/usr/bin/env python3

# /// script
# dependencies = [
#   "mlx",
#   "mlx-vlm>=0.5.0",
# ]
# ///

import os
import sys
import warnings

MODEL = "mlx-community/gemma-4-e4b-it-4bit"
PROMPT = "Say hello and explain in one sentence that you are running locally with MLX."
MAX_TOKENS = int(os.environ.get("AGILAB_GEMMA_MAX_TOKENS", "2048"))

warnings.filterwarnings(
    "ignore",
    message="At least one mel filter has all zero values.*",
    category=UserWarning,
    module="transformers.audio_utils",
)


def _load_backend():
    try:
        from mlx_vlm import apply_chat_template, load, stream_generate
    except ModuleNotFoundError as exc:
        if exc.name != "mlx_vlm":
            raise
        raise RuntimeError(
            "This Gemma 4 checkpoint is multimodal and requires mlx-vlm.\n"
            "Run one of:\n"
            "  uv run --script run-gemma.py\n"
            "  uv run --with mlx-vlm python run-gemma.py\n"
            "  uv run --extra local-llm python run-gemma.py"
        ) from exc
    return load, stream_generate, apply_chat_template


def _build_prompt(processor, model_config, apply_chat_template):
    messages = [{"role": "user", "content": PROMPT}]
    return apply_chat_template(
        processor,
        model_config,
        messages,
        add_generation_prompt=True,
    )


def main():
    print(f"Loading model: {MODEL}", flush=True)
    print("First run can take time because the model must be downloaded.", flush=True)

    load, stream_generate, apply_chat_template = _load_backend()
    model, processor = load(MODEL)

    print("Model loaded.", flush=True)
    print("Generating:\n", flush=True)

    prompt = _build_prompt(processor, getattr(model, "config", {}), apply_chat_template)

    for response in stream_generate(
        model,
        processor,
        prompt=prompt,
        max_tokens=MAX_TOKENS,
    ):
        print(getattr(response, "text", response), end="", flush=True)

    print("\n\nDone.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        sys.exit(130)
