# GeoTIFF to wavetable converter

This is a utility to convert GeoTIFF files to wavetable files (`.wt`) for use in synthesizers.

Despite the name, GeoTIFFs aren't the only way in: photos and scans (JPEG, PNG, WebP, and more) work too. Scan a poster, a wall, or a texture and play it. See [Images and scans](#images-and-scans). LiDAR point clouds (`.las`, `.laz`) work as well. See [LiDAR point clouds](#lidar-point-clouds).

I've never worked with GeoTIFF and my wavetable experience is limited. Huge shout-out to both [`okwt`](https://github.com/drzhnn/okwt/tree/main) and [`surge`](https://github.com/surge-synthesizer/surge/tree/main) for their helpful implementations.

If you'd like to help or if you've noticed some issues, please see the [CONTRIBUTING guide](CONTRIBUTING.md) for information about how to go forward.

## Installation

The tool is on [PyPI](https://pypi.org/project/geotiff-to-wavetable/) and needs Python 3.10 or newer. Install it as a standalone command with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install geotiff-to-wavetable
```

Or with [pipx](https://pipx.pypa.io/): `pipx install geotiff-to-wavetable`. Either one puts `geotiff-to-wavetable` on your path in its own environment, so its dependencies don't touch anything else. Check that it worked with `geotiff-to-wavetable -h`.

To upgrade later, run `uv tool upgrade geotiff-to-wavetable`. To try changes that haven't been released yet, install straight from the repository:

```bash
uv tool install --force git+https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter
```

## Usage

For these examples, we'll use the GeoTIFF of the lower Colorado River that ships in `examples/`. For more geospatial data, check out [the sources below](#finding-geospatial-data).

The tool automatically:

- Replaces nodata values (like -999999) with the mean elevation, or, with `--fill interpolate`, with an estimate from the surrounding terrain
- Resizes your terrain to valid dimensions (width: power of 2 between 2–4096, height: max 512)
- Normalizes elevation values to audio range (-32768 to 32767 for int16 format)

### Basic conversion

Convert a GeoTIFF file to a wavetable:

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif
```

This creates `examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.wt` (in the same directory as your input file). The tool will automatically handle nodata values (like oceans or missing data) and resize your terrain to valid wavetable dimensions.

### Options

**Usage info:**

```bash
geotiff-to-wavetable -h
```

**Specify an output file:**

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -o output.wt
```

**Select a specific band** (if your GeoTIFF has multiple bands):

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -b 2
```

Most elevation data only has one band, so you won't need this option. Use `-i` to see how many bands your file has.

**Read columns instead of rows:**

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -c
```

By default, each row of the raster (top to bottom) becomes one wave frame. With `-c`/`--columns`, each column (left to right) does instead. It's the same data turned 90 degrees, and it makes a different instrument.

**Set the wave size** (samples per frame):

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -w 256
```

`-w`/`--wave-size` takes a power of 2 from 2 to 4096. By default it's the raster's width rounded up to a power of 2, capped at 4096. The number of frames still follows the raster's height, capped at 512. How to choose:

- **Sound:** fewer samples per frame means less detail in each waveform, which sounds crunchier and more lo-fi. At 8 or 16 samples the terrain is reduced to a handful of steps, and it sounds like it. Large sizes keep the fine texture of the land (or the scan).
- **File size:** the file is 2 bytes × wave size × frame count, so it scales directly with `-w`. A full 4096 × 512 table is about 4 MB, and `-w 256` on the same raster is about 256 KB.
- **Synthesizer support:** Surge reads anything from 2 to 4096. Some synthesizers resample every table to a fixed internal size (often 2048), so on those, very large sizes add file weight without adding detail.

**View file information** (bands and their colors, width, height):

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -i
```

**Visualize the data** before converting:

View the default band:

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -v
```

View a specific band:

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -b 2 -v
```

This opens a plot showing your elevation data. It's a helpful first step to make sure Python can read your file and that it contains the terrain you expect. If it doesn't look right, make sure to check how many bands there are (`-i`) and then view the other bands.

**See what it's doing:**

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif --verbose
```

By default the tool prints only warnings and errors. `--verbose` adds progress messages (what was read, how it was resized), and `--debug` adds detailed diagnostics. Everything goes to the terminal (stderr); nothing is written to a log file.

### Images and scans

Anything GDAL can read works as input: JPEG, PNG, WebP, BMP, GIF, and TIFF, georeferenced or not. A portable scanner and a city full of posters is a sample library.

```bash
geotiff-to-wavetable poster.jpg
```

How images are read:

- **Brightness by default.** Color images convert by their luma, the perceived brightness (Rec. 709: 0.2126 red + 0.7152 green + 0.0722 blue). Dark ink on light paper reads the way your eye sees it. Transparency (alpha) is ignored.
- **One color channel with `-b`.** On a color image, `-b 1`, `-b 2`, and `-b 3` pick red, green, and blue alone. The same poster can sound quite different through each one. `-i` lists which band is which color.
- **Indexed images** (most GIFs and some PNGs) are converted through their color table, so they convert by their actual colors.
- **Blank images are refused.** A scan with no variation at all, such as a white wall, would make a silent wavetable, so the tool exits with an error instead.

Scanning tips:

- **Resolution:** the output is at most 4096 samples wide and 512 frames tall, so 300 dpi is plenty for anything poster-sized.
- **Bit depth:** photos are usually 8-bit, which gives 256 brightness levels. That sounds a little stepped and gritty, which may be exactly what you want. For smoother tables, have the scanner save 16-bit TIFF.
- **Formats the tool can't read:** iPhone HEIC photos and PDFs from scanner apps need converting first, e.g. `magick scan.heic scan.png` ([ImageMagick](https://imagemagick.org/)).

### LiDAR point clouds

LAS and LAZ files, the raw laser returns behind most high-resolution elevation models, convert directly. `examples/` has the point cloud behind the example GeoTIFF:

```bash
geotiff-to-wavetable examples/lower-colorado-lcr-000002.laz
```

How point clouds are read:

- **Ground points by default.** Points classified as ground (class 2) are kept, and trees, buildings, and noise are dropped. On the example, this matches the GeoTIFF to within a centimeter.
- **`--surface` picks what to play.** Every surface except `ground` keeps all the points, minus noise (stray returns from birds, haze, and the sensor itself):
  - `ground` (the default): the bare earth.
  - `blended`: every point averaged, so trees, brush, and buildings rise softly out of the ground.
  - `canopy`: the top of each spot, so treetops and rooftops. Buildings come out as sharp-edged blocks, which play as square waves.
  - `clipped`: `canopy` with its tallest 10% cut flat, so a few big trees can't take the whole range. It caps elevation, so on a hill it flattens the hilltop too.
  - `capped`: the ground's shape, with each tree or building's height above it limited to the 90th percentile of those heights. It keeps hilltops and still reins in the tallest trees and towers. Where a roof or crown hides the ground, the ground beneath is interpolated from the ground around it.
- **`--surface all` writes every surface at once,** each with a letter and name so they sort together: `river-a-ground.wt`, `river-b-blended.wt`, `river-c-canopy.wt`, `river-d-clipped.wt`, `river-e-capped.wt`. In Bitwig's Polymer, filter the wavetable browser on the name (`river`) and click through them. A surface that comes out flat is skipped with a warning.
- **Which sounds best depends on the place:**
  - On the Lower Colorado river, trees up to 30 m tall stand over a riverbed that varies by only 3.5 m. `ground` sounds best there, and `clipped` is a close second.
  - On a forested mountainside, `clipped` and `capped` shine.
  - In `examples/portland-downtown.laz`, a city built on nearly flat land, the buildings are the sound. `canopy` is the city as it looks, and `clipped` adds character.
- **Gridded by density.** Points are binned onto a square grid with cells three times the average point spacing (about 1.2 m on the example), and each cell takes one elevation from its points. Row 0 is north and column 0 is west, the same as a GeoTIFF.
- **Gaps are filled.** Cells with no point, mostly water (which returns little of the laser) and ground hidden under trees or roofs, get the mean elevation by default, like nodata in a GeoTIFF. About 15% of the example is river. On a slope, the mean leaves a spike or a pit in every gap. `--fill interpolate` estimates each gap from the cells around it instead, so it follows the terrain (and bridges a river smoothly).
- **`-i` lists the classes.** It prints the point count and how many points are in each class, for example `Class 2 (ground): 1098401`. `-v` shows the grid the wavetable will be made from. `-b` doesn't apply, since point clouds have no bands.

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

### Hardware samplers (M8, MPC, OP-1, etc.)

Hardware samplers like the Dirtywave M8, Akai MPC, Teenage Engineering OP-1, and Polyend Tracker can't read `.wt` files, but they all play WAVs. Ask for one with `-f wav`:

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -f wav
```

Use `-f wt,wav` to get both from one run.

The WAV is mono, 16-bit, 44.1 kHz, with every wave frame laid end to end. It holds sample-for-sample the same data as the `.wt`. A wavetable synthesizer lets you choose which frame to play; a sampler plays straight through the WAV, so you hear the terrain (or the poster) evolving over time. Loop it and it keeps cycling.

- **Dirtywave M8:** load it into a Sampler instrument and set `PLAY` to `FWDLOOP`, or to `REPITCH`/`BPM` to lock it to the song.
- **Other samplers:** use a forward-looping playback mode. The file has no loop points in it; the sampler's own loop settings handle that.

**Pitch and length:** at 44.1 kHz, each frame of `N` samples repeats `44100 ÷ N` times a second, which sets the pitch you hear: 2048 samples gives about 21.5 Hz (a low rumble), 256 about 172 Hz, 128 about 345 Hz. So `-w` doubles as a tuning control. The file lasts `N × frames ÷ 44100` seconds: about 48 seconds at 4096 × 512, 3 seconds at 256 × 512. A sampler treats the whole file as one chromatic sample, so playing it higher speeds up the scan as well as raising the pitch.

## Finding geospatial data

Where to get elevation data, in the order to try them:

1. **Start here: [SRTM 30m tile browser](https://dwtkns.com/srtm30m/).** It's the fastest route to anywhere on Earth: click a 1° tile on a world map and download it. It covers nearly all land between 60° N and 56° S at 30 m resolution, including places the USGS downloader comes up empty for (Kauai and the rest of Hawaii download cleanly here). You need a free [NASA Earthdata login](https://urs.earthdata.nasa.gov/users/new) to download. SRTM tiles are int16 with a `-32768` nodata value, which the tool handles.
2. **Backup: [NASA ASTER GDEM](https://asterweb.jpl.nasa.gov/gdem.asp).** Also global and also 30 m, with wider coverage toward the poles (83° N to 83° S). Worth trying when SRTM has gaps, such as far-northern terrain or steep mountains.
3. **Deepest catalog: [OpenTopography](https://opentopography.org/).** High-resolution LiDAR, bathymetry, and more, for when 30 m isn't detailed enough. Requires a free account.
4. **United States, no account: [USGS National Map downloader](https://apps.nationalmap.gov/downloader/).** Filter by elevation products (DEM) in GeoTIFF format. 1-arc-second data is a good size. See the walkthrough below.

> 💡 **Pro tips**
>
> - Avoid: ocean/water data, cloud/atmospheric data, sparse measurements
> - Look for: elevation (DEM), bathymetry, land surface temperature
> - Interesting terrain: Iceland's volcanoes, the Grand Canyon, the Himalayas, the Hawaiian islands (via SRTM)

### An example of getting a GeoTIFF from USGS

1. Go to [their site](https://apps.nationalmap.gov/downloader/)
2. Zoom in on an area or search (upper right of the map). I have found that larger areas work better for finding results and then you can scroll through until you see something interesting.
3. On the left, you should be in the Datasets tab. Select "Elevation Source Data (3DEP) - Lidar, IfSAR". Within that, you can select File Formats "TIFF", or the LAS/LAZ format for the raw point clouds (see [LiDAR point clouds](#lidar-point-clouds)).
4. You might need to scroll up. Click the "🔍 Search Products" button. This will bring you to the Products tab.
5. You can now scroll through the available images. If nothing returns, try increasing your area. For example, I couldn't find anything for Kauai. I zoomed out and couldn't find anything for the Hawaiian Islands. So I zoomed out and got stuff for the Aleutian Islands ([copyright is commercial for Alaska](https://www.usgs.gov/faqs/are-usgs-topographic-maps-copyrighted) which is why we're using Arizona for our `examples/`).
6. Find something that looks interesting and click the "Download Link (TIF)" link (it might be "Download Link (ZIP)" and then you'll need to unzip and might have multiple TIFs to play around with).
