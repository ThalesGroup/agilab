from pathlib import Path


def test_security_policy_uses_private_vulnerability_intake() -> None:
    text = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "Do **not** open a public GitHub issue" in text
    assert "Preferred channel: use GitHub Private Vulnerability Reporting" in text
    assert "Do not include exploit code, secrets" in text
    assert "Public GitHub issues are only for non-sensitive post-fix advisories" in text
    assert "private GitHub Security Advisory" in text
    assert "Open a GitHub issue with the title" not in text
    assert "[SECURITY]" not in text
    assert "Share reproduction steps, proof-of-concept material" in text
