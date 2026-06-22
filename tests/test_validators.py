"""Tests for validator functions.

Verifies wave size validation according to .wt format requirements (powers of 2
between 2 and 4096), and band-range validation against a dataset's band count.
"""

from unittest.mock import MagicMock

import pytest

from geotiff_to_wavetable import is_band_in_band, validate_wave_size


def test_validate_wave_size_valid() -> None:
    assert validate_wave_size(2048)


def test_validate_wave_size_invalid_not_power_of_2() -> None:
    assert not validate_wave_size(2047)


def test_validate_wave_size_invalid_less_than_2() -> None:
    assert not validate_wave_size(1)


def test_validate_wave_size_invalid_greater_than_4096() -> None:
    assert not validate_wave_size(8192)


# --- is_band_in_band ---------------------------------------------------------


def test_is_band_in_band_within_range_returns_none() -> None:
    dataset = MagicMock()
    dataset.count = 3
    # A band within range returns normally (no SystemExit raised).
    is_band_in_band(dataset, user_specified_band=2)


def test_is_band_in_band_exceeds_count_exits_with_singular_band() -> None:
    dataset = MagicMock()
    dataset.count = 1
    with pytest.raises(SystemExit) as exc_info:
        is_band_in_band(dataset, user_specified_band=5)
    message = str(exc_info.value)
    assert "1 band." in message
    assert "1 bands" not in message


def test_is_band_in_band_exceeds_count_exits_with_plural_bands() -> None:
    dataset = MagicMock()
    dataset.count = 3
    with pytest.raises(SystemExit) as exc_info:
        is_band_in_band(dataset, user_specified_band=5)
    assert "3 bands" in str(exc_info.value)
