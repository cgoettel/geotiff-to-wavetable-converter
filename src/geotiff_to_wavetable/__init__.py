"""Converts raster files (like GeoTIFF) to wavetables (.wt) for use in Bitwig Studio."""

from importlib.metadata import version

from geotiff_to_wavetable.converter import (
    calculate_height,
    calculate_width,
    convert_geotiff_to_wt,
)
from geotiff_to_wavetable.io_utils import (
    display_info,
    visualize,
    write_wt_file,
)
from geotiff_to_wavetable.validators import (
    is_band_in_band,
    validate_wave_size,
)

__version__ = version("geotiff-to-wavetable")

__all__ = [
    "calculate_height",
    "calculate_width",
    "convert_geotiff_to_wt",
    "display_info",
    "is_band_in_band",
    "validate_wave_size",
    "visualize",
    "write_wt_file",
]
