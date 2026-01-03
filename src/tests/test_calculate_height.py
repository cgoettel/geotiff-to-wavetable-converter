"""Tests for calculate_height function.

Verifies that height is correctly capped at 512 for wavetable format requirements.
"""

from main import calculate_height


def test_calculate_height_less_than_512() -> None:
    assert calculate_height(100) == 100


def test_calculate_height_equal_to_512() -> None:
    assert calculate_height(512) == 512


def test_calculate_height_greater_than_512() -> None:
    assert calculate_height(1000) == 512
