# GeoTIFF to wavetable converter

This is a utility to convert GeoTIFF files to wavetable files (`.wt`) for use in synthesizers.

Yes, this is an absolutely wild idea and I don't even know if it's going to work. I've never worked with GeoTIFF and my wavetable experience is limited. We can totally figure this out.

If you'd like to help or if you've noticed some issues, please see the [CONTRIBUTING guide](CONTRIBUTING.md) for information about how to go forward.

## Usage

For these examples, we'll use a GeoTIFF of the Oro Valley in Arizona (`examples/USGS_1_n33w111_20240401.tif`). There's also a GeoTIFF of the lower Colorado river in there for you to check out. For more geospatial data, check out [the sources below](#finding-geospatial-data).

The tool automatically:

- Replaces nodata values (like -999999) with the mean elevation
- Resizes your terrain to valid dimensions (width: power of 2 between 2–4096, height: max 512)
- Normalizes elevation values to audio range (-32768 to 32767 for int16 format)

### Basic conversion

Convert a GeoTIFF file to a wavetable:

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif
```

This creates `examples/USGS_1_n33w111_20240401.wt` (in the same directory as your input file). The tool will automatically handle nodata values (like oceans or missing data) and resize your terrain to valid wavetable dimensions.

### Options

**Usage info:**

```bash
geotiff-to-wavetable -h
```

**Specify an output file:**

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif -o output.wt
```

**Select a specific band** (if your GeoTIFF has multiple bands):

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif -b 2
```

Most elevation data only has one band, so you won't need this option. Use `-i` to see how many bands your file has.

**View file information** (bands, width, height):

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif -i
```

**Visualize the data** before converting:

View the default band:

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif -v
```

View a specific band:

```bash
geotiff-to-wavetable examples/USGS_1_n33w111_20240401.tif -b 2 -v
```

This opens a plot showing your elevation data. It's a helpful first step to make sure Python can read your file and that it contains the terrain you expect. If it doesn't look right, make sure to check how many bands there are (`-i`) and then view the other bands.

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

You can also drag your wavetable file into the wavetable part of the oscillator.

## Finding geospatial data

Some sources for dense GeoTIFF data:

1. [USGS Elevation](https://apps.nationalmap.gov/downloader/)
    - Filter by: GeoTIFF, Elevation Products (DEM)
    - Choose interesting terrain: mountains, canyons, volcanoes
    - 1-arc-second resolution is good
1. [OpenTopography](https://opentopography.org/)
    - High-resolution LiDAR elevation data
    - Great for detailed terrain
    - Requires free account
1. [SRTM (Shuttle Radar Topography Mission)](https://dwtkns.com/srtm30m/)
    - Global elevation data, 30m resolution
    - Has an easy browser
    - Download tiles covering interesting places
1. [NASA ASTER GDEM](https://asterweb.jpl.nasa.gov/gdem.asp)
    - Global elevation
    - Higher resolution than SRTM

> 💡 **Pro tips**
>
> - Avoid: Ocean/water data, cloud/atmospheric data, sparse measurements
> - Look for: Elevation (DEM), bathymetry, land surface temperature
> - Interesting terrain: Iceland volcanoes, Grand Canyon, Himalayas, Hawaiian islands

### An example of getting a GeoTIFF from USGS

1. Go to [their site](https://apps.nationalmap.gov/downloader/)
1. Zoom in on an area or search (upper right of the map). I have found that larger areas work better for finding results and then you can scroll through until you see something interesting.
1. On the left, you should be in the Datasets tab. Select "Elevation Source Data (3DEP) - Lidar, IfSAR". Within that, you can select File Formats "TIFF" (I want to add LiDAR support in a future update)
1. You might need to scroll up. Click the "🔍 Search Products" button. This will bring you to the Products tab.
1. You can now scroll through the available images. If nothing returns, try increasing your area. For example, I couldn't find anything for Kauai. I zoomed out and couldn't find anything for the Hawaiian Islands. So I zoomed out and got stuff for the Aleutian Islands ([copyright is commercial for Alaska](https://www.usgs.gov/faqs/are-usgs-topographic-maps-copyrighted) which is why we're using Arizona for our `examples/`).
1. Find something that looks interesting and click the "Download Link (TIF)" link (it might be "Download Link (ZIP)" and then you'll need to unzip and might have multiple TIFs to play around with).
