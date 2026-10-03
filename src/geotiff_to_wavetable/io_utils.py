"""I/O utility functions."""

import logging
import sys
import wave

import laspy
import numpy as np
import numpy.typing as npt
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
    # Color interpretation per band (e.g. "red, green, blue" for a photo, "gray" for most elevation data), so
    # users can see what -b 1/2/3 will pick.
    colors: str = ", ".join(interp.name for interp in dataset.colorinterp)
    info = "Bands: {} ({})\nWidth: {}\nHeight: {}"
    print(info.format(bands, colors, width, height))


def display_point_cloud_info(points: laspy.LasData) -> None:
    """Displays information about a LAS/LAZ point cloud: its size and how many points each class has.

    The class counts show what's in the file before converting. Only ground points (class 2) are used.

    Args:
        points: The LasData object created with laspy.read()

    Returns:
        None
    """
    header = points.header
    classes, counts = np.unique(np.asarray(points.classification), return_counts=True)
    print(f"Points: {header.point_count} (LAS {header.version}, point format {header.point_format.id})")
    for code, count in zip(classes.tolist(), counts.tolist(), strict=True):
        name = ASPRS_CLASSES.get(code, "other")
        print(f"Class {code} ({name}): {count}")


# The ASPRS classes USGS 3DEP point clouds commonly use (LAS 1.4 specification, table 17).
ASPRS_CLASSES = {
    0: "never classified",
    1: "unclassified",
    2: "ground",
    3: "low vegetation",
    4: "medium vegetation",
    5: "high vegetation",
    6: "building",
    7: "low noise",
    9: "water",
    17: "bridge deck",
    18: "high noise",
}


def visualize(dataset: rasterio.io.DatasetReader | npt.NDArray[np.float64]) -> None:
    """Plots the provided object.

    This is a helpful debugging step that allows you to provide a file and see it plotted.
    It's a good first step in checking your data — not just that it's valid, but that Python can read it.

    Args:
        dataset: The DatasetReader object created with rasterio.open(), or a 2D array (a rasterized point cloud)

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


WAV_SAMPLE_RATE = 44100


def write_wav_file(
    output_file: str,
    samples: list[bytes],
    wave_size: int,
    wave_count: int,
    sample_rate: int = WAV_SAMPLE_RATE,
) -> None:
    """Writes the wavetable as a mono 16-bit PCM `.wav`, every frame back to back.

    Hardware samplers (Dirtywave M8, Akai MPC, OP-1, Polyend Tracker, ...) can't read `.wt` files but all play WAVs.
    Played through, the concatenated single-cycle frames become a scan across the wavetable: the terrain (or
    scan) evolving over time. The samples are byte-for-byte the `.wt` payload, so both formats hold the same sound.

    Args:
        output_file: where to write the `.wav` file
        samples: the int16 frame data, as returned by `array_to_wavetable`
        wave_size: samples per frame
        wave_count: number of frames
        sample_rate: playback rate in Hz. 44.1 kHz is what samplers expect; at that rate one frame of
            `wave_size` samples repeats at 44100 / wave_size Hz.

    Returns:
        None
    """
    frames = b"".join(samples)
    expected = 2 * wave_size * wave_count
    if len(frames) != expected:
        # A mismatch would mean the frames and the header describe different tables; refuse rather than write it.
        raise ValueError(
            f"Expected {expected} bytes for {wave_count} frames of {wave_size} samples; got {len(frames)}."
        )
    with wave.open(output_file, "wb") as out_file:
        out_file.setnchannels(1)
        out_file.setsampwidth(2)  # 16-bit
        out_file.setframerate(sample_rate)
        out_file.writeframes(frames)
    logger.info(
        f"Wrote {output_file}: {wave_count} frames x {wave_size} samples, "
        f"{wave_size * wave_count / sample_rate:.2f} s at {sample_rate} Hz."
    )
