# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.8.0] - 2026-10-04

### Added

- `--clip-percentile` and `--cap-percentile` move where `--surface clipped` and `capped` cut, from above 0 up to 100 (default 90) (#34). They're refused with any other surface, so a setting is never silently ignored. `load_lidar_surface` takes matching `clip_percentile` and `cap_percentile` arguments.

## [0.7.0] - 2026-10-04

### Added

- `--fill mean|interpolate` chooses how gaps are filled: nodata in a raster, or LiDAR cells no point landed in (#33). `interpolate` estimates each gap from the cells around it, so it follows the terrain. `mean` uses the average of the valid data, which leaves a spike or a pit in every gap on a slope. `array_to_wavetable` takes a matching `fill` argument, and `interpolate_gaps` is exported.

### Changed

- Gaps are interpolated by default, in the CLI and in `array_to_wavetable`. Compared by ear on all three example places, the sound barely changes, but the tables look like the land, without the spikes or flat bands the mean left. `--fill mean` (or `fill="mean"`) restores the old behavior.

## [0.6.0] - 2026-10-04

### Added

- `--surface clipped`: `canopy` with its tallest 10% cut flat, so a few big trees can't take the whole range (#32).
- `--surface capped`: the ground's shape, with each tree or building's height above it capped at the 90th percentile of those heights, so hilltops survive (#32).
- `--surface all` writes every surface to its own file, lettered so they sort together and in order: `river-a-ground.wt` through `river-e-capped.wt`. A surface that comes out flat is skipped with a warning.
- `load_lidar_surface(points, surface)` makes any surface from the library, and `SURFACES` lists them.
- `examples/portland-downtown.laz` and `examples/portland-downtown.tif`: a 250 m square of downtown Portland, Oregon at the foot of the West Hills, as a LiDAR point cloud (1.54 million points, 2019) and the matching USGS 1 m elevation model. The ground slopes only 14 m, but the towers rise up to 132 m above it. A city is built on a boring plot of land, and its buildings make the sound interesting. Public domain, cropped from the [USGS 3DEP copies on AWS](https://registry.opendata.aws/usgs-lidar/).

### Fixed

- LiDAR noise (classes 7 and 18: stray returns from birds, haze, and the sensor) is left out of every surface. In 0.5.0, `--surface blended` and `canopy` kept it, so one high-noise return far above the tallest building could set the top of the range. Downtown Portland has 699 of them, reaching 195 m.

## [0.5.0] - 2026-10-04

### Added

- `--surface ground|blended|canopy` chooses which LiDAR surface to play (#30). `ground` (the default) is the bare earth, `blended` averages every point so trees and buildings rise softly out of it, and `canopy` takes the top of each spot. `load_from_lidar` gains a `cell_value` argument (`mean` or `highest`) to go with `classes`.
- `--verbose` and `--debug` print progress and diagnostics to stderr.

### Fixed

- The command no longer writes `geotiff_to_wavetable.log` into whatever directory it runs from (#31). Warnings and errors still print to the terminal, and `--verbose`/`--debug` show the rest.

## [0.4.0] - 2026-10-03

### Added

- **LiDAR point clouds.** LAS and LAZ files convert directly. Ground points (class 2) are binned onto a grid with cells three times the average point spacing, each cell takes their mean elevation, and empty cells (mostly water) are filled like nodata. On the example, the result matches the GeoTIFF to a median of 9 mm. `-i` lists the point count per class, and `-v` shows the grid. `load_from_lidar` is the library entry point, and takes `classes` and `cell_size` arguments (#19).
- `examples/lower-colorado-lcr-000002.laz`: the LiDAR point cloud behind the example GeoTIFF, covering the same ground at full density (2.05 million points, ground and unclassified returns). It's cropped from the public-domain [USGS 3DEP copy on AWS](https://registry.opendata.aws/usgs-lidar/) and stored in Web Mercator (EPSG:3857).

### Changed

- README: an *Installation* section (uv or pipx from PyPI, or straight from the repository for unreleased changes).
- GitLab CI runs the tests and the pre-commit hooks (ruff, mypy) on every merge request and every push to `main`. Before, the tests only ran in CI when a release tag published to PyPI.
- CI jobs retry up to twice when the runner itself fails, such as when GitHub's container registry rate-limits the image pull. A failing test still fails the first time.

## [0.3.1] - 2026-09-26

### Changed

- Depend on `opencv-python-headless` instead of `opencv-python`. The converter only uses OpenCV to resize arrays, never its windows, so the headless build is a smaller install and needs no system graphics libraries (it now installs cleanly on servers and slim containers). If you installed `opencv-python` separately, both can coexist.
- Package metadata declares its license as the SPDX expression `MIT` ([PEP 639](https://peps.python.org/pep-0639/)) and bundles `LICENSE`, replacing the deprecated table form and trove classifier that setuptools will stop accepting.

## [0.3.0] - 2026-09-26

### Added

- **WAV output for hardware samplers.** `-f`/`--format` takes `wt`, `wav`, or both (`-f wt,wav`). The WAV is mono 16-bit 44.1 kHz with every frame laid end to end, sample-for-sample the same data as the `.wt`, so samplers like the M8, MPC, and OP-1 play it as a scan through the table. `write_wav_file` is exported for library use.
- README: a *Hardware samplers* section (playback modes, how `-w` sets pitch and length), and the data sources ranked with SRTM 30m first.

## [0.2.0] - 2026-09-26

### Added

- **Images and scans.** Photos and scans (JPEG, PNG, WebP, BMP, GIF, TIFF) convert by brightness (Rec. 709 luma) by default. `-b 1/2/3` picks a single color channel, palette images convert through their color table, and alpha is ignored.
- `-c`/`--columns` reads the raster left to right, one column per wave frame.
- `-w`/`--wave-size` sets the samples per wave frame (a power of 2 from 2 to 4096), trading detail for crunch and file size. `array_to_wavetable` takes a matching `wave_size` argument.
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
- `validate_wave_size` raised a math domain error on 0 and negative numbers instead of returning `False`.

## [0.1.1] - 2026-01-05

Documentation cleanup for PyPI. (0.1.0, the first PyPI release, went out the same day.)

[0.1.1]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/commit/1b83917
[0.2.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/1b83917...v0.2.0
[0.3.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.2.0...v0.3.0
[0.3.1]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.3.0...v0.3.1
[0.4.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.3.1...v0.4.0
[0.5.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.4.0...v0.5.0
[0.6.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.5.0...v0.6.0
[0.7.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.6.0...v0.7.0
[0.8.0]: https://gitlab.com/colby.goettel/geotiff-to-wavetable-converter/-/compare/v0.7.0...v0.8.0
