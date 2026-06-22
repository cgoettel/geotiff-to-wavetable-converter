"""Core conversion logic.

Transforms a raw 2D array (from any loader in `loaders`) into the
list-of-bytes / wave-size / wave-count tuple expected by `write_wt_file`.
"""

import logging
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

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


def _clean_nodata(
    bands: npt.NDArray[np.float64],
    nodata_value: float | None,
) -> tuple[npt.NDArray[np.float64], float]:
    """Replace nodata/NaN values in-place with the mean of valid data.

    GeoTIFFs often have a nodata sentinel (for clouds, oceans, gaps, etc.).
    Leaving those values in skews the normalization step and produces
    DC-offset artifacts in the wavetable.

    Args:
        bands: The input 2D array. Modified in place.
        nodata_value: The dataset's nodata sentinel, or None if unset.

    Returns:
        A tuple of (cleaned array, percentage of pixels that were valid).

    Raises:
        ValueError: if the band contains only nodata/NaN values.
    """
    if nodata_value is None:
        logger.debug("No nodata value on the source; skipping nodata cleaning.")
        return bands, 100.0

    valid_mask = (bands != nodata_value) & (~np.isnan(bands))
    valid_percentage = (valid_mask.sum() / valid_mask.size) * 100
    logger.debug(
        f"Valid pixels: {valid_mask.sum()} of {valid_mask.size} ({valid_percentage:.1f}%); nodata={nodata_value}"
    )

    if not valid_mask.any():
        logger.error("Selected band contains only nodata/NaN values — cannot proceed.")
        raise ValueError("The selected band contains only nodata/NaN values. Try a different band or file.")

    bands[~valid_mask] = bands[valid_mask].mean()

    if valid_percentage < 10:
        logger.error(f"Only {valid_percentage:.1f}% valid data — output will likely be unusable.")
    elif valid_percentage < 50:
        logger.warning(f"Only {valid_percentage:.1f}% valid data. Wavetable may be mostly silent.")

    return bands, valid_percentage


def _resize_for_wavetable(
    bands: npt.NDArray[np.float64],
    target_width: int,
    target_height: int,
    valid_min: float,
    valid_max: float,
) -> npt.NDArray[np.float64]:
    """Resize to wavetable dimensions and clip to the pre-resize valid range.

    Cubic interpolation can overshoot the original range near steep edges, so
    we clip back to [valid_min, valid_max] to keep the int16 normalization honest.

    Args:
        bands: The input 2D array (cleaned of nodata).
        target_width: The output width (wave size — a power of 2 in [2, 4096]).
        target_height: The output height (wave count — in [1, 512]).
        valid_min: Lower clip bound, typically `bands.min()` before resize.
        valid_max: Upper clip bound, typically `bands.max()` before resize.

    Returns:
        A 2D array of shape (target_height, target_width), clipped to the valid range.
    """
    logger.debug(f"Resizing {bands.shape} -> ({target_height}, {target_width}); clip range=[{valid_min}, {valid_max}]")
    # TODO: (issue #4) add a flag to switch interpolation algorithms.
    # https://stackoverflow.com/questions/48121916/numpy-resize-rescale-image
    # cv2.resize preserves dtype at runtime, but its stubs widen it to integer|floating.
    # Cast is safe because `bands` is guaranteed float64 by the signature above.
    resized = cast(
        "npt.NDArray[np.float64]",
        cv2.resize(bands, dsize=(target_width, target_height), interpolation=cv2.INTER_CUBIC),
    )
    clipped: npt.NDArray[np.float64] = np.clip(resized, valid_min, valid_max)
    logger.debug(
        f"After resize+clip: has_nan={np.isnan(clipped).any()}, has_inf={np.isinf(clipped).any()}, "
        f"min={clipped.min()}, max={clipped.max()}"
    )
    return clipped


def _normalize_to_int16(bands: npt.NDArray[np.float64]) -> npt.NDArray[np.int16]:
    """Linearly rescale an array into the int16 audio range (-32768, 32767).

    Args:
        bands: The input 2D array. Must have `max > min` (i.e. non-constant data).

    Returns:
        A 2D int16 array spanning the full int16 range.
    """
    normalized = (bands - bands.min()) / (bands.max() - bands.min())
    scaled = normalized * 65535 - 32768
    result: npt.NDArray[np.int16] = scaled.astype(np.int16)
    logger.debug(
        f"Normalized 0-1 range: [{normalized.min():.4f}, {normalized.max():.4f}]; "
        f"scaled int16 range: [{result.min()}, {result.max()}]"
    )
    return result


def array_to_wavetable(
    array: npt.NDArray[np.float64],
    nodata: float | None = None,
) -> tuple[list[bytes], int, int]:
    """Convert a raw 2D array into wavetable byte data.

    This is the source-agnostic entry point. Pair it with a loader from the
    `loaders` module (e.g. `load_from_geotiff`) to go end-to-end.

    Args:
        array: A 2D array of raw sample data (e.g. elevation values).
        nodata: The sentinel value representing "no data", or None if the
            array has no nodata values.

    Returns:
        A tuple of (byte frames list, wave size / width, wave count / height)
        suitable for passing to `write_wt_file`.
    """
    height, width = array.shape
    logger.info(f"Converting {height}x{width} array to wavetable (nodata={nodata}).")

    cleaned, valid_percentage = _clean_nodata(array, nodata)

    # Capture the valid range AFTER cleaning (so nodata-replacement values are
    # included) but BEFORE resize (so cubic interpolation overshoot gets clipped
    # back to the real data range).
    valid_min = cleaned.min()
    valid_max = cleaned.max()

    wave_size = calculate_width(width)
    wave_count = calculate_height(height)

    resized = _resize_for_wavetable(cleaned, wave_size, wave_count, valid_min, valid_max)
    int16_array = _normalize_to_int16(resized)

    logger.info(
        f"Produced wavetable: wave_size={wave_size}, wave_count={wave_count}, valid_data={valid_percentage:.1f}%."
    )
    return [int16_array.tobytes()], wave_size, wave_count
