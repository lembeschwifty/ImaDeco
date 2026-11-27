
# ImaDeco

**Quick start:** from the project root, run
`python -m imadeco decode your-image.jpg` to see an image's metadata, or
`python -m imadeco convert your-image.gif -o out.png` to convert it to PNG.
Damaged file? `python -m imadeco salvage your-image.png -o out.png` recovers
what's left of it, and `python -m imadeco verify your-image.png` tells you
exactly what's wrong with it.

**In one sentence:** ImaDeco (IMAge DECOder) is a command-line tool that
tells you what an image file really is, verifies whether it is damaged,
recovers what is left of broken files, and converts it to PNG, using
nothing but Python itself, no installs, no dependencies.

Version 0.2.0.

## What it does

- **Identify and inspect** JPEG, PNG, BMP and GIF files: real format (by
  content, not filename), dimensions, color type, bit depth, frame count and
  more.
- **Convert** any supported image to a standard PNG.
- **Fail helpfully**: corrupt, truncated or unsupported files produce one
  clear error line, not a crash.
- **Inspect** (`python -m imadeco inspect FILE`): a bitstream-level report,
  the actual chunks or segments inside the file, with offsets and sizes.
- **Verify** (`python -m imadeco verify FILE`): strict structure checking
  with clear OK / WARN / FAIL verdicts. Works on whole directories at once.
- **Salvage** (`python -m imadeco salvage FILE -o out.png`): best-effort
  recovery of damaged files. A truncated image yields a partial PNG with
  every row that survived.

## Requirements

Python 3.10 or newer. Nothing else; there are no packages to install.

## Run it

From the project root (the folder containing `imadeco/`):

```bash
# Show an image's metadata (human-readable)
python -m imadeco decode photo.jpg

# Same metadata, as JSON (for scripts)
python -m imadeco decode photo.jpg --json

# Convert any supported image to PNG
python -m imadeco convert photo.jpg -o photo.png

# See inside the file: chunks/segments with offsets and sizes
python -m imadeco inspect photo.jpg

# Strictly check one file, several files, or a whole directory
python -m imadeco verify photos/

# Recover what's left of a damaged file (exit code 3 = partial)
python -m imadeco salvage damaged.png -o recovered.png
```

Note: `python -m imadeco` must run from the project root. From anywhere
else, add the project root to `PYTHONPATH` first.

## Example: what you see, format by format

JPEG (this is a real fixture file, a JPEG despite its .webp name,
which ImaDeco identifies correctly):

```text
IMG_9736.webp: 720 x 416
  Format: JPEG
  Pixel layout: RGB
  Precision: 8
  Sampling: [(1, 2, 2), (2, 1, 1), (3, 1, 1)]
  Restart interval: 45
```

PNG:

```text
demo.png: 2 x 2
  Format: PNG
  Pixel layout: L
  Bit depth: 8
  Color type: 0 (grayscale)
  Interlaced: False
```

BMP (8-bit paletted):

```text
demo.bmp: 3 x 2
  Format: BMP
  Pixel layout: RGB
  Bits per pixel: 8
  Top-down rows: False
  Compression: BI_RGB
  DIB header size: 40
```

GIF:

```text
demo.gif: 3 x 2
  Format: GIF
  Pixel layout: RGB
  GIF version: GIF89a
  Frames: 1
  Interlaced: False
  Transparent index: None
  Canvas size: 3x2
```

And a conversion:

```text
$ python -m imadeco convert demo.gif -o demo.png
demo.gif (GIF) -> demo.png (3x2, RGB, 77 bytes)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (for `salvage`: the file was intact) |
| 1 | File or decode error (bad path, unsupported format, corrupt data); for `verify`, at least one file failed |
| 2 | Usage error (bad command or arguments) |
| 3 | `salvage` only: recovered a partial image with some loss |

## Supported formats and known limits

| Format | Decodes | Notes |
|---|---|---|
| JPEG | Baseline (SOF0), 8-bit | Progressive JPEG is rejected with a clear message |
| PNG | Color types 0/2/3/4/6, depths 1/2/4/8 (16-bit reduced to 8) | Adam7 interlacing not supported yet |
| BMP | 1/4/8/24/32 bpp, top-down or bottom-up | Compressed BMPs (RLE etc.) not supported yet |
| GIF | LZW, first frame, interlace, transparency | Later frames are counted, not decoded |
| JPEG salvage | not yet | The compressed stream has no row-aligned recovery point; planned for a later release |
| GIF salvage | non-interlaced frames only | Interlaced-frame salvage is planned for a later release |

Output is always PNG: 8-bit grayscale, RGB or RGBA.

Known behavior: `convert` overwrites an existing output file without
asking (standard command-line convention).

## Troubleshooting

**"Unsupported file type"** - the file's first bytes don't match any known
format. The file is probably not actually an image, or a format ImaDeco does
not read (e.g. WebP or TIFF).

**"Corrupt..." / "truncated..."** - the file matches a supported format but
its data is cut short or invalid. Re-obtain the file; if it opens in a
viewer, it may use a feature listed under known limits above.

**Conversion stopped with an error** - check the output name: ImaDeco only
writes `.png` files.

**Salvage says a file is unrecoverable** - nothing survived above the row
level: the header itself is broken, or no complete pixel row remains. For
JPEG, salvage is not implemented yet (see known limits).

**Large or odd files** - decoding is pure Python, so big photos take a few
seconds. Decompression is capped at the size the header declares, so a
crafted "zip bomb" image fails fast instead of consuming memory.

## For developers

Zero third-party dependencies by design (ADR: stdlib-only). One format per
module behind a common decoder interface; new formats plug in without
touching existing code.

Module map:

```text
imadeco/
  cli.py            # command line: decode / convert / inspect / verify / salvage
  registry.py       # magic-byte detection and the decoder registry
  report.py         # structure reports shared by inspect and verify
  models.py         # DecodedImage: the uniform decoded-image representation
  exceptions.py     # error hierarchy (unsupported / corrupt / out-of-scope)
  decoders/
    jpeg.py         # baseline JPEG: Huffman, IDCT, restart markers, subsampling
    png.py          # chunks, zlib, all 5 scanline filters, tRNS
    bmp.py          # DIB headers, palettes, top-down rows, row padding
    gif.py          # LZW, interlace, transparency, frame counting
  encoder/
    png.py          # minimal 8-bit L/RGB/RGBA PNG writer
tests/              # 60 tests, incl. independent fixture writers
```

Each decoder module also exposes `walk()` (the bitstream structure report
used by inspect and verify) and, where supported, `salvage()` (lenient
recovery of damaged files).

Adding a new format is one file and a decorator (this exact pattern is
verified):

```python
from imadeco.models import DecodedImage
from imadeco.registry import Decoder, register

@register(b"\x89MY", "MYFORMAT")     # the file's magic bytes
class MyDecoder(Decoder):
    format_name = "MYFORMAT"

    @classmethod
    def decode(cls, data: bytes) -> DecodedImage:
        ...  # parse data, return DecodedImage(pixels, w, h, color, metadata)
```

Import the new module in `imadeco/decoders/__init__.py` and it is
automatically detected and routed. Tests use independent fixture writers
(simple, hand-built files) so decoders are never validated only against
themselves.

```bash
python -m unittest discover -s tests
```

## Security note

No network access, no dynamic code execution, no secrets. All parsers are
bounded by declared sizes; the PNG decompressor is capped at exactly the
size the header allows, so decompression-bomb images fail fast (covered by
dedicated tests).

## License

MIT. See `LICENSE` in this repository.
