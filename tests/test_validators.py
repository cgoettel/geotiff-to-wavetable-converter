"""Tests for validate_wave_size function.

Verifies wave size validation according to .wt format requirements:
wave sizes must be powers of 2 between 2 and 4096 inclusive.
"""

from geotiff_to_wavetable import validate_wave_size


def test_validate_wave_size_valid() -> None:
    assert validate_wave_size(2048)


def test_validate_wave_size_invalid_not_power_of_2() -> None:
    assert not validate_wave_size(2047)


def test_validate_wave_size_invalid_less_than_2() -> None:
    assert not validate_wave_size(1)


def test_validate_wave_size_invalid_greater_than_4096() -> None:
    assert not validate_wave_size(8192)
