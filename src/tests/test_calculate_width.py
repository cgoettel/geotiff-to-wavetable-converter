from main import calculate_width


def test_calculate_width_less_than_4096():
    assert calculate_width(1000) == 1024


def test_calculate_width_equal_to_4096():
    assert calculate_width(4096) == 4096


def test_calculate_width_greater_than_4096():
    assert calculate_width(5000) == 4096
