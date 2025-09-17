# GeoTIFF to wavetable converter

This is an absolutely wild idea I had and I don't know if it's even going to work. I've never worked with GeoTIFF and my wavetable experience is limited. We can totally figure this out. If you'd like to help or if you've noticed some issues, please see the [CONTRIBUTING guide](CONTRIBUTING.md) for information about how to go forward.

The purpose of this repository is to provide a Python script that can convert geospatial data (currently just GeoTIFF) to a wavetable file (in `.wt` format) so it can be used by a synthesizer.

## Usage

TODO

### Importing into Bitwig

Bitwig expects files to be in `~/Documents/Bitwig Studio/Library`, so copy your file into that directory and then you can source it from Bitwig's wavetable.

To validate that the file is available in Bitwig, copy the file to the Bitwig Library:

```bash
cp /path/to/your/file.wt ~/Documents/Bitwig\ Studio/Library
```

Then, in Bitwig:

- Create a new Instrument and add Polymer to it.
- Change your Oscillator to "Wavetable" and click on the wavetable.
- This will bring up the Wavetables selector. On the left, click "My Library" and you should see your wavetable there.

## Finding geospatial data

I'm not including any GeoTIFF files in this repository because I don't know how their license works with the license I'm using. If you know more about this, please comment on [this issue]()

You can download GeoTIFF data from a number of places. Here are some examples (not to get all Wikipedia on you, but you can help by expanding this):

1. [NASA](https://www.earthdata.nasa.gov/data/catalog) (be sure to filter by GeoTIFF)
1. [USGS](https://apps.nationalmap.gov/downloader/)
