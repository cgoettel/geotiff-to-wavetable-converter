"""Command-line interface for the GeoTIFF to Wavetable converter."""

import argparse
import logging
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import laspy
import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.errors import NotGeoreferencedWarning

from geotiff_to_wavetable.converter import array_to_wavetable
from geotiff_to_wavetable.io_utils import (
    display_info,
    display_point_cloud_info,
    visualize,
    write_wav_file,
    write_wt_file,
)
from geotiff_to_wavetable.loaders import (
    GROUND,
    LIDAR_NODATA,
    CellValue,
    load_from_geotiff,
    load_from_lidar,
)
from geotiff_to_wavetable.validators import is_band_in_band, validate_wave_size

# Set up logger
logger = logging.getLogger(__name__)


def wave_size_argument(value: str) -> int:
    """Argparse type for -w/--wave-size: a power of 2 in [2, 4096].

    Validating here (rather than in the converter) makes a bad value fail before
    the raster is read, with argparse's usage line.
    """
    try:
        wave_size = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from None
    if not validate_wave_size(wave_size):
        raise argparse.ArgumentTypeError(f"{wave_size} is not a power of 2 between 2 and 4096")
    return wave_size


FORMATS = ("wt", "wav")


def formats_argument(value: str) -> tuple[str, ...]:
    """Argparse type for -f/--format: a comma-separated subset of FORMATS, in order, duplicates dropped."""
    formats = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if not formats or unknown:
        raise argparse.ArgumentTypeError(f"{value!r}: choose from {', '.join(FORMATS)}, comma-separated")
    return formats


def output_paths(input_file: str, output_file: str | None, formats: tuple[str, ...]) -> dict[str, str]:
    """Work out where each requested format gets written.

    - No -o: next to the input, with the format's extension (with_suffix swaps only the final extension, so
      dotted directories and stems like ./dem.tif, v1.2/dem.tif, dem.v2.tif keep their names).
    - -o with one format: exactly the path given.
    - -o with several formats: the -o path with each format's extension, so `-f wt,wav -o out.wav` writes
      out.wt and out.wav.
    """
    if output_file is None:
        return {fmt: str(Path(input_file).with_suffix(f".{fmt}")) for fmt in formats}
    if len(formats) == 1:
        return {formats[0]: output_file}
    return {fmt: str(Path(output_file).with_suffix(f".{fmt}")) for fmt in formats}


POINT_CLOUD_SUFFIXES = (".las", ".laz")


# --surface: which LiDAR points to keep (None keeps every class) and how each grid cell reduces them.
SURFACES: dict[str, tuple[tuple[int, ...] | None, CellValue]] = {
    "ground": ((GROUND,), "mean"),  # bare earth, like an elevation model
    "blended": (None, "mean"),  # every point averaged: canopy blended with the ground beneath
    "canopy": (None, "highest"),  # the top of every cell: treetops and rooftops
}


def is_point_cloud(input_file: str) -> bool:
    """True for LAS/LAZ LiDAR files, which load through laspy instead of rasterio."""
    return Path(input_file).suffix.lower() in POINT_CLOUD_SUFFIXES


def read_raster(args: argparse.Namespace) -> tuple[npt.NDArray[np.float64], float | None]:
    """Open a raster, handle the raster-only options (-b, -i, -v), and return its array and nodata value."""
    # Photos and scans have no map coordinates, and the conversion never uses them anyway, so rasterio's
    # "no geotransform" warning is noise here.
    warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
    src: rasterio.io.DatasetReader = rasterio.open(args.input_file, "r")
    if src.crs is None:
        logger.info(f"{args.input_file} has no georeferencing (a photo or scan?); treating it as a plain image.")

    if args.surface is not None:
        sys.exit("ERROR: --surface applies to LiDAR point clouds (.las, .laz), not rasters.")
    # -b, --band. If the provided band is out-of-band, print an error message and exit.
    if args.band is not None:
        is_band_in_band(src, args.band)
    # -i, --info
    if args.info:
        display_info(src)
        sys.exit(0)
    # -v, --visualize
    if args.visualize:
        visualize(src)
        sys.exit(0)

    band = "auto" if args.band is None else args.band
    logger.info(f"Converting band {band} from {args.input_file}...")
    nodata: float | None = src.nodata
    return load_from_geotiff(src, args.band), nodata


def read_point_cloud(args: argparse.Namespace) -> tuple[npt.NDArray[np.float64], float | None]:
    """Read a LAS/LAZ point cloud, handle -i and -v, and return it rasterized, with its nodata value."""
    if args.band is not None:
        sys.exit("ERROR: -b/--band picks a raster band; point clouds have none.")
    points = laspy.read(args.input_file)
    # -i, --info
    if args.info:
        display_point_cloud_info(points)
        sys.exit(0)

    # --surface picks which points to keep and how each cell reduces them; the default is the bare ground.
    surface = args.surface or "ground"
    classes, cell_value = SURFACES[surface]
    logger.info(f"Converting the {surface} surface from {args.input_file}...")
    try:
        array = load_from_lidar(points, classes=classes, cell_value=cell_value)
    except ValueError as error:
        sys.exit(f"ERROR: {error}")
    # -v, --visualize. Shows the rasterized grid, which is what the wavetable is made from.
    if args.visualize:
        visualize(array)
        sys.exit(0)
    return array, LIDAR_NODATA


def main() -> None:
    """Parses the command-line arguments and runs the desired commands."""
    # Set up logging.
    #  We want INFO+ (default; feel free to change) logged to a file, but only WARNING+ to the console.
    # File handler for everything
    file_handler = logging.FileHandler("geotiff_to_wavetable.log")
    file_handler.setLevel(logging.INFO)

    # Console handler for warnings and errors only
    console_handler = logging.StreamHandler()  # Defaults to stderr
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))  # Simplified format for console

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
        format="%(asctime)s %(name)s - %(levelname)s: %(message)s",
    )

    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Converts rasters and LiDAR point clouds to a wavetable.")

    # Required arguments
    parser.add_argument(
        "input_file",  # Works with relative and absolute paths.
        type=str,
        help=(
            "The filename (relative or absolute) to the raster file, or a LAS/LAZ LiDAR point cloud (.las, .laz), "
            "whose ground points are gridded into an elevation model first."
        ),
    )

    # Optional arguments
    parser.add_argument(
        "-b",
        "--band",
        default=None,
        type=int,
        help=(
            "Which band you would like processed. The -i/--info option will tell you how many bands there are. "
            "You can then use this command in conjunction with -v/--visualize to see that band displayed. "
            "Default: brightness (luma) for color images such as photos and scans, otherwise band 1. "
            "On a color image, -b 1/2/3 picks the red/green/blue channel alone."
        ),
    )
    parser.add_argument(
        "-c",
        "--columns",
        action="store_true",
        help=(
            "Read the raster left to right, one column per wave frame, instead of top to bottom, one row per frame. "
            "The same poster scanned the other way makes a different instrument."
        ),
    )
    parser.add_argument(
        "-i",
        "--info",
        action="store_true",
        help=(
            "Displays information embedded in the provided raster file. "
            "For example, these files may contain multiple bands (like geothermal, elevation) and you only want one. "
            "Use this option before using -b/--band and -v/--visualize to ensure you're seeing the raster you want."
        ),
    )
    parser.add_argument(
        "-o",
        "--output-file",
        help=(
            "The filename (relative or absolute) of the output file. Default: INPUT_FILE.wt (or .wav, per -f). "
            "With several formats, each gets this path with its own extension."
        ),
    )
    parser.add_argument(
        "-f",
        "--format",
        type=formats_argument,
        default=("wt",),
        help=(
            "Output format(s), comma-separated: wt (a wavetable for Bitwig, Surge, and other software synthesizers) "
            "and/or wav (every frame back to back in a mono 16-bit 44.1 kHz WAV, for hardware samplers like the "
            "M8, MPC, or OP-1). Example: -f wt,wav. Default: wt"
        ),
    )
    parser.add_argument(
        "-w",
        "--wave-size",
        type=wave_size_argument,
        default=None,
        help=(
            "Samples per wave frame: a power of 2 from 2 to 4096. Smaller sizes sound crunchier and lo-fi, and make "
            "smaller files. Default: the raster's width rounded up to a power of 2, capped at 4096."
        ),
    )
    parser.add_argument(
        "-v",
        "--visualize",
        action="store_true",
        help=(
            "Displays a visualization of the provided raster in an external viewer."
            "This is a helpful first step to make check your. See also -b/--band and -i/--info."
        ),
    )

    parser.add_argument(
        "--surface",
        choices=SURFACES,
        default=None,
        help=(
            "LiDAR only: which surface to play. ground is the bare earth (trees and buildings removed). blended "
            "averages every point, so trees and buildings rise softly out of the ground. canopy takes the top of each "
            "spot: treetops and rooftops. Tall trees can take over the range and flatten the terrain under them, so "
            "which sounds best depends on the place. Default: ground"
        ),
    )

    # Parse arguments
    args: argparse.Namespace = parser.parse_args()

    # Read the input once, handling the options that stop before converting (-i, -v). argparse handles -h on its own.
    if is_point_cloud(args.input_file):
        array, nodata = read_point_cloud(args)
    else:
        array, nodata = read_raster(args)

    # -o, --output-file and -f, --format: one output path per requested format (see output_paths).
    outputs = output_paths(args.input_file, args.output_file, args.format)
    logger.info(f"Writing {', '.join(outputs.values())}.")

    # -c, --columns. Transposing turns columns into rows, so each column becomes a wave frame. Copy to a contiguous
    # array: the transpose is a strided view, and nodata cleaning writes into it in place.
    if args.columns:
        logger.info("Reading columns as wave frames (--columns).")
        array = np.ascontiguousarray(array.T)
    try:
        samples, wave_size, wave_count = array_to_wavetable(array, nodata=nodata, wave_size=args.wave_size)
    except ValueError as error:
        # Unusable input (e.g. an all-nodata band): exit with the message instead of a traceback, matching the
        # other CLI errors.
        sys.exit(f"ERROR: {error}")
    writers: dict[str, Callable[[str, list[bytes], int, int], None]] = {"wt": write_wt_file, "wav": write_wav_file}
    for fmt, path in outputs.items():
        writers[fmt](path, samples, wave_size, wave_count)


if __name__ == "__main__":
    main()
