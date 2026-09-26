"""End-to-end tests for the GeoTIFF → `.wt` pipeline.

Each test writes a small synthetic GeoTIFF to `tmp_path`, drives the CLI
(in-process via `main()`, or as a real `python -m` subprocess), and checks the
resulting `.wt` file against the format spec:
https://github.com/surge-synthesizer/surge/blob/main/resources/data/wavetables/WT%20fileformat.txt

These prove the bytes on disk are structurally valid. Whether the result sounds
good (or loads in Bitwig) still needs human ears — see docs/manual-validation.md.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import rasterio
from rasterio.transform import from_origin

from geotiff_to_wavetable.cli import main

NODATA = -9999.0


@dataclass
class Wavetable:
    """A parsed `.wt` file."""

    wave_size: int
    wave_count: int
    flags: bytes
    samples: npt.NDArray[np.int16]


def write_geotiff(
    path: Path,
    bands: npt.NDArray[np.generic],
    nodata: float | None = NODATA,
) -> Path:
    """Write a georeferenced GeoTIFF from a (height, width) or (count, height, width) array."""
    if bands.ndim == 2:
        bands = bands[np.newaxis, ...]
    count, height, width = bands.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=count,
        dtype=bands.dtype,
        nodata=nodata,
        crs="EPSG:4326",
        transform=from_origin(0.0, float(height), 1.0, 1.0),
    ) as dataset:
        dataset.write(bands)
    return path


def gradient(height: int, width: int) -> npt.NDArray[np.float32]:
    """A left-to-right ramp with a sine ripple down the rows — non-constant in both axes."""
    x = np.linspace(0.0, 1000.0, width, dtype=np.float32)
    y = np.sin(np.linspace(0.0, 2 * np.pi, height, dtype=np.float32)) * 100
    ramp: npt.NDArray[np.float32] = (x[np.newaxis, :] + y[:, np.newaxis]).astype(np.float32)
    return ramp


def read_wt(path: Path) -> Wavetable:
    """Parse a `.wt` file, asserting the header and payload length are consistent."""
    raw = path.read_bytes()
    assert raw[:4] == b"vawt", "magic must be 'vawt'"
    wave_size = int.from_bytes(raw[4:8], "little")
    wave_count = int.from_bytes(raw[8:10], "little")
    flags = raw[10:12]
    payload = raw[12:]
    assert len(payload) == 2 * wave_size * wave_count, "int16 payload length must be 2 * wave_size * wave_count"
    return Wavetable(wave_size, wave_count, flags, np.frombuffer(payload, dtype="<i2"))


def run_cli(monkeypatch: pytest.MonkeyPatch, cwd: Path, *argv: str) -> None:
    """Invoke `main()` in-process with the given arguments from `cwd`.

    chdir keeps the CLI's `geotiff_to_wavetable.log` out of the repo root.
    """
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["geotiff-to-wavetable", *argv])
    main()


def assert_valid_wavetable(wavetable: Wavetable) -> None:
    """Structural checks every output must pass."""
    assert wavetable.wave_size & (wavetable.wave_size - 1) == 0, "wave size must be a power of 2"
    assert 2 <= wavetable.wave_size <= 4096
    assert 1 <= wavetable.wave_count <= 512
    assert wavetable.flags == bytes([12, 0])
    # Normalization maps the data's min and max onto the ends of the int16 range.
    assert wavetable.samples.min() == -32768
    assert wavetable.samples.max() == 32767


# --- Full pipeline -----------------------------------------------------------------------------


def test_python_m_round_trip(tmp_path: Path) -> None:
    """`python -m geotiff_to_wavetable` turns a real GeoTIFF into a valid `.wt` on disk."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(64, 300))
    output = tmp_path / "out.wt"

    result = subprocess.run(
        [sys.executable, "-m", "geotiff_to_wavetable", str(source), "-o", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    wavetable = read_wt(output)
    assert_valid_wavetable(wavetable)
    assert (wavetable.wave_size, wavetable.wave_count) == (512, 64)


@pytest.mark.parametrize(
    ("height", "width", "expected_count", "expected_size"),
    [
        (10, 100, 10, 128),  # width rounds up to the next power of 2
        (1, 3, 1, 4),  # smallest sensible raster
        (8, 256, 8, 256),  # already a power of 2 — unchanged
        (600, 5000, 512, 4096),  # both dimensions capped at the format maximums
    ],
)
def test_output_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    height: int,
    width: int,
    expected_count: int,
    expected_size: int,
) -> None:
    """Raster dimensions map onto legal wave size / wave count values."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(height, width))

    run_cli(monkeypatch, tmp_path, str(source), "-o", "out.wt")

    wavetable = read_wt(tmp_path / "out.wt")
    assert_valid_wavetable(wavetable)
    assert (wavetable.wave_size, wavetable.wave_count) == (expected_size, expected_count)


def test_int16_source_raster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integer rasters (SRTM ships int16 with a -32768 sentinel) convert cleanly."""
    elevation = gradient(32, 64).astype(np.int16)
    elevation[0, :8] = -32768
    source = write_geotiff(tmp_path / "srtm.tif", elevation, nodata=-32768)

    run_cli(monkeypatch, tmp_path, str(source), "-o", "out.wt")

    assert_valid_wavetable(read_wt(tmp_path / "out.wt"))


# --- CLI options -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_input",
    [
        "terrain.tif",
        "./terrain.tif",  # leading dot
        "v1.2/terrain.tif",  # dotted directory
        "terrain.v2.tif",  # dotted stem keeps everything but the last suffix
    ],
)
def test_default_output_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_input: str) -> None:
    """Without -o, the `.wt` lands next to the input with only the extension swapped."""
    source = tmp_path / relative_input
    source.parent.mkdir(parents=True, exist_ok=True)
    write_geotiff(source, gradient(8, 16))

    run_cli(monkeypatch, tmp_path, relative_input)

    expected = source.with_suffix(".wt")
    assert expected.exists(), f"expected {expected}; directory has {sorted(p.name for p in source.parent.iterdir())}"
    assert_valid_wavetable(read_wt(expected))


def test_info_prints_metadata_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """-i prints band count and dimensions, exits 0, and skips conversion."""
    source = write_geotiff(tmp_path / "terrain.tif", np.stack([gradient(20, 30)] * 3))

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-i")

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.splitlines() == ["Bands: 3", "Width: 30", "Height: 20"]
    assert not list(tmp_path.glob("*.wt"))


def test_visualize_shows_plot_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-v hands the dataset to rasterio's plotter, exits 0, and skips conversion."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(8, 16))
    shown: list[object] = []
    monkeypatch.setattr("rasterio.plot.show", shown.append)

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-v")

    assert exc_info.value.code == 0
    assert len(shown) == 1
    assert not list(tmp_path.glob("*.wt"))


@pytest.mark.parametrize(
    ("band_count", "requested", "message"),
    [
        (1, "2", "only contains 1 band."),
        (3, "5", "only contains 3 bands."),
    ],
)
def test_out_of_range_band_exits_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, band_count: int, requested: str, message: str
) -> None:
    """-b beyond the band count exits non-zero with a singular/plural-correct message."""
    source = write_geotiff(tmp_path / "terrain.tif", np.stack([gradient(8, 16)] * band_count))

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-b", requested)

    assert isinstance(exc_info.value.code, str)
    assert exc_info.value.code.endswith(message)
    assert not list(tmp_path.glob("*.wt"))


def test_band_option_selects_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-b 2 converts the second band, not the first.

    Band 2 is band 1 inverted, so its normalized output is the mirror image.
    """
    ramp = gradient(4, 16)
    source = write_geotiff(tmp_path / "terrain.tif", np.stack([ramp, -ramp]))

    run_cli(monkeypatch, tmp_path, str(source), "-o", "band1.wt")
    run_cli(monkeypatch, tmp_path, str(source), "-b", "2", "-o", "band2.wt")

    band1 = read_wt(tmp_path / "band1.wt").samples.astype(np.int32)
    band2 = read_wt(tmp_path / "band2.wt").samples.astype(np.int32)
    assert not np.array_equal(band1, band2)
    np.testing.assert_allclose(band1 + band2, -1, atol=2)


# --- Nodata handling ---------------------------------------------------------------------------


def with_valid_fraction(valid_percent: int) -> npt.NDArray[np.float32]:
    """A 10x10 gradient where only the first `valid_percent` pixels hold real data."""
    data = gradient(10, 10)
    data.ravel()[valid_percent:] = NODATA
    return data


@pytest.mark.parametrize(
    ("valid_percent", "expected_level"),
    [
        (70, None),  # plenty of data — no complaint
        (30, logging.WARNING),  # under 50% valid
        (5, logging.ERROR),  # under 10% valid
    ],
)
def test_sparse_data_is_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    valid_percent: int,
    expected_level: int | None,
) -> None:
    """Mostly-nodata rasters still convert, but warn at <50% valid and error at <10%."""
    source = write_geotiff(tmp_path / "sparse.tif", with_valid_fraction(valid_percent))

    run_cli(monkeypatch, tmp_path, str(source), "-o", "out.wt")

    complaints = [record.levelno for record in caplog.records if "valid data" in record.getMessage()]
    assert complaints == ([] if expected_level is None else [expected_level])
    assert_valid_wavetable(read_wt(tmp_path / "out.wt"))


def test_all_nodata_exits_with_error(tmp_path: Path) -> None:
    """A band with no valid pixels exits non-zero with a readable message, not a traceback."""
    source = write_geotiff(tmp_path / "empty.tif", np.full((8, 16), NODATA, dtype=np.float32))

    result = subprocess.run(
        [sys.executable, "-m", "geotiff_to_wavetable", str(source), "-o", "out.wt"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "only nodata/NaN values" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "out.wt").exists()


@pytest.mark.parametrize(
    "flat",
    [
        np.full((8, 16), 350.0, dtype=np.float32),  # a lakebed: one elevation everywhere
        np.where(np.eye(8, 16, dtype=bool), NODATA, 350.0).astype(np.float32),  # flat once nodata is mean-filled
    ],
    ids=["constant", "constant-with-nodata"],
)
def test_flat_raster_exits_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flat: npt.NDArray[np.float32]
) -> None:
    """A flat band would normalize to silence, so the CLI refuses instead of writing it."""
    source = write_geotiff(tmp_path / "flat.tif", flat)

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-o", "out.wt")

    assert isinstance(exc_info.value.code, str)
    assert exc_info.value.code.startswith("ERROR: The selected band is flat")
    assert not (tmp_path / "out.wt").exists()
