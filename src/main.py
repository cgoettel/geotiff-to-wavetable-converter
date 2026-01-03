import argparse
import math
import sys
import tempfile
import wave

import cv2
import numpy as np
import rasterio
import rasterio.io
import rasterio.plot


def calculate_height(height: int) -> int:
    """
    wt files require a wave count between 1 and 512, inclusive. Given a height, return the maximum height ≤512.

    @param height: the current height
    """
    if height > 512:
        return 512
    else:
        return height


def calculate_width(width: int) -> int:
    """
    wt files require a wave size between 2 and 4096, as a power of 2.

    Given a width, this method calculates the closest power of 2 without going above 4096.

    @param width: the current width
    """
    if width > 4096:
        return 4096
    else:
        return shift_bit_length(width)


def convert_geotiff_to_wt(dataset: rasterio.io.DatasetReader, user_specified_band: int) -> list[bytes]:
    """
    Converts the provided file from GeoTIFF to a wavetable (`.wt` format).

    Notes as I figure this out:
    - Bitwig uses a `.wt` file (or a .wav file, but I think it'll be easier to get to `.wt` (based off of nothing))
    - There's a [wt-tool](https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/wt-tool.py) provided by [Surge Synthesizer](https://github.com/surge-synthesizer/surge-synthesizer.github.io/wiki/Creating-Wavetables-For-Surge) which we might need to rely on heavily, at least for inspiration and guidance.
        - Maybe they have libraries we can lift, too? Not seeing anything in PyPi. Might just have to sideload. And document.
        - Here's the [section on writing a .wt file](https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/wt-tool.py#L174-L180)
    - `.wt` files are binary and in [this format](https://github.com/surge-synthesizer/surge/blob/main/resources/data/wavetables/WT%20fileformat.txt)

    I think the simplest thing to do here is to convert GeoTIFF to an intermediate format (even another picture) because there's too much data in GeoTIFF and I don't know how to handle it. Once it's in another format, `okwt` can already convert pictures to wavetables, so we can do similarly.

    We're massively overthinking this: the src.read returns an array. THAT'S BASICALLY A CSV! Let's just run with that. We can already convert .csv files.

    @param input_file: a string containing the location of the GeoTIFF file to convert
    @param user_specified_band: the band of the GeoTIFF file to process. Default: 1
    """
    # Read the data from the specified band and store it.
    array: np.ndarray = dataset.read(user_specified_band)
    # wt files support wave cycles of length 2-4096 (as powers of 2) and we can't guarantee that our input data will have a number of waves that's a power of 2. Additionally, we can only have a wave count of 1-512 waves.
    # We'll need to resize our array so the wave size (determined by len(array[n])) is a power of 2 in the range 2-4096 and the wave count (determined by len(array)) is between 1-512, inclusive.
    # A little discussion: To illustrate this point, the test input data I'm using (GeoTIFF of Oro Valley, AZ, USA) is 3612x3612. 3612 is between 2048 and 4096 so we have a choice to make: do we resize down and lose data, or do we resize up and maybe incorrectly interpolate data? I've tried both and they're both really accurate. 2048 sounds great in Bitwig. Let's just use the next greatest and be done with it.
    # TODO: add a flag to control the width. lower resolution could produce a crunchier tone. see issue #4.
    resize_width: int = calculate_width(dataset.width)
    resize_height: int = calculate_height(dataset.height)

    # With out new width and height determined, we can resize the ndarray to the new size.
    # TODO: add a flag to switch interpolation algorithms. more: https://stackoverflow.com/questions/48121916/numpy-resize-rescale-image
    resized_array = cv2.resize(array, dsize=(resize_width, resize_height), interpolation=cv2.INTER_CUBIC)
    # If you would like to play around with the dsize dimensions and visualize the output, so that and uncomment this next line:
    # rasterio.plot.show(resized_array)

    # There are two approaches I can think of:
    # 1. convert ndarray -> WAV and then WAV -> bytes (for wt)
    # 2. skip the intermediary and just iterate through ndarray and convert to bytes
    # Both seem to be producing the same (incorrect) output. That's something, but I'm not sure what.

    # Approach 1. This is from [Reddit](https://www.reddit.com/r/synthesizers/comments/84rlal/need_help_with_a_weird_csv_to_audio_conversion/).
    # Set up a temporary file where we can write the WAV data.
    temp_file: tempfile._TemporaryFileWrapper[bytes] = tempfile.NamedTemporaryFile()
    wave_data: wave.Wave_write = wave.open(temp_file.name, "wb")

    # Define parameters for the wave file.
    channels = 1  # 1 = mono, 2 = stereo
    sample_width = 2
    sample_rate = 44100
    number_of_audio_frames = 0
    compression_type = "NONE"
    compression_name = "not compressed"
    wave_data.setparams(
        (
            channels,
            sample_width,
            sample_rate,
            number_of_audio_frames,
            compression_type,
            compression_name,
        )
    )

    # Write each wave in the dataset's array into a temporary WAV file.
    for waveform in resized_array:
        wave_data.writeframes(waveform)
    wave_data.close()

    # Now that the data is in a format we know how to work with (i.e., WAV), we read the WAV file frame by frame and put those bytes into a list.
    databuffer: list[bytes] = []
    with wave.open(temp_file, "rb") as wav_file:
        n_frames: int = wav_file.getnframes()
        sample_width: int = wav_file.getsampwidth()
        content: bytes = wav_file.readframes(n_frames * sample_width)
        databuffer.append(content)

    # Approach 2
    # databuffer: list[bytes] = []
    # for current_wave in resized_array:
    #     databuffer.append(b"".join(current_wave))

    rasterio.plot.show(databuffer)
    return databuffer


def display_info(dataset: rasterio.io.DatasetReader) -> None:
    """
    Displays information about the provided raster file.

    This object has around 60 pieces of metadata. For more information, open a Python REPL and poke around.
    I've tried to include only the information that the user will need or might find most helpful or informational.
    If there is additional information that you think should be provided, please submit a PR or file an issue.

    @param dataset: The DatasetReader object created with rasterio.open()
    """
    bands = dataset.count
    width = dataset.width
    height = dataset.height
    info = "Bands: {}\nWidth: {}\nHeight: {}"
    print(info.format(bands, width, height))


def is_band_in_band(dataset: rasterio.io.DatasetReader, user_specified_band: int) -> None:
    """
    Error handling: check the number of bands in the raster file.

    If the user has specified something outside of that range, print an error message and exit. Otherwise, return None.

    @param dataset: The DatasetReader object created with rasterio.open()
    @param user_specified_band: which band the user wanted (from the -b/--band CLI option)
    """
    number_of_bands = dataset.count
    if user_specified_band > number_of_bands:
        # Pluralize "band" if number_of_bands XOR 1 is true.
        sys.exit(
            f"ERROR: The user-specified band ({user_specified_band}) does not exist. "
            f"This raster file only contains {number_of_bands} band{'s'[: number_of_bands ^ 1]}."
        )

    return None


def shift_bit_length(num: int) -> int:
    """
    Finds the next greatest power of 2 that is greater than or equal to num.

    Usage::

    >>> shift_bit_length(2047)
    2048

    >>> shift_bit_length(2048)
    2048

    >>> shift_bit_length(2049)
    4096
    """
    return 1 << (num - 1).bit_length()


def validate_wave_size(wave_size: int) -> bool:
    """
    Validates that the given wave size is between 2-4096 and is a power of 2.

    @param wave_size: The wave size we are validating
    """
    if math.log2(wave_size).is_integer() and wave_size >= 2 and wave_size <= 4096:
        return True
    else:
        return False


def visualize(dataset: rasterio.io.DatasetReader) -> None:
    """
    Plots the provided object.

    This is a helpful debugging step that allows you to provide a file and see it plotted.
    It's a good first step in checking your data — not just that it's valid, but that Python can read it.

    @param dataset: The DatasetReader object created with rasterio.open()
    """
    # TODO: I think it would look prettier to display a title with the graphic, but src.meta is pretty ugly and probably not what the end user wants to see. For USGS data, they're not putting the location or even coordinates in the object anywhere, so not sure what to display. Display nothing cause that's better?
    # rasterio.plot.show(src, title=src.meta)
    rasterio.plot.show(dataset)


def write_wt_file(output_file: str, samples: list[bytes]):
    """
    From: https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/generated-wt.py#L8C1-L15C26

    @param output_file: a string containing the location of the `.wt` file we're going to write
    @param samples: a list of bytes containing the frames from the WAV file
    """
    with open(output_file, "wb") as out_file:
        # Big endian. Everything following is little endian.
        out_file.write(b"vawt")

        # wave_size = int(len(samples[0]) / 4)
        wave_size = 4096
        # wave_count = len(samples)
        wave_count = 512

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
        # out_file.write(bytes([4, 0]))
        out_file.write(b"0004")
        # The rest of the byte sequence is the wave data. There's room at the end for metadata, but we don't have any.
        # float32 format: size = 4 * wave_size * wave_count bytes
        # int16 format:   size = 2 * wave_size * wave_count bytes
        for data in samples:
            out_file.write(data)


def main() -> None:
    """
    Parses the command-line arguments and runs the desired commands.
    """
    # Instantiate argument parser
    parser = argparse.ArgumentParser(description="Converts rasters to a wavetable.")

    # Required arguments
    # TODO: this works with both relative and absolute paths?
    parser.add_argument(
        "input_file",
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
    src = rasterio.open(args.input_file, "r")

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

    samples: list[bytes] = convert_geotiff_to_wt(src, args.band)
    write_wt_file(args.output_file, samples)


if __name__ == "__main__":
    main()
