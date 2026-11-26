# Changelog

## 3.0.0 — Image-to-Art and Animation-to-Art Studios (2026-11-25)

### Added
* Image-to-Art Studio in both editions: 30 conversion modes with distinct algorithms, measured glyph coverage
  (`glyph_masks.json`, 1,149 glyphs), integer shape matching, two-colour block optimisation, CIELAB colour engine,
  20 image adjustments, geometry, dithering, palettes (built-in, custom, favourites, import/export, from FIGlet
  fonts), presets, undo/redo, comparison views, cost estimates for large outputs, batch queue, typographic
  compositions, comparison exports and image projects.
* Image analysis with rule-based recommendations and Smart Optimize (9 presets, approximate quality metrics).
* Animation-to-Art Studio: GIF/WebP/APNG (desktop) and GIF/video (browser) → animated HTML, GIF, frame ZIPs,
  Bash/PowerShell ANSI players, WebM/MP4 where the browser can encode.
* Safe decoding: magic-byte sniffing, decompression-bomb and size limits, EXIF orientation, SVG sanitiser,
  built-in SVG rasterizer (desktop), built-in GIF decoder/encoder and baseline TIFF decoder (browser).
* CLI: `--image`, `--image-mode`, `--cols`, `--set`, `--analyze`, `--optimize`, `--animate`, `--formats`,
  `--list-image-modes`; `python -m leerbox` now dispatches CLI vs. GUI.
* Export: letter spacing; sextants drawn as exact rectangles in raster and SVG exports; SVG block elements as
  rectangles.
* 70 new Python tests, 225 new JS checks, 206 cross-edition image fixtures (all bit-identical), Image Studio
  benchmarks (`tools/benchmark_image.py`) and a WebGPU evaluation script.

### Changed
* The old "Image Art" text mode is superseded by the Image Studio (the original `imageart.py` API remains).
* The EXE now bundles NumPy (35.4 MB).

## 3.0.0 — Ultimate Edition (2026-11-25)

### V2.0 audit findings (addressed)
* V2 shipped 347 bitmap rasterizations of Noto/Lato/DejaVu/Liberation weights stored as uncompressed
  `0`/`1` strings (14.8 MB HTML) and **no genuine FIGlet fonts**; 13 hairline weights rendered as broken strokes.
* FLF/TLF import used full-width layout only (no smushing, no layout rules, no vertical layout).
* Arabic support joined only common letters: no lam-alef ligatures, no diacritics, no bidi (whole runs reversed).
* Input limited to 120 characters; exports limited to TXT/ANSI/HTML/SVG/PNG with a fixed vertical gradient.
* The V2 HTML contained two injected `<script src="//local.adguard.org…">` tags (saved from a browser
  with AdGuard), which made network requests and referenced a chatgpt.com URL — removed; V3 enforces a
  no-network CSP.
* Monolithic one-line code, no tests, no build process. V2 files are preserved in `legacy_v2/`.

### Added
* 601 genuine, de-duplicated FIGlet/TOIlet fonts with per-font source, author and license metadata
  (`FONT_MANIFEST.json`); strict-license build option.
* FIGfont 2.0 engine: smushing rules 1–6, universal smushing, kerning, vertical layouts, RTL, code tags,
  zipped fonts, wrapping, alignment, spacing, grapheme clusters, Unicode fallbacks — pyfiglet-verified.
* Independent Arabic engine (shaping, ligatures, diacritics, Persian/Urdu, digits, UAX #9 bidi) and 6 OFL
  Arabic raster fonts.
* Raster modes: half blocks, quarter blocks, Braille.
* 20-effect non-destructive pipeline with representability labels; deterministic shared PRNG.
* Image → ASCII/blocks/half-block colour/quarter/Braille with dithering and colour mapping.
* Unicode styles (30), encoders/decoders, text boxes, terminal/README banners, CLI headers.
* 15 export formats + JSON projects, rich clipboard, batch export, transparent/scaled raster export.
* Font management: fuzzy search, filters, favourites, recents, compare, ZIP import, collection export.
* Smart features: recommendations, unsupported-character detection, width warnings, auto-fit, curated
  and random designs, presets.
* Modular source tree, single-file builders for `.py` and `.html`, PyInstaller EXE build, headless CLI,
  92 Python tests + 123 JS checks, golden fixtures, benchmarks.

### Changed
* Python UI rebuilt as a three-panel dark workspace with background rendering and a virtualized gallery.
* HTML edition rebuilt; size reduced from 14.8 MB to 3.75 MB.
