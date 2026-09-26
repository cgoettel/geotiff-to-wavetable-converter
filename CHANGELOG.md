# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - Unreleased

### Added

- **Images and scans.** Photos and scans (JPEG, PNG, WebP, BMP, GIF, TIFF) convert by brightness (Rec. 709 luma) by default. `-b 1/2/3` picks a single color channel, palette images convert through their color table, and alpha is ignored.
- `-c`/`--columns` reads the raster left to right, one column per wave frame.
- `-i` lists each band's color interpretation, for example `Bands: 3 (red, green, blue)`.
- `python -m geotiff_to_wavetable` works as an alternative to the `geotiff-to-wavetable` command.
- `load_from_geotiff` and `array_to_wavetable` split reading a raster from converting it, so new source formats can reuse the conversion.

### Changed

- **Breaking:** `convert_geotiff_to_wt` is removed. Use `array_to_wavetable(load_from_geotiff(dataset, band), nodata=dataset.nodata)`.
- RGB rasters, including color GeoTIFFs such as aerial photos, default to brightness instead of the red band. `-b 1` gives the previous output.
- The conversion runs in float64 throughout, so integer rasters (such as SRTM int16) no longer truncate during nodata filling.
- The georeferencing warning is no longer printed for sources without map coordinates.

### Fixed

- Without `-o`, the output path was cut at the first dot anywhere in the path: `./dem.tif` wrote a hidden `.wt`, `v1.2/dem.tif` wrote `v1.wt` in the parent directory, and `dem.v2.tif` overwrote `dem.wt`. Only the extension is replaced now.
- A flat band (every value equal) wrote a silent wavetable. It now exits with an error.
- An all-nodata band exited with a traceback. It now exits with an error message.
- `-b 0` was silently ignored and negative bands crashed. Both now exit with an error.

## [0.1.1] - 2026-01-05

Documentation cleanup for PyPI. (0.1.0, the first PyPI release, went out the same day.)

[0.1.1]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/commit/1b83917
[0.2.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/1b83917...main
