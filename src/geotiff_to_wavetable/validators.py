"""Validation utility functions."""

import logging
import math
import sys

import rasterio

# Set up logger
logger = logging.getLogger(__name__)


def is_band_in_band(dataset: rasterio.io.DatasetReader, user_specified_band: int) -> None:
    """Error handling: check the number of bands in the raster file.

    If the user has specified something outside of that range, print an error message and exit. Otherwise, return None.

    Args:
        dataset: The DatasetReader object created with rasterio.open()
        user_specified_band: which band the user wanted (from the -b/--band CLI option)

    Returns:
        None
    """
    number_of_bands: int = dataset.count
    if user_specified_band > number_of_bands:
        # Pluralize "band" if number_of_bands XOR 1 is true.
        sys.exit(
            f"ERROR: The user-specified band ({user_specified_band}) does not exist. "
            f"This raster file only contains {number_of_bands} band{'s'[: number_of_bands ^ 1]}."
        )


def validate_wave_size(wave_size: int) -> bool:
    """Validates that the given wave size is between 2-4096 and is a power of 2.

    Args:
        wave_size: The wave size we are validating

    Returns:
        True if the wave size is valid, False otherwise.
    """
    if math.log2(wave_size).is_integer() and wave_size >= 2 and wave_size <= 4096:
        return True
    else:
        return False
