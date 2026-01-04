"""Core conversion logic."""

import rasterio


def calculate_height(height: int) -> int:
    """The `wt` filetype requires a wave count between 1 and 512, inclusive. Given a height, return the maximum height ≤512.

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


def convert_geotiff_to_wt(dataset: rasterio.io.DatasetReader, user_specified_band: int) -> list[bytes]:
    """Converts the provided file from GeoTIFF to a wavetable (`.wt` format).

    Notes as I figure this out:
    - Bitwig uses a `.wt` file (or a .wav file, but I think it'll be easier to get to `.wt` (based off of nothing))
    - There's a [wt-tool](https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/wt-tool.py) provided by [Surge Synthesizer](https://github.com/surge-synthesizer/surge-synthesizer.github.io/wiki/Creating-Wavetables-For-Surge) which we might need to rely on heavily, at least for inspiration and guidance.
        - Maybe they have libraries we can lift, too? Not seeing anything in PyPi. Might just have to sideload. And document.
        - Here's the [section on writing a .wt file](https://github.com/surge-synthesizer/surge/blob/main/scripts/wt-tool/wt-tool.py#L174-L180)
    - `.wt` files are binary and in [this format](https://github.com/surge-synthesizer/surge/blob/main/resources/data/wavetables/WT%20fileformat.txt)

    I think the simplest thing to do here is to convert GeoTIFF to an intermediate format (even another picture) because there's too much data in GeoTIFF and I don't know how to handle it. Once it's in another format, `okwt` can already convert pictures to wavetables, so we can do similarly.

    We're massively overthinking this: the src.read returns an array. THAT'S BASICALLY A CSV! Let's just run with that. We can already convert .csv files.

    Args:
        dataset: The DatasetReader object created with rasterio.open()
        user_specified_band: which band the user wanted (from the -b/--band CLI option)

    Returns:
        A list of bytes representing the frames from the WAV file.
    """
    return []  # TODO: implement this function

    # # Read the data from the specified band and store it.
    # array: np.ndarray = dataset.read(user_specified_band)
    # # wt files support wave cycles of length 2-4096 (as powers of 2) and we can't guarantee that our input data will have a number of waves that's a power of 2. Additionally, we can only have a wave count of 1-512 waves.
    # # We'll need to resize our array so the wave size (determined by len(array[n])) is a power of 2 in the range 2-4096 and the wave count (determined by len(array)) is between 1-512, inclusive.
    # # A little discussion: To illustrate this point, the test input data I'm using (GeoTIFF of Oro Valley, AZ, USA) is 3612x3612. 3612 is between 2048 and 4096 so we have a choice to make: do we resize down and lose data, or do we resize up and maybe incorrectly interpolate data? I've tried both and they're both really accurate. 2048 sounds great in Bitwig. Let's just use the next greatest and be done with it.
    # # TODO: add a flag to control the width. lower resolution could produce a crunchier tone. see issue #4.
    # resize_width: int = calculate_width(dataset.width)
    # resize_height: int = calculate_height(dataset.height)

    # # With out new width and height determined, we can resize the ndarray to the new size.
    # # TODO: add a flag to switch interpolation algorithms. more: https://stackoverflow.com/questions/48121916/numpy-resize-rescale-image
    # resized_array = cv2.resize(array, dsize=(resize_width, resize_height), interpolation=cv2.INTER_CUBIC)
    # # If you would like to play around with the dsize dimensions and visualize the output, so that and uncomment this next line:
    # # rasterio.plot.show(resized_array)

    # # There are two approaches I can think of:
    # # 1. convert ndarray -> WAV and then WAV -> bytes (for wt)
    # # 2. skip the intermediary and just iterate through ndarray and convert to bytes
    # # Both seem to be producing the same (incorrect) output. That's something, but I'm not sure what.

    # # Approach 1. This is from [Reddit](https://www.reddit.com/r/synthesizers/comments/84rlal/need_help_with_a_weird_csv_to_audio_conversion/).
    # # Set up a temporary file where we can write the WAV data.
    # temp_file: tempfile._TemporaryFileWrapper[bytes] = tempfile.NamedTemporaryFile()
    # wave_data: wave.Wave_write = wave.open(temp_file.name, "wb")

    # # Define parameters for the wave file.
    # channels = 1  # 1 = mono, 2 = stereo
    # sample_width = 2
    # sample_rate = 44100
    # number_of_audio_frames = 0
    # compression_type = "NONE"
    # compression_name = "not compressed"
    # wave_data.setparams(
    #     (
    #         channels,
    #         sample_width,
    #         sample_rate,
    #         number_of_audio_frames,
    #         compression_type,
    #         compression_name,
    #     )
    # )

    # # Write each wave in the dataset's array into a temporary WAV file.
    # for waveform in resized_array:
    #     wave_data.writeframes(waveform)
    # wave_data.close()

    # # Now that the data is in a format we know how to work with (i.e., WAV), we read the WAV file frame by frame and put those bytes into a list.
    # databuffer: list[bytes] = []
    # with wave.open(temp_file, "rb") as wav_file:
    #     n_frames: int = wav_file.getnframes()
    #     sample_width: int = wav_file.getsampwidth()
    #     content: bytes = wav_file.readframes(n_frames * sample_width)
    #     databuffer.append(content)

    # # Approach 2
    # # databuffer: list[bytes] = []
    # # for current_wave in resized_array:
    # #     databuffer.append(b"".join(current_wave))

    # rasterio.plot.show(databuffer)
    # return databuffer


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
