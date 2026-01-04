"""Tests for converter.py functions.

Verifies that height is correctly capped at 512 for wavetable format requirements.

Verifies that width is correctly calculated as the next power of 2, capped at 4096.
"""

from geotiff_to_wavetable.converter import calculate_height, calculate_width, shift_bit_length


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
