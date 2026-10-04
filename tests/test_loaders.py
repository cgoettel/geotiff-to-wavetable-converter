"""Tests for loaders.py: band selection, nodata handling, and point cloud rasterizing.

The CLI-level behavior (brightness by default, -b channels, palettes, alpha)
is covered end to end in test_integration.py. These pin down each loader's
contract. For `load_from_geotiff`, the nodata contract: its result plus
`dataset.nodata` must still identify exactly the missing pixels after an RGB or
palette source is collapsed to luma. For `load_from_lidar`, the grid: which
points land in which cell, which classes count, and that empty cells are NaN.

Both loaders also read small synthetic files written to `tmp_path`, so their
tests stay structurally parallel and need no real-world fixture.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import laspy
import numpy as np
import numpy.typing as npt
import pytest
import rasterio
from rasterio.io import MemoryFile

from geotiff_to_wavetable.loaders import GROUND, LUMA_WEIGHTS, load_from_geotiff, load_from_lidar


@contextmanager
def raster(
    bands: npt.NDArray[np.uint8],
    nodata: float | None,
    photometric: str,
    colormap: dict[int, tuple[int, int, int, int]] | None = None,
) -> Iterator[rasterio.io.DatasetReader]:
    """An in-memory GeoTIFF with the given photometric interpretation (RGB or PALETTE)."""
    count, height, width = bands.shape
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=width,
            height=height,
            count=count,
            dtype="uint8",
            nodata=nodata,
            photometric=photometric,
            crs="EPSG:4326",
            transform=rasterio.transform.from_origin(0.0, float(height), 1.0, 1.0),
        ) as writer:
            writer.write(bands)
            if colormap is not None:
                writer.write_colormap(1, colormap)
        with memory.open() as dataset:
            yield dataset


def test_rgb_nodata_pixels_keep_the_sentinel() -> None:
    """All-sentinel RGB pixels come back as exactly the sentinel; a pixel with one zero channel doesn't."""
    fill = (0, 0, 0)
    blue = (0, 0, 255)
    gray = (100, 100, 100)
    pixels = np.array([[fill, blue], [gray, fill]], dtype=np.uint8)  # (height, width, 3)
    bands = np.moveaxis(pixels, -1, 0)

    with raster(bands, nodata=0, photometric="RGB") as dataset:
        result = load_from_geotiff(dataset)

    assert result[0, 0] == 0
    assert result[1, 1] == 0
    assert result[0, 1] == LUMA_WEIGHTS[2] * 255  # pure blue is real data, not fill
    assert result[1, 0] > 0


def test_palette_nodata_index_keeps_the_sentinel_and_collisions_are_nudged() -> None:
    """The nodata index maps back to the sentinel; a real black pixel (luma 0 == sentinel) moves off it."""
    palette = {0: (255, 255, 255, 255), 1: (0, 0, 0, 255), 2: (128, 128, 128, 255)}
    indices = np.array([[[0, 1, 2], [2, 1, 0]]], dtype=np.uint8)

    with raster(indices, nodata=0, photometric="PALETTE", colormap=palette) as dataset:
        result = load_from_geotiff(dataset)

    missing = result == dataset.nodata
    np.testing.assert_array_equal(missing, indices[0] == 0)
    assert result[0, 1] == np.nextafter(0.0, np.inf)  # black: real data, nudged off the sentinel
    assert result[0, 2] > 100


def test_no_nodata_leaves_conversion_untouched() -> None:
    """Without a sentinel there is nothing to carry, so values are plain luma."""
    bands = np.zeros((3, 2, 2), dtype=np.uint8)

    with raster(bands, nodata=None, photometric="RGB") as dataset:
        result = load_from_geotiff(dataset)

    np.testing.assert_array_equal(result, np.zeros((2, 2)))


# --- load_from_geotiff on a file ----------------------------------------------------------------


def test_load_from_geotiff_reads_band_data(tmp_path: Path) -> None:
    """A single-band elevation GeoTIFF comes back as its values, cast to float64, nodata untouched."""
    elevations = np.array([[10, 20, 30, 40], [50, -9999, 70, 80], [90, 100, 110, 120], [130, 140, 150, 160]])
    path = tmp_path / "fixture.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="int16",
        nodata=-9999,
        crs="EPSG:4326",
        transform=rasterio.transform.from_origin(0.0, 4.0, 1.0, 1.0),
    ) as writer:
        writer.write(elevations.astype(np.int16), 1)

    with rasterio.open(path) as dataset:
        result = load_from_geotiff(dataset)

    assert result.dtype == np.float64
    np.testing.assert_array_equal(result, elevations)


# --- load_from_lidar ----------------------------------------------------------------------------


def write_las(
    path: Path,
    x: list[float],
    y: list[float],
    z: list[float],
    classification: list[int],
) -> laspy.LasData:
    """Write a tiny LAS 1.4 point cloud (point format 6, like USGS 3DEP's) and read it back."""
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([0.0, 0.0, 0.0])
    points = laspy.LasData(header)
    points.x = np.array(x)
    points.y = np.array(y)
    points.z = np.array(z)
    points.classification = np.array(classification, dtype=np.uint8)
    points.write(path)
    return laspy.read(path)


def test_load_from_lidar_averages_ground_points_per_cell(tmp_path: Path) -> None:
    """Each cell is the mean ground elevation inside it, with north on row 0 and west on column 0."""
    # A 2x2 grid of 1-unit cells spanning x 0-2, y 0-2. The northwest cell gets two points (mean 15); the
    # southeast corner point sits exactly on the far edges and still lands in the last cell.
    points = write_las(
        tmp_path / "fixture.las",
        x=[0.0, 0.5, 1.5, 0.5, 2.0],
        y=[2.0, 1.5, 1.5, 0.5, 0.0],
        z=[10.0, 20.0, 30.0, 40.0, 50.0],
        classification=[GROUND] * 5,
    )

    result = load_from_lidar(points, cell_size=1.0)

    assert result.dtype == np.float64
    np.testing.assert_array_equal(result, [[15.0, 30.0], [40.0, 50.0]])


def test_load_from_lidar_keeps_only_requested_classes(tmp_path: Path) -> None:
    """Ground only by default, so a tree over a cell doesn't raise it; classes=None keeps every point."""
    medium_vegetation = 4
    points = write_las(
        tmp_path / "fixture.las",
        x=[0.0, 0.0, 1.5],
        y=[0.5, 0.5, 0.5],
        z=[10.0, 30.0, 20.0],
        classification=[GROUND, medium_vegetation, GROUND],
    )

    np.testing.assert_array_equal(load_from_lidar(points, cell_size=1.0), [[10.0, 20.0]])
    np.testing.assert_array_equal(load_from_lidar(points, classes=None, cell_size=1.0), [[20.0, 20.0]])


def test_load_from_lidar_leaves_empty_cells_nan(tmp_path: Path) -> None:
    """Cells with no ground point (a river, say) come back NaN, so array_to_wavetable can fill them."""
    points = write_las(
        tmp_path / "fixture.laz",  # compressed, exercising the lazrs backend
        x=[0.0, 2.5],
        y=[0.5, 0.5],
        z=[10.0, 30.0],
        classification=[GROUND, GROUND],
    )

    result = load_from_lidar(points, cell_size=1.0)

    assert result.shape == (1, 3)
    assert result[0, 0] == 10.0
    assert np.isnan(result[0, 1])
    assert result[0, 2] == 30.0


def test_load_from_lidar_picks_a_cell_size_from_point_density(tmp_path: Path) -> None:
    """With no cell size, cells are three times the average spacing: a 31x31 lattice becomes 11x11."""
    lattice = np.arange(31, dtype=np.float64)
    x, y = np.meshgrid(lattice, lattice)
    points = write_las(
        tmp_path / "fixture.las",
        x=x.ravel().tolist(),
        y=y.ravel().tolist(),
        z=(x + y).ravel().tolist(),
        classification=[GROUND] * x.size,
    )

    result = load_from_lidar(points)

    assert result.shape == (11, 11)
    assert not np.isnan(result).any()


def test_load_from_lidar_grids_a_transect_along_its_length(tmp_path: Path) -> None:
    """Points on one line have no area, so spacing comes from the length: 31 points along x make one row of 11."""
    lattice = np.arange(31, dtype=np.float64)
    points = write_las(
        tmp_path / "fixture.las",
        x=lattice.tolist(),
        y=[0.0] * lattice.size,
        z=lattice.tolist(),
        classification=[GROUND] * lattice.size,
    )

    result = load_from_lidar(points)

    assert result.shape == (1, 11)
    assert not np.isnan(result).any()


def test_load_from_lidar_rejects_a_nonpositive_cell_size(tmp_path: Path) -> None:
    """A zero cell size would divide by zero, so it's refused up front."""
    points = write_las(tmp_path / "fixture.las", x=[0.0], y=[0.0], z=[1.0], classification=[GROUND])

    with pytest.raises(ValueError, match="Cell size must be positive"):
        load_from_lidar(points, cell_size=0.0)


def test_load_from_lidar_without_matching_points_raises(tmp_path: Path) -> None:
    """A cloud with no ground points can't make a ground surface, so it fails loudly."""
    points = write_las(tmp_path / "fixture.las", x=[0.0], y=[0.0], z=[1.0], classification=[1])

    with pytest.raises(ValueError, match=r"no points classified as \[2\]"):
        load_from_lidar(points)


def test_load_from_lidar_highest_takes_the_top_point_per_cell(tmp_path: Path) -> None:
    """cell_value="highest" keeps each cell's tallest point: with every point, that's the canopy, not the ground."""
    medium_vegetation = 4
    points = write_las(
        tmp_path / "fixture.las",
        x=[0.0, 0.0, 0.0, 1.5],
        y=[0.0, 0.0, 0.0, 0.0],
        z=[10.0, 12.0, 30.0, 20.0],
        classification=[GROUND, GROUND, medium_vegetation, GROUND],
    )

    np.testing.assert_array_equal(load_from_lidar(points, cell_size=1.0, cell_value="highest"), [[12.0, 20.0]])
    np.testing.assert_array_equal(
        load_from_lidar(points, classes=None, cell_size=1.0, cell_value="highest"), [[30.0, 20.0]]
    )


def test_load_from_lidar_rejects_an_unknown_cell_value(tmp_path: Path) -> None:
    """A typo in cell_value fails loudly instead of silently averaging."""
    points = write_las(tmp_path / "fixture.las", x=[0.0], y=[0.0], z=[1.0], classification=[GROUND])

    with pytest.raises(ValueError, match="Cell value must be one of mean, highest"):
        load_from_lidar(points, cell_value="median")  # type: ignore[arg-type]
