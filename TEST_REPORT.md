# Test Report — LeerBox Text Art Studio 3.0

Environment: Windows 11 Pro 10.0.26300, Python 3.13.17, Node.js v26.13.0, Pillow 13.0.0, pyfiglet 1.0.4,
python-bidi 0.6.12, arabic-reshaper 3.1.0, NumPy 2.5.4. Date: 2026-11-25. All results below come from actual runs.

## Summary

| Suite | Result |
|---|---|
| Python test-suite (`tests/`, pytest) | **162 passed, 0 failed, 0 skipped** (≈26 s; 92 Text Studio + 70 Image/Animation Studio) |
| JavaScript engine suite (`node tests/js/run_tests.js`) | **348 checks passed, 0 failed** (123 Text Studio + 225 Image Studio) |
| Image Studio cross-edition (Python vs JavaScript) | **206 / 206 cases bit-identical** (146,748 cells: characters, foreground and background colours) — 6 images × 30 modes plus 26 parameter variations (adjustments, geometry, dithering, colour engines, words/RTL/wide characters); analysis recommendations identical on 4 images |
| pyfiglet reference compatibility | **2,689 / 2,689 cases identical** (543 fonts × 5 strings) in **both** editions |
| Cross-edition consistency (Python vs JavaScript) | **95 / 95 render cases identical** (TXT + ANSI true-colour/256/16, width, height) plus Arabic, styles, encoders, boxes, 8 image conversions, fuzzy scores and search order |
| Browser (Chromium, desktop-app pane, http://localhost) | boots in ≈324 ms, Web Worker active, all 16 export formats produce valid files, gallery lazy-renders, no console errors |
| Desktop UI (Tk, driven by `tools/ui_screenshot.py`) | all 5 modes and 3 views exercised and screenshotted, no exceptions |
| Standalone script (`python -I`, isolated folder) | output identical to the modular engine; PNG export and font listing work |
| Browser Image/Animation Studio (Chromium, browser pane) | image decode (PNG via canvas, sanitised SVG), 30-mode rendering in the Web Worker, analysis and Smart Optimize dialogs, all 15 export formats from image art, GIF animation decode → convert → animated HTML / GIF / PNG ZIP / Bash script, WebM recording via MediaRecorder; unsafe SVG rejected; no console errors |
| Desktop Image/Animation Studio (Tk, `tools/ui_screenshot.py`) | image loading, mode switches, slider and side-by-side views, animation conversion and playback screenshotted; standalone script (`python -I`) opens both workspaces and renders |
| Windows EXE | built (35.4 MB, includes NumPy); **blocked by Smart App Control** on this machine (unsigned binary) — not launched. An earlier Text Studio build ran before SAC blocked rebuilds |

## Python suite by area

| File | Tests | Covers |
|---|---|---|
| `test_figlet.py` | 22 | pyfiglet golden comparison; FLF/TLF parsing, Latin-1 FLF, UTF-8 TLF, zipped fonts, hex/octal/decimal/negative code tags, missing-Deutsch detection, old→full layout derivation, hardblanks; malformed/oversized fonts rejected; every smushing rule incl. universal; layout width ordering; vertical smushing; wrapping; alignment; RTL; Unicode fallback; graphemes/wide chars; input limit |
| `test_arabic.py` | 20 | contextual forms, right-joining breaks, lam-alef (4 variants + disabled), transparent diacritics, Persian letters, ZWNJ, tatweel; bidi classes, pure RTL, numbers, mixed paragraphs, bracket mirroring, marks stay with base; **8 strings identical to python-bidi**, **6 strings identical to arabic-reshaper**; digit conversion; all 6 Arabic raster fonts render and cover the test text; diacritics add ink and can be stripped |
| `test_fonts_security.py` | 16 | pack counts = manifest (≥ 400); every one of the 937 fonts parses and renders; no duplicate glyph sets; metadata completeness; search/fuzzy; import → persist → reload → remove; duplicate-of-built-in rejected; malformed imports rejected; ZIP import with path traversal (`../`, `C:/`) and zip-bomb ratio rejected; invalid ZIP; collection export round-trip; reset; control-character stripping; HTML/SVG escaping; colour-value validation; imported font containing ESC sequences cannot inject them |
| `test_effects_export.py` | 27 | all 20 effects run non-destructively; disabled effects; order sensitivity; mirror/flip/rotate identities (**found and fixed a real bug**: rotation map was not a 4-cycle for parentheses); gradient endpoints; PRNG reference values; determinism of random effects; representability flags; size limit; **all 15 export formats valid** (Pillow `verify()`, XML parse); transparent PNG alpha; scale doubles resolution; no-Pillow PNG/BMP fallback; ANSI 24-bit/256/16; source literals executed: **Python, JavaScript (node), PowerShell (pwsh), Bash** reproduce the text byte-for-byte; Markdown fences; image conversion monotonicity, 5 modes × 4 dithers, colour, invert, Pillow loader; project round-trip, malicious project sanitation, rejection; Unicode styles, encoder round-trips, Braille, box alignment |
| `test_distributions.py` | 7 | standalone script output equals modular engine (FIGlet + Arabic); PNG + listing; no network imports / eval in the script; HTML self-contained (CSP present, no external `src`/`href`, no AdGuard injection, no `unsafe-eval`), no eval/new Function; size < 8 MB; Node suite passes |

## Image Studio suite (`test_image_studio.py`, 70 tests)

Decoding of PNG, JPEG, WebP, BMP, GIF, TIFF, ICO and AVIF written by Pillow (magic-byte detection, pixel check);
EXIF orientation (rotate-90 JPEG); transparency; decompression-bomb limit; 5 malformed inputs; HEIF reported as
needing pillow-heif; 7 unsafe SVGs rejected (script, event handler, entity expansion, external image,
foreignObject, external url(), @import); safe SVG rasterized with correct colours and transparency; animated GIF
frames, durations, frame skipping (timing preserved) and fps override; aspect-ratio compensation (cell aspect,
Braille/sextant sub-pixels, double-width emoji cells, automatic fit); rotate ×4 identity, flips, crop, free
rotation, padding; area resampling preserves the mean; all 20 adjustments change the image, stay in range and never
modify the source; background removal; Sobel/Canny/edge-mode orientation glyphs; dithering preserves average
density (Atkinson within its known 6/8 error loss); Otsu and equalization; measured density ordering; **Braille dot
→ code point mapping for all 8 dots**; quadrant and sextant mapping (all 64 sextant patterns unique, masks agree
with bits, two-colour split gives exact colours); palette library, reversal, custom palettes, JSON import/export
with control-character stripping, FIGlet-derived palette; glyph matcher (full, empty, vertical-bar cells); **all
30 modes on all 8 representative images** (portrait, landscape, logo, drawing, high-contrast, transparent,
16×12 low-res, 1200×800 large photo); all 30 modes produce distinct output; colour engine (every colour mode,
ANSI 16/256 palettes respected, grayscale neutral, only SGR escape sequences with resets); custom words (Latin,
word layout, Arabic shaping, CJK continuation cells); cost estimates; analysis metrics and recommendations; all 9
Smart Optimize presets (sorted scores, SSIM range); exports of image art in all 15 formats (Pillow verify, SVG
parse, sextant rectangles, letter spacing); animation exports (HTML with CSP, 2-frame GIF, frame ZIP, Bash script
escape whitelist, PowerShell); typographic composition PNG/SVG; comparison PNG; image project round trip and
rejection of invalid base64 / foreign files; parameter sanitation (NaN, control characters, path-like mode);
batch conversion with failure report; CLI (`--image`, `--analyze`, `--set … --format png`); no network modules or
eval in the image modules (both editions); the JS image engine matches Python (runs `tests/js/image_tests.js`).

## JavaScript suite

Pure-JS inflate equals zlib on the 22.8 MB pack; raw inflate; decompression-bomb limit; font count;
pyfiglet reference (2,689); cross-edition renders (95 × 4 encodings); Arabic shape/visual/visual-rtl/
visual-ltr for 11 strings; 30 Unicode styles; 8 encoders; 4 box styles; 8 image conversions; 8 fuzzy
scores; 5 search orderings; mulberry32 reference; ZIP round-trip and path-traversal rejection; control-
character stripping; HTML escaping; malformed font and project rejection; project sanitation; every one
of the 937 built-in fonts renders; duplicate import rejected.

Image Studio (`tests/js/image_tests.js`): 206 cross-edition render cases; analysis recommendations for 4 images;
Braille dot map; sextant mapping; density ordering; GIF encoder/decoder round trip (frame count, timing, loop,
palette error ≤ 40/255); **built-in GIF decoder equals Pillow's frames** (disposal 2, transparency, interlacing);
**built-in TIFF decoder equals Pillow** for uncompressed, LZW and PackBits; SVG sanitiser (5 rejections, 1
acceptance); ANSI output contains only SGR sequences; image project round trip and rejection; parameter
sanitation.

## Reference deviations (documented, not failures)

35 pyfiglet comparisons are excluded, each classified automatically by `tools/gen_golden.py`; any
difference that matches no rule would be kept as a failing case (there are **0 unexplained** differences):

| Count | Reason |
|---|---|
| 23 | pyfiglet 1.0.4 drops glyphs that are blank or hardblank-only (e.g. `%#%` in `knob` → `%%`); figlet 2.2.5 keeps them for width/smush bookkeeping, as LeerBox does |
| 7 | fonts `konto`, `konto_slant` (pyfiglet decodes Latin-1 as UTF-8 → `�`), `ivrit`, `jerusalem`, `mirror`, `mshebrew210` (pyfiglet right-pads RTL output to the terminal width), `3d-ascii` (zero-width glyph) |
| 3 | pyfiglet crashes (`IndexError: string index out of range`) on the punctuation test string |
| 2 | bundled font revision is newer than the copy inside pyfiglet 1.0.4 |

## Bugs found and fixed by the tests

* Rotation character map was not a 4-cycle for `(`/`)` (four 90° rotations did not restore the art) — fixed in both editions.
* Braille capitalisation diverged for non-ASCII capitals between editions, and Python raised on non-ASCII digits — unified.
* Code-literal test used WSL's `bash.exe` with a Windows path — test now pipes via stdin.
* Font de-duplication merged `ivrit` into `standard` (identical ASCII, different direction) and downgraded license tiers on superseding — key now includes direction/layout; merges never downgrade the license tier.
* Pillow 13 does not auto-register the WebP encoder on `save()` — `Image.init()` added.

## Not tested / environment-limited

* Brave, Edge and Firefox (only Chromium was available); the HTML `file://` Web-Worker fallback path (the
  browser pane cannot open `file://`); IndexedDB persistence across browser restarts.
* C/C++ literal compilation (no compiler installed).
* HEIC/HEIF decoding (pillow-heif not installed; Chromium cannot decode HEIC) — only the "decoder missing" path is tested.
* Browser video *decoding* with a real video file (WebM *recording* was tested); AVIF/ICO/TIFF decoding in browsers
  other than Chromium; clipboard image paste (needs a real user gesture).
* Desktop Image Studio interaction is scripted (programmatic actions + screenshots), not manual; desktop
  drag-and-drop does not exist (Tk limitation).
* The current EXE launch (blocked by Smart App Control; requires code signing).
* Clipboard writes were exercised through the UI code paths but not read back from the OS clipboard.
* Interactive desktop UI testing was scripted (programmatic actions + screenshots), not manual.

## How to reproduce

```powershell
pip install -r requirements-dev.txt
```

```powershell
.\build.ps1 test
```

```powershell
node tests/js/run_tests.js
```

```powershell
python tools/benchmark_image.py
```
