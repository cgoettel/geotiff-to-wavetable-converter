"""Converts raster files (like GeoTIFF) to wavetables (.wt) for use in Bitwig Studio."""

from importlib.metadata import version

from geotiff_to_wavetable.converter import (
    array_to_wavetable,
    calculate_height,
    calculate_width,
)
from geotiff_to_wavetable.io_utils import (
    display_info,
    visualize,
    write_wt_file,
)
from geotiff_to_wavetable.loaders import (
    load_from_geotiff,
)
from geotiff_to_wavetable.validators import (
    is_band_in_band,
    validate_wave_size,
)

__version__ = version("geotiff-to-wavetable")

__all__ = [
    "array_to_wavetable",
    "calculate_height",
    "calculate_width",
    "display_info",
    "is_band_in_band",
    "load_from_geotiff",
    "validate_wave_size",
    "visualize",
    "write_wt_file",
]
