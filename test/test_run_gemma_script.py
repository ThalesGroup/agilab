import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "run-gemma.py"


def _load_run_gemma_module():
    spec = importlib.util.spec_from_file_location("run_gemma_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_gemma_uses_multimodal_mlx_vlm_loader():
    source = SCRIPT.read_text()

    assert "mlx_vlm" in source
    assert "mlx_lm" not in source
    assert "mlx-community/gemma-4-e4b-it-4bit" in source
    assert "uv run --script run-gemma.py" in source


def test_run_gemma_prompt_uses_vlm_chat_template():
    module = _load_run_gemma_module()
    calls = []

    def apply_chat_template(processor, config, messages, add_generation_prompt):
        calls.append((processor, config, messages, add_generation_prompt))
        return "rendered prompt"

    prompt = module._build_prompt(
        "processor",
        {"model_type": "gemma4"},
        apply_chat_template,
    )

    assert prompt == "rendered prompt"
    assert calls == [
        (
            "processor",
            {"model_type": "gemma4"},
            [{"role": "user", "content": module.PROMPT}],
            True,
        )
    ]
