"""Tests for loaders.py: band selection and nodata handling through color conversion.

The CLI-level behavior (brightness by default, -b channels, palettes, alpha)
is covered end to end in test_integration.py. These pin down the nodata
contract — `load_from_geotiff(...)` plus `dataset.nodata` must still identify
exactly the missing pixels after an RGB or palette source is collapsed to luma.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.io import MemoryFile

from geotiff_to_wavetable.loaders import LUMA_WEIGHTS, load_from_geotiff


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
