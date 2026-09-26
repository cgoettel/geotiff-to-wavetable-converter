"""Loader functions for turning source files into raw 2D sample arrays.

Each loader is responsible only for reading a source format and returning a
2D numpy array of float64 samples. Cleaning and transformation live in
`converter`. This split lets new formats (e.g. LiDAR via laspy, issue #19)
slot in alongside without touching the transform pipeline.

The pipeline is float64 end-to-end; loaders cast from the source dtype so
int-dtype rasters (e.g. SRTM int16) don't truncate during nodata mean replacement.

`load_from_geotiff` handles any raster GDAL can open — GeoTIFFs, but also
photos and scans (JPEG, PNG, WebP, ...). Color images need one extra step,
because their bands are color channels rather than independent measurements:

- RGB(A) sources collapse to luma (perceived brightness), so a blue-on-white
  poster isn't read as its near-flat red channel. Alpha is ignored.
- Palette sources (GIFs, indexed PNGs) store color-table indices, whose order
  is arbitrary; they're looked up in the color table and collapsed to luma.
"""

import logging

import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.enums import ColorInterp

logger = logging.getLogger(__name__)

# Rec. 709 luma weights, applied to the gamma-encoded channel values. That's
# luma (Y′), not linear luminance — the right call here, since we want the
# brightness a person sees on the page, and it's what image editors do.
LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)

RGB = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)


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
