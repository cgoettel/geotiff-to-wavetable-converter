"""Converts raster files (like GeoTIFF) to wavetables (.wt) for use in Bitwig Studio."""

from importlib.metadata import version

from geotiff_to_wavetable.converter import (
    array_to_wavetable,
    calculate_height,
    calculate_width,
)
from geotiff_to_wavetable.io_utils import (
    display_info,
    display_point_cloud_info,
    visualize,
    write_wav_file,
    write_wt_file,
)
from geotiff_to_wavetable.loaders import (
    LIDAR_NODATA,
    SURFACES,
    load_from_geotiff,
    load_from_lidar,
    load_lidar_surface,
)
from geotiff_to_wavetable.validators import (
    is_band_in_band,
    validate_wave_size,
)

__version__ = version("geotiff-to-wavetable")

__all__ = [
    "LIDAR_NODATA",
    "SURFACES",
    "array_to_wavetable",
    "calculate_height",
    "calculate_width",
    "display_info",
    "display_point_cloud_info",
    "is_band_in_band",
    "load_from_geotiff",
    "load_from_lidar",
    "load_lidar_surface",
    "validate_wave_size",
    "visualize",
    "write_wav_file",
    "write_wt_file",
]
