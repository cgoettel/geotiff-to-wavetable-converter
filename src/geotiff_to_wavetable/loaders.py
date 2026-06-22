"""Loader functions for turning source files into raw elevation arrays.

Each loader is responsible only for reading a source format and returning a
2D numpy array of float64 samples. Cleaning and transformation live in
`converter`. This split lets new formats (e.g. LiDAR via laspy, issue #19)
slot in alongside without touching the transform pipeline.

The pipeline is float64 end-to-end; loaders cast from the source dtype so
int-dtype rasters (e.g. SRTM int16) don't truncate during nodata mean replacement.
"""

import logging

import numpy as np
import numpy.typing as npt
import rasterio

logger = logging.getLogger(__name__)


def load_from_geotiff(dataset: rasterio.io.DatasetReader, band: int) -> npt.NDArray[np.float64]:
    """Load a single band from a GeoTIFF dataset as a float64 array.

    The returned array is the raw band data (cast to float64) — nodata sentinel
    values are NOT replaced here. Pass `dataset.nodata` alongside the array to
    `array_to_wavetable` so it can clean them.

    Args:
        dataset: The DatasetReader object created with rasterio.open().
        band: Which band to read (1-indexed).

    Returns:
        A 2D float64 array of shape (dataset.height, dataset.width).
    """
    logger.info(
        f"Loading band {band} from GeoTIFF (width={dataset.width}, height={dataset.height}, "
        f"bands={dataset.count}, nodata={dataset.nodata}, dtype={dataset.dtypes[band - 1]})"
    )
    return np.asarray(dataset.read(band), dtype=np.float64)
