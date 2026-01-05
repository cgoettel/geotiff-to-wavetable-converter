"""I/O utility functions."""

import logging
import sys

import rasterio
import rasterio.plot

from geotiff_to_wavetable.validators import validate_wave_size

# Set up logger
logger = logging.getLogger(__name__)


def display_info(dataset: rasterio.io.DatasetReader) -> None:
    """Displays information about the provided raster file.

    This object has around 60 pieces of metadata. For more information, open a Python REPL and poke around.
    I've tried to include only the information that the user will need or might find most helpful or informational.
    If there is additional information that you think should be provided, please submit a PR or file an issue.

    Args:
        dataset: The DatasetReader object created with rasterio.open()

    Returns:
        None
    """
    bands: int = dataset.count
    width: int = dataset.width
    height: int = dataset.height
    info = "Bands: {}\nWidth: {}\nHeight: {}"
    print(info.format(bands, width, height))


def visualize(dataset: rasterio.io.DatasetReader) -> None:
    """Plots the provided object.

    This is a helpful debugging step that allows you to provide a file and see it plotted.
    It's a good first step in checking your data — not just that it's valid, but that Python can read it.

    Args:
        dataset: The DatasetReader object created with rasterio.open()

    Returns:
        None
    """
    rasterio.plot.show(dataset)


def write_wt_file(output_file: str, samples: list[bytes], wave_size: int, wave_count: int) -> None:
    """Writes a `.wt` file to disk.

    From: https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/generated-wt.py#L8C1-L15C26

    `.wt` files are binary and in [this format](https://github.com/surge-synthesizer/surge/blob/main/resources/data/wavetables/WT%20fileformat.txt)

    Args:
        output_file: a string containing the location of the `.wt` file we're going to write
        samples: a list of bytes containing the frames from the WAV file
        wave_size: the size of each wave in the wavetable
        wave_count: the number of waves in the wavetable

    Returns:
        None
    """
    with open(output_file, "wb") as out_file:
        # Big endian. Everything following is little endian.
        out_file.write(b"vawt")

        # The wave size must be between 2-4096 (as a power of 2)
        if validate_wave_size(wave_size):
            out_file.write(wave_size.to_bytes(4, byteorder="little"))
        else:
            sys.exit(
                f"ERROR: The data has a wave size of {wave_size},{wave_count}. Must be a power of 2 between 2-4096."
            )
        # The wave count must be between 1-512
        out_file.write(wave_count.to_bytes(2, byteorder="little"))
        # Flags (see https://github.com/surge-synthesizer/surge/blob/main/resources/data/wavetables/WT%20fileformat.txt)
        out_file.write(bytes([12, 0]))
        # The rest of the byte sequence is the wave data. There's room at the end for metadata, but we don't have any.
        # float32 format: size = 4 * wave_size * wave_count bytes
        # int16 format:   size = 2 * wave_size * wave_count bytes
        for data in samples:
            out_file.write(data)
