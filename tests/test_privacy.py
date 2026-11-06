import json
from pathlib import Path

import pytest

from trialmatch.agents import IntakePIIGuardAgent
from trialmatch.privacy import contains_unmasked_common_pii, redact_pii

ROOT = Path(__file__).resolve().parents[1]
SECURITY = json.loads((ROOT / "data/security_tests.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", SECURITY["pii"])
def test_synthetic_pii_is_masked_before_processing(case: dict[str, str]) -> None:
    result = redact_pii(case["text"])
    assert result.pii_types
    assert "[REDACTED]" in result.text
    assert not contains_unmasked_common_pii(result.text)
    assert case["text"] not in result.text


def test_intake_guard_returns_only_sanitized_text() -> None:
    text, pii_types = IntakePIIGuardAgent().run("Hasta: Ayşe Yılmaz, TC 11111111111.")
    assert pii_types
    assert "Ayşe Yılmaz" not in text
    assert "11111111111" not in text
