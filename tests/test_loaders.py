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

from geotiff_to_wavetable.loaders import GROUND, LUMA_WEIGHTS, load_from_geotiff, load_from_lidar, load_lidar_surface


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


# --- load_lidar_surface -------------------------------------------------------------------------


def hillside(path: Path) -> laspy.LasData:
    """Ground rising 10 m per cell from west to east, with a tree on each of the first nine cells and a 50 m one last.

    Ten 1 m cells in a row. Ground at x+0.5 sits at 10*x; trees (class 5) stand 5 m tall over cells 0-8 and 50 m over
    cell 9. A single high-noise return (class 18) floats 500 m up over cell 0. Two more ground points, at x=0 and
    x=10, pin the extent to exactly ten cells.
    """
    cells = np.arange(10, dtype=np.float64)
    ground_x, ground_z = cells + 0.5, 10 * cells
    tree_x = cells + 0.5
    tree_z = ground_z + np.where(cells == 9, 50.0, 5.0)
    return write_las(
        path,
        x=[0.0, *ground_x, *tree_x, 0.5, 10.0],
        y=[0.0] * 23,
        z=[0.0, *ground_z, *tree_z, 500.0, 90.0],
        classification=[GROUND, *[GROUND] * 10, *[5] * 10, 18, GROUND],
    )


def test_surfaces_drop_noise(tmp_path: Path) -> None:
    """A high-noise return 500 m up never becomes the canopy."""
    points = hillside(tmp_path / "fixture.las")

    canopy = load_lidar_surface(points, "canopy", cell_size=1.0)

    assert np.nanmax(canopy) == 140.0  # the 50 m tree on the 90 m ground, not the 500 m noise
    assert canopy[0, 0] == 5.0


def test_clipped_cuts_the_canopy_at_its_90th_percentile(tmp_path: Path) -> None:
    """The clipped surface flattens the top 10% of canopy elevations, whatever they are: here, the tall tree."""
    points = hillside(tmp_path / "fixture.las")
    canopy = load_lidar_surface(points, "canopy", cell_size=1.0)

    clipped = load_lidar_surface(points, "clipped", cell_size=1.0)

    ceiling = np.nanpercentile(canopy, 90)
    np.testing.assert_array_equal(clipped, np.minimum(canopy, ceiling))
    assert np.nanmax(clipped) < 140.0


def test_capped_keeps_the_hill_and_reins_in_the_tall_tree(tmp_path: Path) -> None:
    """The capped surface keeps every cell's ground and caps only the height above it, so the hilltop survives."""
    points = hillside(tmp_path / "fixture.las")

    capped = load_lidar_surface(points, "capped", cell_size=1.0)

    ground = 10 * np.arange(10, dtype=np.float64)
    heights = np.array([5.0] * 9 + [50.0])
    cap = np.percentile(heights, 90)  # 9.5 m: the 50 m tree is cut down, the 5 m ones are untouched
    np.testing.assert_allclose(capped[0], ground + np.minimum(heights, cap))


def test_blended_and_ground_surfaces_match_load_from_lidar(tmp_path: Path) -> None:
    """The ground surface is load_from_lidar's default; blended is every class but noise, averaged."""
    points = hillside(tmp_path / "fixture.las")

    np.testing.assert_array_equal(
        load_lidar_surface(points, "ground", cell_size=1.0), load_from_lidar(points, cell_size=1.0)
    )
    np.testing.assert_array_equal(
        load_lidar_surface(points, "blended", cell_size=1.0),
        load_from_lidar(points, classes=[GROUND, 5], cell_size=1.0),
    )


def test_surfaces_refuse_what_they_cannot_make(tmp_path: Path) -> None:
    """An unknown surface, a cloud of nothing but noise, and capped without ground points all fail loudly."""
    noise_only = write_las(tmp_path / "noise.las", x=[0.0], y=[0.0], z=[1.0], classification=[18])
    trees_only = write_las(tmp_path / "trees.las", x=[0.0, 1.0], y=[0.0, 0.0], z=[1.0, 2.0], classification=[5, 5])

    with pytest.raises(ValueError, match="Surface must be one of"):
        load_lidar_surface(trees_only, "forest")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="only noise"):
        load_lidar_surface(noise_only, "canopy")
    with pytest.raises(ValueError, match=r"no points classified as \[2\]"):
        load_lidar_surface(trees_only, "capped")


def test_capped_interpolates_the_ground_under_buildings(tmp_path: Path) -> None:
    """A roof hides the ground, so capped fills the ground in from its neighbors instead of dropping the building."""
    building = 6
    # Five 1 m cells: ground at 10 m in cells 0, 2, and 4; a 40 m roof over cell 1 and a 20 m one over cell 3.
    points = write_las(
        tmp_path / "fixture.las",
        x=[0.5, 2.5, 4.5, 1.5, 3.5, 0.0, 5.0],
        y=[0.0] * 7,
        z=[10.0, 10.0, 10.0, 40.0, 20.0, 10.0, 10.0],
        classification=[GROUND, GROUND, GROUND, building, building, GROUND, GROUND],
    )

    capped = load_lidar_surface(points, "capped", cell_size=1.0)

    cap = float(np.percentile([30.0, 10.0], 90))  # the two buildings' heights above the interpolated 10 m ground
    np.testing.assert_allclose(capped[0], [10.0, 10.0 + cap, 10.0, 20.0, 10.0])
