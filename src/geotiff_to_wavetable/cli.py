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

from geotiff_to_wavetable.converter import FILLS, array_to_wavetable
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
    Surface,
    load_from_geotiff,
    load_lidar_surface,
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


# One table to convert: a label for its file name (None for a single output) and its array and nodata value.
Table = tuple[str | None, npt.NDArray[np.float64], float | None]


def surface_label(surface: str) -> str:
    """The file-name label --surface all gives a surface: a letter for sort order, then its name (a-ground, ...)."""
    return f"{chr(ord('a') + SURFACES.index(surface))}-{surface}"


def labeled(path: str, label: str | None) -> str:
    """Add a table's label to an output path's name: river.wt becomes river-a-ground.wt."""
    return path if label is None else str(Path(path).with_stem(f"{Path(path).stem}-{label}"))


def is_point_cloud(input_file: str) -> bool:
    """True for LAS/LAZ LiDAR files, which load through laspy instead of rasterio."""
    return Path(input_file).suffix.lower() in POINT_CLOUD_SUFFIXES


def read_raster(args: argparse.Namespace) -> list[Table]:
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
    return [(None, load_from_geotiff(src, args.band), nodata)]


def read_point_cloud(args: argparse.Namespace) -> list[Table]:
    """Read a LAS/LAZ point cloud, handle -i and -v, and return each requested surface rasterized."""
    if args.band is not None:
        sys.exit("ERROR: -b/--band picks a raster band; point clouds have none.")
    if args.surface == "all" and args.visualize:
        sys.exit("ERROR: -v/--visualize shows one surface; pick it with --surface.")
    points = laspy.read(args.input_file)
    # -i, --info
    if args.info:
        display_point_cloud_info(points)
        sys.exit(0)

    # --surface picks which points to keep and how each cell reduces them; the default is the bare ground. With all,
    # every surface gets its own file, labeled so they sort together and in order (river-a-ground, river-b-blended).
    surfaces: tuple[Surface, ...] = SURFACES if args.surface == "all" else (args.surface or "ground",)
    tables: list[Table] = []
    for surface in surfaces:
        logger.info(f"Converting the {surface} surface from {args.input_file}...")
        try:
            array = load_lidar_surface(points, surface)
        except ValueError as error:
            # A surface the cloud can't make (capped with no ground points, say): fatal on its own, skipped in a batch.
            if args.surface != "all":
                sys.exit(f"ERROR: {error}")
            logger.warning(f"Skipping {surface_label(surface)}: {error}")
            continue
        label = surface_label(surface) if args.surface == "all" else None
        tables.append((label, array, LIDAR_NODATA))
    # -v, --visualize. Shows the rasterized grid, which is what the wavetable is made from.
    if args.visualize:
        visualize(tables[0][1])
        sys.exit(0)
    return tables


def configure_logging(verbose: bool, debug: bool) -> None:
    """Send log messages to stderr: warnings and errors by default, more with --verbose or --debug.

    Nothing is written to a file, so running the tool leaves nothing behind but its output.
    """
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    console_handler = logging.StreamHandler()  # Defaults to stderr
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    # Attach to the package's logger rather than the root, so other libraries' logging is left alone. The logger
    # passes everything through and the handler's level decides what's shown. Assigning (not appending) replaces the
    # handler from an earlier call, as when tests run main() repeatedly.
    package_logger = logging.getLogger("geotiff_to_wavetable")
    package_logger.setLevel(logging.DEBUG)
    package_logger.handlers = [console_handler]


def main() -> None:
    """Parses the command-line arguments and runs the desired commands."""
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
        choices=(*SURFACES, "all"),
        default=None,
        help=(
            "LiDAR only: which surface to play. ground is the bare earth (trees and buildings removed). blended "
            "averages every point, so trees and buildings rise softly out of the ground. canopy takes the top of each "
            "spot: treetops and rooftops, with square-edged buildings. clipped is canopy with the tallest 10%% cut "
            "flat, so a few big trees can't take the whole range. capped keeps the ground's shape and limits how "
            "far trees and buildings rise above it. all writes every surface to its own file, labeled so they sort "
            "together: river-a-ground.wt, river-b-blended.wt, and so on. Which sounds best depends on the place. "
            "Default: ground"
        ),
    )

    parser.add_argument(
        "--fill",
        choices=FILLS,
        default="interpolate",
        help=(
            "How gaps are filled: nodata in a raster, or LiDAR cells no point landed in (water, ground hidden under "
            "trees or roofs). interpolate estimates each gap from the cells around it, so it follows the terrain. "
            "mean uses the average of everything else, which suits flat ground but leaves a spike or a pit in "
            "every gap on a slope. Default: interpolate"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also print progress messages (what was read, how it was gridded or resized) to stderr.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print everything --verbose does, plus detailed diagnostics (value ranges, nodata counts) to stderr.",
    )

    # Parse arguments
    args: argparse.Namespace = parser.parse_args()
    configure_logging(args.verbose, args.debug)

    # Read the input once, handling the options that stop before converting (-i, -v). argparse handles -h on its own.
    tables = read_point_cloud(args) if is_point_cloud(args.input_file) else read_raster(args)

    # -o, --output-file and -f, --format: one output path per requested format (see output_paths), with each table's
    # label added when there are several.
    outputs = output_paths(args.input_file, args.output_file, args.format)
    writers: dict[str, Callable[[str, list[bytes], int, int], None]] = {"wt": write_wt_file, "wav": write_wav_file}
    written = 0
    for label, array, nodata in tables:
        paths = {fmt: labeled(path, label) for fmt, path in outputs.items()}
        logger.info(f"Writing {', '.join(paths.values())}.")

        # -c, --columns. Transposing turns columns into rows, so each column becomes a wave frame. Copy to a
        # contiguous array: the transpose is a strided view, and nodata cleaning writes into it in place.
        if args.columns:
            logger.info("Reading columns as wave frames (--columns).")
            array = np.ascontiguousarray(array.T)
        try:
            samples, wave_size, wave_count = array_to_wavetable(
                array, nodata=nodata, wave_size=args.wave_size, fill=args.fill
            )
        except ValueError as error:
            # Unusable input (e.g. an all-nodata band): exit with the message instead of a traceback, matching the
            # other CLI errors. In a batch (--surface all), skip just that table, so one flat surface (bare ground
            # with no relief, say) doesn't cost the others.
            if label is None:
                sys.exit(f"ERROR: {error}")
            logger.warning(f"Skipping {label}: {error}")
            continue
        for fmt, path in paths.items():
            writers[fmt](path, samples, wave_size, wave_count)
        written += 1
    if written == 0:
        sys.exit("ERROR: None of the surfaces could be converted; see the warnings above.")


if __name__ == "__main__":
    main()
