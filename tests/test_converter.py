"""Tests for converter.py functions.

Verifies that height is correctly capped at 512 for wavetable format requirements.

Verifies that width is correctly calculated as the next power of 2, capped at 4096.

Verifies helper extraction behavior (_clean_nodata, _normalize_to_int16) and the
array_to_wavetable public API contract.
"""

import logging

import numpy as np
import pytest

from geotiff_to_wavetable.converter import (
    _clean_nodata,
    _normalize_to_int16,
    array_to_wavetable,
    calculate_height,
    calculate_width,
    shift_bit_length,
)

LOGGER_NAME = "geotiff_to_wavetable.converter"


def test_calculate_height_less_than_512() -> None:
    assert calculate_height(100) == 100


def test_calculate_height_equal_to_512() -> None:
    assert calculate_height(512) == 512


def test_calculate_height_greater_than_512() -> None:
    assert calculate_height(1000) == 512


def test_calculate_width_less_than_4096() -> None:
    assert calculate_width(1000) == 1024


def test_calculate_width_equal_to_4096() -> None:
    assert calculate_width(4096) == 4096


def test_calculate_width_greater_than_4096() -> None:
    assert calculate_width(5000) == 4096


def test_shift_bit_length_below_power_of_2() -> None:
    assert shift_bit_length(2047) == 2048


def test_shift_bit_length_exact_power_of_2() -> None:
    assert shift_bit_length(2048) == 2048


def test_shift_bit_length_above_power_of_2() -> None:
    assert shift_bit_length(2049) == 4096


# --- _clean_nodata -----------------------------------------------------------


def test_clean_nodata_none_returns_array_unchanged() -> None:
    bands = np.array([[1.0, 2.0], [3.0, 4.0]])
    original = bands.copy()
    cleaned, valid_pct = _clean_nodata(bands, nodata_value=None)
    assert valid_pct == 100.0
    np.testing.assert_array_equal(cleaned, original)


def test_clean_nodata_all_nodata_raises() -> None:
    bands = np.full((4, 4), -9999.0)
    with pytest.raises(ValueError, match="only nodata"):
        _clean_nodata(bands, nodata_value=-9999.0)


def test_clean_nodata_partial_replaces_with_mean() -> None:
    bands = np.array(
        [
            [1.0, 2.0, -9999.0, -9999.0],
            [3.0, 4.0, -9999.0, -9999.0],
        ]
    )
    expected_mean = (1.0 + 2.0 + 3.0 + 4.0) / 4
    cleaned, valid_pct = _clean_nodata(bands, nodata_value=-9999.0)
    assert valid_pct == 50.0
    assert cleaned[0, 0] == 1.0
    assert cleaned[0, 2] == expected_mean
    assert cleaned[1, 3] == expected_mean


def test_clean_nodata_replaces_nan_alongside_sentinel() -> None:
    bands = np.array([[1.0, 2.0], [np.nan, 4.0]])
    cleaned, valid_pct = _clean_nodata(bands, nodata_value=-9999.0)
    assert not np.isnan(cleaned).any()
    assert valid_pct == 75.0


def test_clean_nodata_warns_between_10_and_50_percent(caplog: pytest.LogCaptureFixture) -> None:
    # 2 valid of 10 cells = 20% — below 50% but above 10%.
    bands = np.array(
        [
            [1.0, -9999.0, -9999.0, -9999.0, -9999.0],
            [2.0, -9999.0, -9999.0, -9999.0, -9999.0],
        ]
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _clean_nodata(bands, nodata_value=-9999.0)
    levels = {r.levelname for r in caplog.records if r.name == LOGGER_NAME}
    assert "WARNING" in levels
    assert "ERROR" not in levels


def test_clean_nodata_errors_below_10_percent(caplog: pytest.LogCaptureFixture) -> None:
    # 1 valid of 20 cells = 5%.
    bands = np.full((4, 5), -9999.0)
    bands[0, 0] = 1.0
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _clean_nodata(bands, nodata_value=-9999.0)
    errors = [r for r in caplog.records if r.name == LOGGER_NAME and r.levelname == "ERROR"]
    assert errors, "expected an ERROR log entry for severely sparse data"
    assert any("unusable" in r.message for r in errors)


# --- _normalize_to_int16 -----------------------------------------------------


def test_normalize_to_int16_spans_full_range() -> None:
    bands = np.array([[0.0, 1.0], [2.0, 3.0]])
    result = _normalize_to_int16(bands)
    assert result.dtype == np.int16
    assert result.min() == -32768
    assert result.max() == 32767


def test_normalize_to_int16_preserves_shape() -> None:
    bands = np.random.rand(64, 128).astype(np.float64)
    result = _normalize_to_int16(bands)
    assert result.shape == (64, 128)
    assert result.dtype == np.int16


# --- array_to_wavetable (1.0.0 public API contract) --------------------------


def test_array_to_wavetable_structural_contract() -> None:
    """Given any 2D array, the output satisfies the .wt byte layout."""
    array = np.random.rand(100, 300).astype(np.float64)
    samples, wave_size, wave_count = array_to_wavetable(array)

    assert isinstance(samples, list)
    assert len(samples) == 1
    assert isinstance(samples[0], bytes)

    # wave_size must be a power of 2 in [2, 4096]
    assert wave_size & (wave_size - 1) == 0
    assert 2 <= wave_size <= 4096
    # wave_count must be in [1, 512]
    assert 1 <= wave_count <= 512
    # int16 serialization = 2 bytes per sample
    assert len(samples[0]) == 2 * wave_size * wave_count


def test_array_to_wavetable_caps_oversize_dimensions() -> None:
    array = np.random.rand(1000, 5000).astype(np.float64)
    _, wave_size, wave_count = array_to_wavetable(array)
    assert wave_size == 4096
    assert wave_count == 512


def test_array_to_wavetable_runs_cleaning_when_nodata_given() -> None:
    """Nodata values must not leak through into the wavetable byte layout."""
    # 50% nodata; mix of real values.
    row = [1.0, -9999.0, 2.0, -9999.0]
    array = np.array([row] * 10, dtype=np.float64)
    samples, wave_size, wave_count = array_to_wavetable(array, nodata=-9999.0)
    assert len(samples[0]) == 2 * wave_size * wave_count
