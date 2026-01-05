"""Core conversion logic."""

import logging

import cv2
import numpy as np
import numpy.typing as npt
import rasterio
from cv2.typing import Range

# Set up logger
logger = logging.getLogger(__name__)


def calculate_height(height: int) -> int:
    """Given a height, return the maximum height ≤512.

    The `wt` filetype requires a wave count between 1 and 512, inclusive.

    Args:
        height: the current height

    Returns:
        the adjusted height, capped at 512
    """
    if height > 512:
        return 512
    else:
        return height


def calculate_width(width: int) -> int:
    """The `wt` filetype requires a wave size between 2 and 4096, as a power of 2.

    Given a width, this method calculates the closest power of 2 without going above 4096.

    Args:
        width: the current width

    Returns:
        the adjusted width, capped at 4096 and as a power of 2
    """
    if width > 4096:
        return 4096
    else:
        return shift_bit_length(width)


def convert_geotiff_to_wt(dataset: rasterio.io.DatasetReader, user_specified_band: int) -> tuple[list[bytes], int, int]:
    """Converts the provided file from GeoTIFF to a list[bytes] which is what the `.wt` format expects.

    You can then feed that list of bytes to the `write_wt_file` function to write the `.wt` file to disk.

    Args:
        dataset: The DatasetReader object created with rasterio.open()
        user_specified_band: which band the user wanted (from the -b/--band CLI option) (default: 1)

    Returns:
        A list of bytes representing the frames from the WAV file.
    """
    # Read the data from the specified band and store it.
    bands = dataset.read(user_specified_band)

    # Handle nodata values by replacing them with the mean of the valid data.
    # GeoTiffs often have nodata values defined (to deal with clouds or oceans, etc.) which will skew the data.
    nodata_values = dataset.nodata
    if nodata_values is not None:
        # Create mask for valid data (not nodata AND not NaN)
        valid_mask = (bands != nodata_values) & (~np.isnan(bands))

        # Calculate percentage BEFORE replacement
        valid_percentage = (valid_mask.sum() / valid_mask.size) * 100
        logger.debug(f"Valid pixels: {valid_mask.sum()} out of {valid_mask.size} ({valid_percentage:.1f}%)")

        if valid_mask.any():
            bands[~valid_mask] = bands[valid_mask].mean()
        else:
            raise ValueError("Error: The selected band contains only nodata/NaN values. Try a different band or file.")

        # Warn about sparse data
        if valid_percentage < 50:
            logger.warning(f"Only {valid_percentage:.1f}% valid data. Wavetable may be mostly silent.")
            logger.error("Less than 50% valid data — output will likely be unusable.")

    logger.debug(f"Nodata value: {nodata_values}")
    logger.debug(f"Array has NaN: {np.isnan(bands).any()}")
    logger.debug(f"Array has Inf: {np.isinf(bands).any()}")
    logger.debug(f"Array min: {bands.min()}, max: {bands.max()}")
    logger.debug(f"Range: {bands.max() - bands.min()}")

    # Save the valid data range AFTER nodata_values handling (for clipping after resize) with only have valid data.
    valid_min = bands.min()
    valid_max = bands.max()

    # wt files support wave cycles of length 2-4096 (as powers of 2).
    # And wave counts of 1-512 waves.
    # This resizes the width and height accordingly.
    # TODO: (issue #4) add a flag to control the width. lower resolution could produce a crunchier tone. see issue #4.
    resized_width: int = calculate_width(dataset.width)
    resized_height: int = calculate_height(dataset.height)

    logger.debug(f"Resized width: {resized_width}, resized height: {resized_height}")

    # With our new width and height determined, we can resize the ndarray to the new size.
    # TODO: add a flag to switch interpolation algorithms. more: https://stackoverflow.com/questions/48121916/numpy-resize-rescale-image
    resized_bands: Range = cv2.resize(bands, dsize=(resized_width, resized_height), interpolation=cv2.INTER_CUBIC)
    # Clip to prevent interpolation artifacts
    clipped_bands: npt.NDArray[np.float64] = np.clip(resized_bands, valid_min, valid_max)

    logger.debug(f"After clip - has NaN: {np.isnan(clipped_bands).any()}")
    logger.debug(f"After clip - has Inf: {np.isinf(clipped_bands).any()}")
    logger.debug(f"After clip - min: {clipped_bands.min()}, max: {clipped_bands.max()}")
    # If you would like to play around with the dsize dimensions and visualize the output:
    # Uncomment this next line and add `import rasterio.plot` at the top.
    # rasterio.plot.show(clipped_bands)

    # With the resized and clipped array, we can now normalize it to fit in the int16 range.
    # We start by normalizing to 0–1.
    normalized_bands = (clipped_bands - clipped_bands.min()) / (clipped_bands.max() - clipped_bands.min())
    # Then scale to int16 range (-32,768 to 32,767) — that's a range of 65,535 total values
    scaled_bands = normalized_bands * 65535 - 32768

    logger.debug(f"After normalize - min: {normalized_bands.min()}, max: {normalized_bands.max()}")
    logger.debug(f"After scale - min: {scaled_bands.min()}, max: {scaled_bands.max()}")

    # We can now convert to an int16 array.
    int16_array = scaled_bands.astype(np.int16)

    # Convert that to bytes.
    byte_array = int16_array.tobytes()

    return [byte_array], resized_width, resized_height


def shift_bit_length(num: int) -> int:
    """Finds the next greatest power of 2 that is greater than or equal to num.

    Usage::

    >>> shift_bit_length(2047)
    2048

    >>> shift_bit_length(2048)
    2048

    >>> shift_bit_length(2049)
    4096

    Args:
        num: the number to evaluate

    Returns:
        the next greatest power of 2 greater than or equal to num
    """
    return 1 << (num - 1).bit_length()
