# Manual validation

`tests/test_integration.py` proves every output is a structurally valid `.wt` file: correct header, legal dimensions, full int16 range. It can't tell you whether a wavetable *sounds* good or whether a synthesizer will actually load it. Run this checklist before tagging a release, and after any change to the conversion pipeline (`loaders.py`, `converter.py`, `io_utils.py`).

## Rasters to convert

| Raster                                                                  | Why it's on the list                                                             |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif`           | Committed example; compare against `examples/lower-colorado.wt`                  |
| An SRTM 30m tile from [dwtkns.com/srtm30m](https://dwtkns.com/srtm30m/) | int16 source with a `-32768` nodata sentinel: exercises the float64 cast         |
| A coastal tile (ocean is nodata)                                        | Large nodata share: the mean-fill should not produce a silent table              |
| A tile smaller than 512 rows or 4096 columns                            | Exercises upscaling instead of downscaling                                       |
| A real scan or phone photo (JPEG), with and without `-c`                | Brightness (luma) path; listen for 8-bit grit and for the orientation difference |

```bash
geotiff-to-wavetable examples/USGS_OPR_AZ_2021LowerColoradoTB_C23_LCR_000002.tif -o /tmp/lower-colorado.wt
cmp /tmp/lower-colorado.wt examples/lower-colorado.wt && echo "byte-identical to the committed example"
```

A byte difference from the committed example isn't automatically a regression, since pipeline changes are expected to shift it. It means you need to listen before you ship, then regenerate the example as the new baseline. (For scale: the float64 pipeline change moved 1.8% of samples by ±1 least significant bit, which is inaudible.)

## Listening

For each output:

- [ ] **Bitwig Studio** loads it without error (Polymer → Wavetable oscillator → My Library; see the README's *Importing into Bitwig*).
- [ ] **Surge XT** loads it (drag the file onto the oscillator). Surge wrote the `.wt` spec, so it's the reference parser.
- [ ] Sweeping the wavetable position moves audibly through the table; it isn't one static timbre.
- [ ] No constant DC thump or silence at either end of the sweep (a sign nodata fill or normalization went wrong).
- [ ] No harsh clicks at the frame boundaries beyond what the terrain itself implies.
- [ ] Compared against the previous release's output of the same raster: any difference is one you expected.
