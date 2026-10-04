"""Loader functions for turning source files into raw 2D sample arrays.

Each loader is responsible only for reading a source format and returning a
2D numpy array of float64 samples. Cleaning and transformation live in
`converter`. This split lets new formats (e.g. LiDAR via laspy, issue #19)
slot in alongside without touching the transform pipeline.

The pipeline is float64 end-to-end; loaders cast from the source dtype so
int-dtype rasters (e.g. SRTM int16) don't truncate during nodata mean replacement.

`load_from_lidar` reads LAS/LAZ point clouds instead, binning the points onto a
grid first (see its docstring). Empty cells come back as NaN, which
`array_to_wavetable` fills like any other nodata.

`load_from_geotiff` handles any raster GDAL can open — GeoTIFFs, but also
photos and scans (JPEG, PNG, WebP, ...). Color images need one extra step,
because their bands are color channels rather than independent measurements:

- RGB(A) sources collapse to luma (perceived brightness), so a blue-on-white
  poster isn't read as its near-flat red channel. Alpha is ignored.
- Palette sources (GIFs, indexed PNGs) store color-table indices, whose order
  is arbitrary; they're looked up in the color table and collapsed to luma.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal, get_args

import laspy
import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.enums import ColorInterp
from rasterio.fill import fillnodata

logger = logging.getLogger(__name__)

# Rec. 709 luma weights, applied to the gamma-encoded channel values. That's
# luma (Y′), not linear luminance — the right call here, since we want the
# brightness a person sees on the page, and it's what image editors do.
LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)

RGB = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)

# ASPRS classification code for bare-earth returns.
GROUND = 2

# Cells this many times the average point spacing hold about nine points each, enough for a steady mean. Finer grids
# leave far more cells empty: on the Lower Colorado example, 1x spacing leaves 40% of cells with no ground point,
# while 3x settles near the 15% floor set by the river, which returns almost nothing.
CELL_SPACINGS = 3.0

# The nodata value load_from_lidar uses for cells no point landed in.
LIDAR_NODATA = float("nan")

# How load_from_lidar reduces the elevations in one cell to a single value.
CellValue = Literal["mean", "highest"]
CELL_VALUES: tuple[CellValue, ...] = get_args(CellValue)

# ASPRS low noise (7) and high noise (18): stray returns below the ground and in the air (birds, haze). Dropped from
# every surface, since one high-noise return can sit far above the tallest building and become the whole range.
NOISE = (7, 18)

# The surfaces load_lidar_surface can make, in the order --surface all letters them a, b, c, ...
Surface = Literal["ground", "blended", "canopy", "clipped", "capped"]
SURFACES: tuple[Surface, ...] = get_args(Surface)

# clipped caps the canopy at this percentile of its elevations, so a few tall trees can't take the whole range.
CLIP_PERCENTILE = 90.0

# capped limits each tree or building's height above the ground to this percentile of those heights. Only heights
# over STRUCTURE_HEIGHT (in the file's vertical units) count, so the bare ground's centimeters don't pull it down.
CAP_PERCENTILE = 90.0
STRUCTURE_HEIGHT = 1.0


def is_rgb(dataset: rasterio.io.DatasetReader) -> bool:
    """True when bands 1–3 are tagged red, green, blue (JPEG, PNG, RGB GeoTIFFs, ...)."""
    return tuple(dataset.colorinterp[:3]) == RGB


def load_from_geotiff(dataset: rasterio.io.DatasetReader, band: int | None = None) -> npt.NDArray[np.float64]:
    """Load one 2D float64 array from a raster.

    With `band=None`, RGB(A) sources collapse to luma and everything else uses
    band 1. With an explicit band, that band is read as-is, so `-b 2` on a photo
    gives its green channel. Palette bands always expand through their color
    table, since raw indices aren't meaningful samples.

    The returned array is the raw data (cast to float64) — nodata sentinel
    values are NOT replaced here. Pass `dataset.nodata` alongside the array to
    `array_to_wavetable` so it can clean them.

    Args:
        dataset: The DatasetReader object created with rasterio.open().
        band: Which band to read (1-indexed), or None to choose automatically.

    Returns:
        A 2D float64 array of shape (dataset.height, dataset.width).
    """
    colors = ", ".join(interp.name for interp in dataset.colorinterp)
    logger.info(
        f"Loading from raster (width={dataset.width}, height={dataset.height}, bands={dataset.count}, "
        f"colors={colors}, nodata={dataset.nodata}, dtypes={dataset.dtypes})"
    )

    nodata: float | None = dataset.nodata

    if band is None and is_rgb(dataset):
        logger.info("RGB source and no band requested: converting to luma (Rec. 709).")
        rgb = np.asarray(dataset.read([1, 2, 3]), dtype=np.float64)
        # A pixel is nodata when every channel is the sentinel (GDAL's convention for RGB fill).
        missing = None if nodata is None else np.all(rgb == nodata, axis=0)
        return _carry_nodata(_luma(rgb), missing, nodata)

    band = 1 if band is None else band
    data = np.asarray(dataset.read(band), dtype=np.float64)

    if dataset.colorinterp[band - 1] == ColorInterp.palette:
        logger.info(f"Band {band} is palette-indexed: expanding through its color table to luma.")
        missing = None if nodata is None else data == nodata
        return _carry_nodata(_palette_to_luma(data, dataset.colormap(band)), missing, nodata)

    logger.info(f"Using band {band} (dtype={dataset.dtypes[band - 1]}).")
    return data


@dataclass(frozen=True)
class _Grid:
    """A square grid over a point cloud's extent: row 0 is the north edge and column 0 the west edge."""

    west: float
    north: float
    cell_size: float
    width: int
    height: int

    def cells(self, x: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> npt.NDArray[np.intp]:
        """Flat cell index for each point. Points on the east and south edges fold into the last cell."""
        columns = np.minimum((x - self.west) // self.cell_size, self.width - 1)
        rows = np.minimum((self.north - y) // self.cell_size, self.height - 1)
        cells: npt.NDArray[np.intp] = (rows * self.width + columns).astype(np.intp)
        return cells


def _make_grid(x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], cell_size: float | None) -> _Grid:
    """Lay a grid over the points, with cells CELL_SPACINGS times their average spacing unless cell_size is given."""
    west, north = float(x.min()), float(y.max())
    width_extent, height_extent = x.max() - west, north - y.min()
    if cell_size is None:
        # Average spacing: the side of the square each point would get if they were spread evenly. Points on a line
        # (a transect) have no area, so space them along its length instead. A single point gets one unit cell.
        area = width_extent * height_extent
        spacing = np.sqrt(area / x.size) if area > 0 else max(width_extent, height_extent) / x.size
        cell_size = float(CELL_SPACINGS * spacing) if spacing > 0 else 1.0
        logger.info(f"Average point spacing {spacing:.3f}; using cell size {cell_size:.3f}.")
    elif cell_size <= 0:
        raise ValueError(f"Cell size must be positive; got {cell_size}.")

    # Size the grid to cover the extent. Folding edge points into the last cell (see _Grid.cells) keeps an extent
    # that's an exact multiple of the cell size from growing a sliver row or column holding only those points.
    width = max(1, int(np.ceil(width_extent / cell_size)))
    height = max(1, int(np.ceil(height_extent / cell_size)))
    return _Grid(west, north, cell_size, width, height)


def _reduce(
    grid: _Grid, cells: npt.NDArray[np.intp], z: npt.NDArray[np.float64], cell_value: CellValue
) -> npt.NDArray[np.float64]:
    """Reduce each cell's elevations to one value, as a (height, width) array with LIDAR_NODATA in empty cells."""
    size = grid.width * grid.height
    counts = np.bincount(cells, minlength=size)
    occupied = counts > 0
    values = np.full(size, LIDAR_NODATA)
    if cell_value == "mean":
        sums = np.bincount(cells, weights=z, minlength=size)
        values[occupied] = sums[occupied] / counts[occupied]
    elif cell_value == "highest":
        highest = np.full(size, -np.inf)
        np.maximum.at(highest, cells, z)
        values[occupied] = highest[occupied]
    else:
        raise ValueError(f"Cell value must be one of {', '.join(CELL_VALUES)}; got {cell_value!r}.")
    empty_percentage = 100 * (1 - occupied.mean())
    logger.info(
        f"Rasterized to {grid.height}x{grid.width} cells of {grid.cell_size:.3f} ({cell_value}); "
        f"{empty_percentage:.1f}% empty."
    )
    return values.reshape(grid.height, grid.width)


def load_from_lidar(
    points: laspy.LasData,
    classes: Collection[int] | None = (GROUND,),
    cell_size: float | None = None,
    cell_value: CellValue = "mean",
) -> npt.NDArray[np.float64]:
    """Rasterize a LAS/LAZ point cloud into one 2D float64 array of elevations.

    Points are binned onto a square grid in the file's own horizontal units, and
    each cell takes the mean (or highest) elevation of the points inside it. Row
    0 is the north edge and column 0 the west edge, the same orientation as a
    raster.

    The default keeps ground returns only, which gives the same surface as a
    bare-earth elevation model. Pass `classes=None` to keep every point
    (vegetation, buildings, noise), which gives a rougher surface. With every
    point, `cell_value="highest"` traces the treetops and rooftops (a surface
    model), while `"mean"` blends them with the ground beneath.

    Cells no point landed in (water, mostly) are `LIDAR_NODATA` (NaN). Pass
    `LIDAR_NODATA` as `array_to_wavetable`'s nodata so it can fill them.

    Args:
        points: The point cloud, from `laspy.read()`.
        classes: ASPRS classification codes to keep, or None for every point.
        cell_size: Grid cell width in the file's horizontal units (meters for
            Web Mercator, which stretches ground distances by 1/cos(latitude)).
            None picks `CELL_SPACINGS` times the average point spacing.
        cell_value: How each cell reduces its points' elevations: "mean" or "highest".

    Returns:
        A 2D float64 array, one cell per grid square.

    Raises:
        ValueError: if no point has one of `classes`, `cell_size` isn't positive,
            or `cell_value` isn't one of `CELL_VALUES`.
    """
    header = points.header
    logger.info(
        f"Loading from point cloud (LAS {header.version}, point format {header.point_format.id}, "
        f"{header.point_count} points, classes={'all' if classes is None else sorted(classes)})"
    )

    x = np.asarray(points.x, dtype=np.float64)
    y = np.asarray(points.y, dtype=np.float64)
    z = np.asarray(points.z, dtype=np.float64)
    if classes is not None:
        keep = np.isin(np.asarray(points.classification), list(classes))
        logger.info(f"Kept {int(keep.sum())} of {keep.size} points with classes {sorted(classes)}.")
        x, y, z = x[keep], y[keep], z[keep]
    if x.size == 0:
        logger.error(f"No points with classes {classes}; nothing to rasterize.")
        raise ValueError(f"The point cloud has no points classified as {sorted(classes or [])}.")

    grid = _make_grid(x, y, cell_size)
    return _reduce(grid, grid.cells(x, y), z, cell_value)


def load_lidar_surface(
    points: laspy.LasData,
    surface: Surface = "ground",
    cell_size: float | None = None,
) -> npt.NDArray[np.float64]:
    """Rasterize one named surface of a LAS/LAZ point cloud.

    Every surface but ground keeps all points except noise (`NOISE`):

    - ground: ground points, mean per cell. The bare earth, like an elevation model.
    - blended: mean per cell, so trees and buildings rise softly out of the ground.
    - canopy: highest per cell: treetops and rooftops, with square-edged buildings.
    - clipped: canopy, capped at its `CLIP_PERCENTILE` elevation, so a few tall
      trees can't take the whole range. On hilly ground this also flattens the
      hilltops, since it caps elevation rather than height.
    - capped: ground plus each tree or building's height above it, capped at
      the `CAP_PERCENTILE` of those heights. It keeps hilltops and still
      reins in the tallest trees. Where a roof or crown hides the ground, the
      ground beneath is interpolated from the ground around it.

    Args:
        points: The point cloud, from `laspy.read()`.
        surface: One of `SURFACES`.
        cell_size: Grid cell width in the file's horizontal units, or None to
            pick one from the point density (see `load_from_lidar`).

    Returns:
        A 2D float64 array, with `LIDAR_NODATA` (NaN) in empty cells.

    Raises:
        ValueError: if `surface` is unknown, or the cloud lacks the points the
            surface needs (ground points, or anything besides noise).
    """
    if surface == "ground":
        return load_from_lidar(points, cell_size=cell_size)
    if surface not in SURFACES:
        raise ValueError(f"Surface must be one of {', '.join(SURFACES)}; got {surface!r}.")

    codes = np.asarray(points.classification)
    classes = sorted(set(np.unique(codes).tolist()) - set(NOISE))
    if not classes:
        raise ValueError("The point cloud has only noise points.")
    logger.info(f"Making the {surface} surface from classes {classes} (noise dropped).")
    if surface == "blended":
        return load_from_lidar(points, classes=classes, cell_size=cell_size)
    if surface in ("canopy", "clipped"):
        canopy = load_from_lidar(points, classes=classes, cell_size=cell_size, cell_value="highest")
        if surface == "canopy":
            return canopy
        ceiling = np.nanpercentile(canopy, CLIP_PERCENTILE)
        logger.info(f"Clipping the canopy at {ceiling:.2f} (its {CLIP_PERCENTILE:g}th percentile).")
        clipped: npt.NDArray[np.float64] = np.minimum(canopy, ceiling)
        return clipped

    # capped: the ground and the canopy on one shared grid, so height above ground is a per-cell subtraction.
    keep = np.isin(codes, classes)
    x = np.asarray(points.x, dtype=np.float64)[keep]
    y = np.asarray(points.y, dtype=np.float64)[keep]
    z = np.asarray(points.z, dtype=np.float64)[keep]
    ground_points = codes[keep] == GROUND
    if not ground_points.any():
        raise ValueError(f"The point cloud has no points classified as [{GROUND}].")
    grid = _make_grid(x, y, cell_size)
    cells = grid.cells(x, y)
    top = _reduce(grid, cells, z, "highest")
    ground = _reduce(grid, cells[ground_points], z[ground_points], "mean")
    # A roof or a dense crown hides the ground beneath it, so those cells have no ground point. Estimate it from the
    # surrounding ground (GDAL's inverse-distance fill, searching as far as the grid is wide), or every building
    # would come out empty and be mean-filled instead of capped.
    missing = np.isnan(ground)
    if missing.any():
        logger.info(f"Interpolating the ground under {int(missing.sum())} cells that have no ground point.")
        ground = fillnodata(
            ground, mask=~missing, max_search_distance=float(max(grid.width, grid.height)), smoothing_iterations=0
        )
    height_above = np.clip(top - ground, 0, None)  # NaN only where a cell has no point at all
    structures = height_above[height_above > STRUCTURE_HEIGHT]
    cap = float(np.percentile(structures, CAP_PERCENTILE)) if structures.size else 0.0
    logger.info(
        f"Capping heights above ground at {cap:.2f} (the {CAP_PERCENTILE:g}th percentile of {structures.size} cells "
        f"taller than {STRUCTURE_HEIGHT:g})."
    )
    capped: npt.NDArray[np.float64] = ground + np.minimum(height_above, cap)
    return capped


def _carry_nodata(
    converted: npt.NDArray[np.float64],
    missing: npt.NDArray[np.bool_] | None,
    nodata: float | None,
) -> npt.NDArray[np.float64]:
    """Keep the `dataset.nodata` contract after a color conversion.

    Converting to luma changes pixel values, so the source's nodata pixels would
    no longer equal the sentinel (and slip into the wavetable), while an
    unlucky valid pixel could land on it (and be mean-filled). Put the sentinel
    back on exactly the missing pixels, and nudge any valid pixel that collides
    with it by one float step — far below anything audible.
    """
    if missing is None or nodata is None:
        return converted
    collisions = (converted == nodata) & ~missing
    converted[collisions] = np.nextafter(nodata, np.inf)
    converted[missing] = nodata
    logger.debug(
        f"Carried {int(missing.sum())} nodata pixels through color conversion ({int(collisions.sum())} nudged)."
    )
    return converted


def _luma(rgb: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Collapse a (3, height, width) RGB stack to a (height, width) luma array."""
    red_weight, green_weight, blue_weight = LUMA_WEIGHTS
    luma: npt.NDArray[np.float64] = red_weight * rgb[0] + green_weight * rgb[1] + blue_weight * rgb[2]
    return luma


def _palette_to_luma(
    indices: npt.NDArray[np.float64],
    colormap: dict[int, tuple[int, int, int, int]],
) -> npt.NDArray[np.float64]:
    """Map palette indices through their color table, then collapse to luma."""
    # Size for the largest index actually present too, so an index the color table
    # omits reads as black rather than raising IndexError.
    table = np.zeros((max(max(colormap), int(indices.max())) + 1, 3), dtype=np.float64)
    for index, (red, green, blue, _alpha) in colormap.items():
        table[index] = (red, green, blue)
    logger.debug(f"Palette has {len(colormap)} entries.")
    # (height, width, 3) → (3, height, width) so _luma sees channels first.
    rgb = np.moveaxis(table[indices.astype(np.intp)], -1, 0)
    return _luma(rgb)
