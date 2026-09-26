"""Tests for the output writers in io_utils.py and the CLI's output-path rules."""

import wave
from pathlib import Path

import numpy as np
import pytest

from geotiff_to_wavetable.cli import formats_argument, output_paths
from geotiff_to_wavetable.io_utils import write_wav_file


def test_write_wav_file_round_trips_frames(tmp_path: Path) -> None:
    """Frames go into the WAV unchanged, in order, at the requested rate."""
    frames = np.arange(-8, 8, dtype="<i2")
    path = tmp_path / "table.wav"

    write_wav_file(
        str(path), [frames[:8].tobytes(), frames[8:].tobytes()], wave_size=4, wave_count=4, sample_rate=48000
    )

    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 48000, 16)
        np.testing.assert_array_equal(np.frombuffer(wav.readframes(16), dtype="<i2"), frames)


def test_write_wav_file_rejects_mismatched_dimensions(tmp_path: Path) -> None:
    """Frames that don't match wave_size x wave_count mean a bug upstream, so nothing is written."""
    path = tmp_path / "table.wav"
    with pytest.raises(ValueError, match="Expected 32 bytes"):
        write_wav_file(str(path), [np.zeros(8, dtype="<i2").tobytes()], wave_size=4, wave_count=4)
    assert not path.exists()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("wt", ("wt",)), ("wav", ("wav",)), ("WAV, wt", ("wav", "wt")), ("wt,wt,wav", ("wt", "wav"))],
)
def test_formats_argument_normalizes(value: str, expected: tuple[str, ...]) -> None:
    assert formats_argument(value) == expected


@pytest.mark.parametrize(
    ("output_file", "formats", "expected"),
    [
        (None, ("wt",), {"wt": "maps/v1.2/dem.wt"}),
        (None, ("wt", "wav"), {"wt": "maps/v1.2/dem.wt", "wav": "maps/v1.2/dem.wav"}),
        ("out.bin", ("wav",), {"wav": "out.bin"}),  # one format: -o is taken literally
        ("out.wav", ("wt", "wav"), {"wt": "out.wt", "wav": "out.wav"}),
        ("out", ("wt", "wav"), {"wt": "out.wt", "wav": "out.wav"}),
    ],
)
def test_output_paths(output_file: str | None, formats: tuple[str, ...], expected: dict[str, str]) -> None:
    assert output_paths("maps/v1.2/dem.tif", output_file, formats) == expected
