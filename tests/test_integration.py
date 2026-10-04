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
import warnings
import wave
from dataclasses import dataclass
from pathlib import Path

import laspy
import numpy as np
import numpy.typing as npt
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
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

    chdir makes relative paths (inputs, -o) resolve inside the test's directory.
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
    assert capsys.readouterr().out.splitlines() == [
        "Bands: 3 (gray, undefined, undefined)",
        "Width: 30",
        "Height: 20",
    ]
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


# --- Images and scans --------------------------------------------------------------------------


def write_image(
    path: Path,
    bands: npt.NDArray[np.uint8],
    colormap: dict[int, tuple[int, int, int, int]] | None = None,
) -> Path:
    """Write a plain, non-georeferenced image (PNG or JPEG), like a phone photo or a scanner's output."""
    count, height, width = bands.shape
    driver = "JPEG" if path.suffix == ".jpg" else "PNG"
    # No georeferencing is the point here, so rasterio's warning about it is expected.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        image = rasterio.open(path, "w", driver=driver, width=width, height=height, count=count, dtype="uint8")
    with image:
        image.write(bands)
        if colormap is not None:
            image.write_colormap(1, colormap)
    return path


def poster(height: int = 24, width: int = 40) -> npt.NDArray[np.uint8]:
    """Blue ink on white paper: red is 255 everywhere, so the red channel alone is flat.

    Green and blue dip together where the ink is, in a pattern that varies across
    both axes.
    """
    rows, cols = np.mgrid[0:height, 0:width]
    ink = ((np.sin(cols / 3.0) + np.cos(rows / 4.0)) > 0.5).astype(np.float64) * (cols + rows) / (width + height)
    red = np.full((height, width), 255.0)
    green = 255.0 - 200.0 * ink
    blue = 255.0 - 60.0 * ink
    return np.stack([red, green, blue]).astype(np.uint8)


def luma(rgb: npt.NDArray[np.generic]) -> npt.NDArray[np.float64]:
    """Rec. 709 luma, computed independently of the loader."""
    red, green, blue = (channel.astype(np.float64) for channel in rgb[:3])
    result: npt.NDArray[np.float64] = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return result


def convert(monkeypatch: pytest.MonkeyPatch, cwd: Path, source: Path, *options: str) -> npt.NDArray[np.int32]:
    """Run the CLI on `source` and return the output samples (int32, so they can be subtracted)."""
    output = cwd / f"{source.stem}{''.join(options)}.wt"
    run_cli(monkeypatch, cwd, str(source), "-o", str(output), *options)
    wavetable = read_wt(output)
    assert_valid_wavetable(wavetable)
    return wavetable.samples.astype(np.int32)


def test_color_image_defaults_to_brightness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without -b, a color image converts by brightness rather than its (here flat) red channel."""
    image = poster()
    source = write_image(tmp_path / "poster.png", image)
    reference = write_geotiff(tmp_path / "luma.tif", luma(image).astype(np.float32), nodata=None)

    # float32 vs float64 luma can land a sample on either side of an int16 boundary.
    np.testing.assert_allclose(
        convert(monkeypatch, tmp_path, source), convert(monkeypatch, tmp_path, reference), atol=1
    )


def test_band_option_picks_one_color_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-b 2 on a color image is its green channel alone; -b 1 here is flat red and refuses."""
    image = poster()
    source = write_image(tmp_path / "poster.png", image)
    green = write_geotiff(tmp_path / "green.tif", image[1], nodata=None)

    np.testing.assert_array_equal(
        convert(monkeypatch, tmp_path, source, "-b", "2"), convert(monkeypatch, tmp_path, green)
    )
    with pytest.raises(SystemExit, match="flat"):
        run_cli(monkeypatch, tmp_path, str(source), "-b", "1")


def test_alpha_channel_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An RGBA image converts exactly like the same image without alpha."""
    image = poster()
    alpha = np.linspace(0, 255, image[0].size).reshape(image[0].shape).astype(np.uint8)
    rgba = write_image(tmp_path / "rgba.png", np.concatenate([image, alpha[np.newaxis]]))
    rgb = write_image(tmp_path / "rgb.png", image)

    np.testing.assert_array_equal(convert(monkeypatch, tmp_path, rgba), convert(monkeypatch, tmp_path, rgb))


def test_palette_image_uses_colors_not_indices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Palette images (GIFs, indexed PNGs) convert by the colors their indices point to.

    The palette is deliberately out of brightness order, so reading raw indices
    would give a different wavetable.
    """
    palette = {0: (255, 255, 255, 255), 1: (0, 0, 0, 255), 2: (128, 128, 128, 255), 3: (40, 200, 90, 255)}
    rows, cols = np.mgrid[0:16, 0:32]
    indices = ((rows // 3 + cols // 5) % 4).astype(np.uint8)
    source = write_image(tmp_path / "indexed.png", indices[np.newaxis], colormap=palette)
    colors = np.array([palette[i][:3] for i in range(4)], dtype=np.float64)[indices]
    reference = write_geotiff(tmp_path / "colors.tif", luma(np.moveaxis(colors, -1, 0)).astype(np.float32), nodata=None)

    np.testing.assert_allclose(
        convert(monkeypatch, tmp_path, source), convert(monkeypatch, tmp_path, reference), atol=1
    )


def test_columns_option_reads_left_to_right(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--columns makes each column a wave frame: identical to converting the transposed image."""
    data = gradient(24, 40)
    source = write_geotiff(tmp_path / "terrain.tif", data)
    transposed = write_geotiff(tmp_path / "transposed.tif", np.ascontiguousarray(data.T))

    by_columns = convert(monkeypatch, tmp_path, source, "--columns")
    np.testing.assert_array_equal(by_columns, convert(monkeypatch, tmp_path, transposed))
    wavetable = read_wt(tmp_path / "terrain--columns.wt")
    assert (wavetable.wave_size, wavetable.wave_count) == (32, 40)


def test_blank_scan_exits_with_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan of a blank white wall has nothing to hear, so it gets the flat-band error."""
    source = write_image(tmp_path / "wall.png", np.full((3, 16, 16), 255, dtype=np.uint8))

    with pytest.raises(SystemExit, match="flat"):
        run_cli(monkeypatch, tmp_path, str(source))


def test_info_on_photo_names_color_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """-i shows which band is which color, so -b 1/2/3 is discoverable."""
    source = write_image(tmp_path / "poster.png", poster())

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, tmp_path, str(source), "-i")

    assert capsys.readouterr().out.splitlines()[0] == "Bands: 3 (red, green, blue)"


def test_jpeg_photo_converts_quietly(tmp_path: Path) -> None:
    """A JPEG photo converts end to end, with no georeferencing warning on the console."""
    source = write_image(tmp_path / "photo.jpg", poster(48, 64))

    result = subprocess.run(
        [sys.executable, "-m", "geotiff_to_wavetable", str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert_valid_wavetable(read_wt(tmp_path / "photo.wt"))


# --- Wave size ---------------------------------------------------------------------------------


@pytest.mark.parametrize("wave_size", ["2", "256", "4096"])
def test_wave_size_option_sets_frame_length(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wave_size: str) -> None:
    """-w sets samples per frame regardless of raster width; frame count still follows height."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(24, 300))

    run_cli(monkeypatch, tmp_path, str(source), "-w", wave_size, "-o", "out.wt")

    wavetable = read_wt(tmp_path / "out.wt")
    assert_valid_wavetable(wavetable)
    assert (wavetable.wave_size, wavetable.wave_count) == (int(wave_size), 24)


@pytest.mark.parametrize("wave_size", ["0", "3", "5000", "big"])
def test_invalid_wave_size_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wave_size: str
) -> None:
    """A bad -w fails in argparse (exit 2, usage message) before any file is read or written."""
    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, "does-not-exist.tif", "-w", wave_size)

    assert exc_info.value.code == 2
    assert "-w/--wave-size" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.wt"))


# --- WAV output for hardware samplers ----------------------------------------------------------


def read_wav(path: Path) -> tuple[int, int, int, npt.NDArray[np.int16]]:
    """Return (channels, sample width in bytes, sample rate, samples) from a WAV file."""
    with wave.open(str(path), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        return wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), samples


def test_wav_format_writes_sampler_ready_wav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-f wav writes a mono 16-bit 44.1 kHz WAV next to the input, lasting wave_size x wave_count samples."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(24, 300))

    run_cli(monkeypatch, tmp_path, str(source), "-f", "wav")

    channels, width, rate, samples = read_wav(tmp_path / "terrain.wav")
    assert (channels, width, rate) == (1, 2, 44100)
    assert samples.size == 512 * 24
    assert samples.min() == -32768
    assert samples.max() == 32767
    assert not (tmp_path / "terrain.wt").exists()


def test_wav_samples_match_wt_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-f wt,wav -o out.wav writes out.wt and out.wav holding sample-for-sample the same table."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(16, 64))

    run_cli(monkeypatch, tmp_path, str(source), "-f", "wt,wav", "-o", "out.wav")

    wavetable = read_wt(tmp_path / "out.wt")
    _, _, _, samples = read_wav(tmp_path / "out.wav")
    np.testing.assert_array_equal(samples, wavetable.samples)


def test_wav_respects_wave_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-w changes the WAV's frame length, and so its duration, just like the .wt."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(10, 300))

    run_cli(monkeypatch, tmp_path, str(source), "-f", "wav", "-w", "32", "-o", "crunch.wav")

    _, _, _, samples = read_wav(tmp_path / "crunch.wav")
    assert samples.size == 32 * 10


@pytest.mark.parametrize("formats", ["mp3", "wt,flac", ",", ""])
def test_unknown_format_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], formats: str
) -> None:
    """A bad -f fails in argparse (exit 2) before anything is read or written."""
    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, "does-not-exist.tif", "-f", formats)

    assert exc_info.value.code == 2
    assert "-f/--format" in capsys.readouterr().err


# --- LiDAR point clouds ------------------------------------------------------------------------


def write_point_cloud(path: Path, classification: int = 2) -> Path:
    """Write a 40x40 lattice of points (a tilted plane with a ripple) as a LAS or LAZ, by suffix."""
    lattice = np.arange(40, dtype=np.float64)
    x, y = np.meshgrid(lattice, lattice)
    points = laspy.LasData(laspy.LasHeader(point_format=6, version="1.4"))
    points.header.scales = np.array([0.01, 0.01, 0.01])
    points.x = x.ravel()
    points.y = y.ravel()
    points.z = (x + 5 * np.sin(y / 4)).ravel()
    points.classification = np.full(x.size, classification, dtype=np.uint8)
    points.write(path)
    return path


@pytest.mark.parametrize("suffix", [".las", ".laz", ".LAZ"])
def test_point_cloud_converts_to_wavetable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str) -> None:
    """A LAS/LAZ input is gridded and converted: 40 points across at 3x spacing is a 14x14 grid."""
    source = write_point_cloud(tmp_path / f"terrain{suffix}")

    run_cli(monkeypatch, tmp_path, str(source))

    wavetable = read_wt(source.with_suffix(".wt"))
    assert_valid_wavetable(wavetable)
    assert (wavetable.wave_size, wavetable.wave_count) == (16, 14)


def test_point_cloud_info_lists_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """-i on a point cloud prints its size and per-class point counts, and writes nothing."""
    source = write_point_cloud(tmp_path / "terrain.laz")

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-i")

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.splitlines() == [
        "Points: 1600 (LAS 1.4, point format 6)",
        "Class 2 (ground): 1600",
    ]
    assert not list(tmp_path.glob("*.wt"))


def test_point_cloud_visualize_shows_the_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-v on a point cloud plots the rasterized grid the wavetable would be made from."""
    source = write_point_cloud(tmp_path / "terrain.las")
    shown: list[object] = []
    monkeypatch.setattr("rasterio.plot.show", shown.append)

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-v")

    assert exc_info.value.code == 0
    assert len(shown) == 1
    assert isinstance(shown[0], np.ndarray)
    assert shown[0].shape == (14, 14)
    assert not list(tmp_path.glob("*.wt"))


def test_point_cloud_rejects_band_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-b means nothing for a point cloud, so it's an error rather than silently ignored."""
    source = write_point_cloud(tmp_path / "terrain.las")

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "-b", "1")

    assert exc_info.value.code == "ERROR: -b/--band picks a raster band; point clouds have none."


def test_point_cloud_without_ground_exits_with_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cloud with no ground points exits with a message instead of a traceback."""
    source = write_point_cloud(tmp_path / "canopy.las", classification=5)

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source))

    assert exc_info.value.code == "ERROR: The point cloud has no points classified as [2]."


def write_forest(path: Path) -> Path:
    """A flat 40x40 ground lattice at 10 m with a 30 m treetop (class 5) over every ground point."""
    lattice = np.arange(40, dtype=np.float64)
    x, y = (axis.ravel() for axis in np.meshgrid(lattice, lattice))
    points = laspy.LasData(laspy.LasHeader(point_format=6, version="1.4"))
    points.header.scales = np.array([0.01, 0.01, 0.01])
    points.x = np.concatenate([x, x])
    points.y = np.concatenate([y, y])
    points.z = np.concatenate([np.full(x.size, 10.0), np.full(x.size, 30.0)])
    points.classification = np.concatenate([np.full(x.size, 2), np.full(x.size, 5)]).astype(np.uint8)
    points.write(path)
    return path


@pytest.mark.parametrize(
    ("options", "low", "high"),
    [
        ((), 10.0, 10.0),  # ground by default: the forest floor is flat
        (("--surface", "ground"), 10.0, 10.0),
        (("--surface", "blended"), 20.0, 20.0),  # each cell averages ground and canopy equally
        (("--surface", "canopy"), 30.0, 30.0),  # every cell has a treetop
    ],
)
def test_surface_option_chooses_which_elevations_are_played(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: tuple[str, ...], low: float, high: float
) -> None:
    """--surface ground, blended, and canopy hand the converter the floor, the average, and the treetops."""
    source = write_forest(tmp_path / "forest.las")
    seen: list[npt.NDArray[np.float64]] = []

    def capture(array: npt.NDArray[np.float64], **_: object) -> None:
        """Stand in for the converter: record the grid, then stop before writing anything."""
        seen.append(array.copy())
        sys.exit(0)

    monkeypatch.setattr("geotiff_to_wavetable.cli.array_to_wavetable", capture)

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, tmp_path, str(source), *options)

    assert seen[0].min() == low
    assert seen[0].max() == high


def test_surface_option_is_refused_on_rasters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--surface means nothing for a GeoTIFF, so it's an error rather than silently ignored."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(8, 16))

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "--surface", "canopy")

    assert exc_info.value.code == RASTER_REFUSAL


# --- Logging -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("options", "shows_info", "shows_debug"),
    [((), False, False), (("--verbose",), True, False), (("--debug",), True, True)],
)
def test_logging_goes_to_stderr_not_a_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    options: tuple[str, ...],
    shows_info: bool,
    shows_debug: bool,
) -> None:
    """Progress shows on stderr only with --verbose or --debug, and no log file is ever left behind."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(8, 16))

    run_cli(monkeypatch, tmp_path, str(source), *options)

    stderr = capsys.readouterr().err
    assert ("INFO: Produced wavetable" in stderr) == shows_info
    assert ("DEBUG: Resizing" in stderr) == shows_debug
    assert sorted(path.name for path in tmp_path.iterdir()) == ["terrain.tif", "terrain.wt"]


def test_surface_all_writes_every_surface_labeled_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--surface all writes one table per surface, lettered so they sort together and in order, for every format."""
    source = write_point_cloud(tmp_path / "terrain.las")  # rippled ground, so no surface is flat

    run_cli(monkeypatch, tmp_path, str(source), "--surface", "all", "-f", "wt,wav", "-o", "grove.wt")

    names = ["a-ground", "b-blended", "c-canopy", "d-clipped", "e-capped"]
    expected = sorted(f"grove-{name}.{fmt}" for name in names for fmt in ("wt", "wav"))
    assert sorted(path.name for path in tmp_path.iterdir() if path.name != "terrain.las") == expected
    canopy = read_wt(tmp_path / "grove-c-canopy.wt")
    assert canopy.wave_count == 14  # the 40x40 lattice at 3x spacing, as for one surface


def test_surface_all_refuses_to_visualize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """-v shows one grid, so it needs one surface."""
    source = write_forest(tmp_path / "forest.las")

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "--surface", "all", "-v")

    assert exc_info.value.code == "ERROR: -v/--visualize shows one surface; pick it with --surface."


def test_surface_all_skips_a_flat_surface_and_writes_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Flat surfaces are skipped with a warning, and the rest still write.

    Level ground under level treetops, plus one 60 m tree. Ground is flat. Clipping and capping both cut the lone tree
    back to the 90th percentile, the level treetops, so those are flat too. Blended and canopy keep the tree.
    """
    source = write_forest(tmp_path / "forest.las")
    with laspy.open(source, mode="a") as appender:  # one 60 m tree, so the canopy surfaces aren't flat too
        extra = laspy.ScaleAwarePointRecord.zeros(1, header=appender.header)
        extra.x, extra.y, extra.z, extra.classification = [20.0], [20.0], [60.0], [5]
        appender.append_points(extra)

    run_cli(monkeypatch, tmp_path, str(source), "--surface", "all")

    stderr = capsys.readouterr().err
    for skipped in ("a-ground", "d-clipped", "e-capped"):
        assert f"WARNING: Skipping {skipped}: The selected band is flat" in stderr
    written = sorted(path.name for path in tmp_path.glob("*.wt"))
    assert written == ["forest-b-blended.wt", "forest-c-canopy.wt"]


def test_surface_all_fails_when_nothing_converts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If every surface is unusable, the run fails instead of quietly writing nothing."""
    source = write_forest(tmp_path / "forest.las")  # level ground and level treetops: every surface is flat

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "--surface", "all")

    assert exc_info.value.code == "ERROR: None of the surfaces could be converted; see the warnings above."
    assert not list(tmp_path.glob("*.wt"))


@pytest.mark.parametrize("fill", ["mean", "interpolate"])
def test_fill_option_reaches_the_converter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fill: str) -> None:
    """--fill picks how gaps are filled, for rasters and point clouds alike; interpolate is the default."""
    source = write_geotiff(tmp_path / "terrain.tif", gradient(8, 16))
    seen: list[object] = []

    def capture(array: npt.NDArray[np.float64], **options: object) -> None:
        """Stand in for the converter: record the fill option, then stop before writing anything."""
        seen.append(options["fill"])
        sys.exit(0)

    monkeypatch.setattr("geotiff_to_wavetable.cli.array_to_wavetable", capture)
    extra = () if fill == "interpolate" else ("--fill", fill)

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, tmp_path, str(source), *extra)

    assert seen == [fill]


RASTER_REFUSAL = (
    "ERROR: --surface, --clip-percentile, and --cap-percentile apply to LiDAR point clouds (.las, .laz), not rasters."
)


@pytest.mark.parametrize("option", ["--clip-percentile", "--cap-percentile"])
def test_percentile_options_are_refused_on_rasters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    source = write_geotiff(tmp_path / "terrain.tif", gradient(8, 16))

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), option, "75")

    assert exc_info.value.code == RASTER_REFUSAL


CLIP_REFUSAL = "ERROR: --clip-percentile applies to --surface clipped (or all)."
CAP_REFUSAL = "ERROR: --cap-percentile applies to --surface capped (or all)."


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (("--clip-percentile", "75"), CLIP_REFUSAL),
        (("--surface", "capped", "--clip-percentile", "75"), CLIP_REFUSAL),
        (("--surface", "canopy", "--cap-percentile", "75"), CAP_REFUSAL),
    ],
)
def test_percentile_options_need_their_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: tuple[str, ...], message: str
) -> None:
    """A percentile for a surface that isn't being made would silently do nothing, so it's an error."""
    source = write_forest(tmp_path / "forest.las")

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), *options)

    assert exc_info.value.code == message


@pytest.mark.parametrize("value", ["0", "100.5", "-3", "ninety"])
def test_percentile_options_reject_out_of_range_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """Values must be numbers above 0 and at most 100; argparse rejects the rest with its usage line."""
    source = write_forest(tmp_path / "forest.las")

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, tmp_path, str(source), "--surface", "clipped", "--clip-percentile", value)

    assert exc_info.value.code == 2
    assert "--clip-percentile" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("options", "surface", "expected"),
    [
        (("--surface", "clipped", "--clip-percentile", "60"), "clipped", (60.0, 90.0)),
        (("--surface", "capped", "--cap-percentile", "100"), "capped", (90.0, 100.0)),
        (("--surface", "clipped"), "clipped", (90.0, 90.0)),
    ],
)
def test_percentile_options_reach_the_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: tuple[str, ...],
    surface: str,
    expected: tuple[float, float],
) -> None:
    """The flags pass straight through to load_lidar_surface, defaulting to 90."""
    source = write_forest(tmp_path / "forest.las")
    calls: list[tuple[str, float, float]] = []

    def capture(points: object, name: str, clip_percentile: float, cap_percentile: float) -> None:
        """Stand in for the loader: record what it was asked for, then stop."""
        calls.append((name, clip_percentile, cap_percentile))
        sys.exit(0)

    monkeypatch.setattr("geotiff_to_wavetable.cli.load_lidar_surface", capture)

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, tmp_path, str(source), *options)

    assert calls == [(surface, *expected)]
