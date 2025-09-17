from main import shift_bit_length


def test_shift_bit_length():
    assert shift_bit_length(2047) == 2048
    assert shift_bit_length(2048) == 2048
    assert shift_bit_length(2049) == 4096
