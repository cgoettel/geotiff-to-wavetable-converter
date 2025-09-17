from main import validate_wave_size


def test_validate_wave_size_valid():
    assert validate_wave_size(2048) == True


def test_validate_wave_size_invalid_not_power_of_2():
    assert validate_wave_size(2047) == False


def test_validate_wave_size_invalid_less_than_2():
    assert validate_wave_size(1) == False


def test_validate_wave_size_invalid_greater_than_4096():
    assert validate_wave_size(8192) == False
