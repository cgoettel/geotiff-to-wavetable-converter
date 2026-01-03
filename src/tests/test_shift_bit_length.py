"""Tests for shift_bit_length function.

Verifies the utility function correctly finds the next greatest power of 2.
"""

from main import shift_bit_length


def test_shift_bit_length() -> None:
    assert shift_bit_length(2047) == 2048
    assert shift_bit_length(2048) == 2048
    assert shift_bit_length(2049) == 4096
