from __future__ import annotations

from pathlib import Path


README = Path("README.md")
PUBLIC_DOC_PAGES = (
    Path("docs/source/demos.rst"),
    Path("docs/source/quick-start.rst"),
)
ADOPTION_DOC_PAGES = (
    Path("docs/source/index.rst"),
    Path("docs/source/newcomer-guide.rst"),
)
PUBLIC_HF_SPACE_URL = "https://huggingface.co/spaces/jpmorard/agilab"
HF_RUNTIME_URL = "https://jpmorard-agilab.hf.space"


def test_readme_advertises_public_huggingface_space_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert PUBLIC_HF_SPACE_URL in readme
    assert "AGILAB-demo" in readme
    assert "self-serve public Hugging Face Spaces demo" in readme


def test_readme_links_to_hf_space_page_not_runtime_host() -> None:
    readme = README.read_text(encoding="utf-8")

    assert HF_RUNTIME_URL not in readme


def test_public_docs_link_to_hf_space_page_not_runtime_host() -> None:
    for path in PUBLIC_DOC_PAGES:
        text = path.read_text(encoding="utf-8")
        assert PUBLIC_HF_SPACE_URL in text
        assert HF_RUNTIME_URL not in text


def test_readme_exposes_three_clear_adoption_routes() -> None:
    readme = README.read_text(encoding="utf-8")

    for phrase in ("See the UI now", "Prove it locally", "Use the API/notebook"):
        assert phrase in readme
    assert "Target: pass the first proof in 10 minutes" in readme
    assert "tools/newcomer_first_proof.py --json" in readme


def test_public_docs_expose_three_clear_adoption_routes() -> None:
    for path in ADOPTION_DOC_PAGES:
        text = path.read_text(encoding="utf-8")
        for phrase in ("See the UI now", "Prove it locally", "Use the API/notebook"):
            assert phrase in text
        assert "10 minutes" in text
