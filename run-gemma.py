#!/usr/bin/env python3

# /// script
# dependencies = [
#   "mlx",
#   "mlx-lm",
#   "mlx-vlm",
# ]
# ///

import sys
from mlx_lm import load, stream_generate

MODEL = "mlx-community/gemma-4-e4b-it-4bit"
PROMPT = "Say hello and explain in one sentence that you are running locally with MLX."


def main():
    print(f"Loading model: {MODEL}", flush=True)
    print("First run can take time because the model must be downloaded.", flush=True)

    model, tokenizer = load(MODEL)

    print("Model loaded.", flush=True)
    print("Generating:\n", flush=True)

    messages = [
        {"role": "user", "content": PROMPT}
    ]

    if getattr(tokenizer, "chat_template", None):
        prompt = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
        )
    else:
        prompt = PROMPT

    for response in stream_generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=2048,
    ):
        print(response.text, end="", flush=True)

    print("\n\nDone.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        sys.exit(130)
