from __future__ import annotations

from src.business_rules.compensation_rules import out_of_band_offer


def test_offer_bands() -> None:
    assert out_of_band_offer(180000, 100000, 150000) is True
    assert out_of_band_offer(130000, 100000, 150000) is False
