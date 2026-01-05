"""Command-line interface for the GeoTIFF to Wavetable converter."""

import argparse
import logging
import sys

import rasterio

from geotiff_to_wavetable.converter import convert_geotiff_to_wt
from geotiff_to_wavetable.io_utils import display_info, visualize, write_wt_file
from geotiff_to_wavetable.validators import is_band_in_band

# Set up logger
logger = logging.getLogger(__name__)


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
    parser = argparse.ArgumentParser(description="Converts rasters to a wavetable.")

    # Required arguments
    parser.add_argument(
        "input_file",  # Works with relative and absolute paths.
        type=str,
        help="The filename (relative or absolute) to the raster file.",
    )

    # Optional arguments
    parser.add_argument(
        "-b",
        "--band",
        default=1,
        type=int,
        help=(
            "Which band you would like processed. The -i/--info option will tell you how many bands there are. "
            "You can then use this command in conjunction with -v/--visualize to see that band displayed. Default: 1"
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
        help="The filename (relative or absolute) of the output file. Default: INPUT_FILE.wt",
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

    # Parse arguments
    args: argparse.Namespace = parser.parse_args()

    # In order to handle the various options, we first need to read in the raster file and store that object.
    # This also means we don't have to read in the object in multiple places.
    src: rasterio.io.DatasetReader = rasterio.open(args.input_file, "r")

    # Handle each argument. argparse handles -h on its own.
    # -b, --band. If the provided band is out-of-band, print an error message and exit.
    if args.band:
        is_band_in_band(src, args.band)
    # -i, --info
    if args.info:
        display_info(src)
        sys.exit(0)
    # -o, --output-file.
    # If the user does not specify an output file, save the wavetable to the same path and name as the input file,
    # but with the .wt file extension.
    if args.output_file is None:
        args.output_file = args.input_file.split(".")[0] + ".wt"
    if args.visualize:
        visualize(src)
        sys.exit(0)

    logger.info(f"Converting band {args.band} from {args.input_file} to {args.output_file}...")

    samples, wave_size, wave_count = convert_geotiff_to_wt(src, args.band)
    write_wt_file(args.output_file, samples, wave_size, wave_count)


if __name__ == "__main__":
    main()
