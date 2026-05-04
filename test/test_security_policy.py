from pathlib import Path


def test_security_policy_uses_private_vulnerability_intake() -> None:
    text = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "Do **not** open a public GitHub issue" in text
    assert "GitHub private vulnerability reporting" in text
    assert "Open a GitHub issue with the title" not in text
    assert "Share reproduction steps, proof-of-concept material" in text
