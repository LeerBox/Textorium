# Performance Report — LeerBox Text Art Studio 3.0

Measured with `python tools/benchmark.py` (raw output: `dist/perf.json`) on Windows 11 Pro 10.0.26300,
Intel64 Family 6 Model 198, Python 3.13.17, Node.js v26.13.0. Single runs or small averages; expect ±20 %.

## Startup

| Measurement | Result |
|---|---|
| Python: font pack decompress + index (937 fonts) | 41 ms |
| Python desktop app: process start → first painted window (modular) | 733 ms |
| Standalone script: cold CLI render (process start → output) | 588 ms |
| HTML: navigation → interactive (Chromium, 3.75 MB page) | ≈324 ms |
| HTML: JS heap after boot | 84 MB |
| JS: pure-JS inflate of the 22.8 MB pack (fallback path) | 85 ms (native `DecompressionStream` is used when available) |

## Rendering

| Measurement | Python | JavaScript |
|---|---|---|
| Parse all 937 fonts (lazy in normal use) | 447 ms | 346 ms |
| Render "LeerBox" in all 937 fonts | 734 ms | 504 ms |
| Average per font | 0.78 ms | 0.54 ms |
| Arabic raster (Amiri, 22 chars, half blocks) | 0.90 ms | 0.48 ms |
| Effects pipeline (extrude + gradient + frame + glow) | 0.82 ms | 0.57 ms |
| Fuzzy search over 937 fonts | 0.72 ms | 1.08 ms |
| 176-char text, `standard` | 5.4 ms | — |
| Same, wrapped to 80 columns (word wrap by rendered width) | 6.5 ms | — |

## Export (Python, Pillow 13)

| Format | Time |
|---|---|
| TXT / ANSI / HTML / SVG | 0.12 / 0.26 / 0.28 / 0.72 ms |
| PNG (1×) / PNG (4×) | 38 ms / 183 ms |
| JPEG / WebP | 8.9 ms / 18 ms |

## Image conversion (Python, 800×600 source)

| Mode | Time |
|---|---|
| ASCII, 120 columns | 57 ms |
| Braille + Floyd–Steinberg, 120 columns | 96 ms |

## Responsiveness design

* Fonts are parsed lazily and kept in an LRU cache (160 parsed fonts); renders use a keyed LRU cache.
* Preview renders are debounced (≈100 ms) and run on a "latest job only" worker thread (Python) — stale
  requests are discarded, so typing never queues work.
* The all-font gallery computes its layout from metadata only and renders just the cards near the
  viewport, in a background thread (Python) or Web Worker (HTML); a generation counter cancels outdated
  results. Rendering all 937 fonts at once is never done synchronously in the UI.
* The font list is virtualized in the HTML edition (only visible rows exist in the DOM).
* Search is debounced (≈120 ms).
* The font pack is stored as one zlib stream (2.31 MB vs 14.8 MB of uncompressed bitmaps in V2).

## Image-to-Art Studio

Measured with `python tools/benchmark_image.py` (raw: `dist/perf_image.json`) on the synthetic 1200×800
`large_photo` fixture; best of 1–3 runs. "Cold" = first render of a source (includes the one-time resampling of
the source to the working resolution); Python caches that step, so changing adjustments, palettes or colours
re-renders in **2.1 ms** (classic, 80 columns).

| Measurement | Python (NumPy) | JavaScript (Node 26) |
|---|---|---|
| Decode 1200×800 PNG / 4000×2667 JPEG (Pillow) | 44 ms / 185 ms | browser-native |
| 30 modes at 80 columns, cold (min … median … max) | 66 … 79 … 328 ms | 15 … 18 … 78 ms |
| Classic / Braille / sextant / true colour at 200 columns | 143 / 289 / 271 / 140 ms | 29 / 70 / 65 / 31 ms |
| Typographic / mosaic / high-density / ANSI-16 (dithered) at 200 columns | 329 / 303 / 684 / 471 ms | 95 / 81 / 151 / 40 ms |
| Typographic at 300 columns | 294 ms | 93 ms |
| Braille + Floyd–Steinberg at 500 columns | 612 ms | 120 ms |
| Classic at 1000 columns | 273 ms | 92 ms |
| Image analysis | 157 ms | 94 ms |
| Smart Optimize "similarity" (7 candidates, 80 columns) | 1.68 s | 0.85 s |
| Glyph matching, 200,000 random 4×8 cells (no cache hits) | 1.56 s (3.1 M comparisons/s) | 0.74 s (6.5 M/s) |

The slowest kernels are pure-Python loops that cannot be vectorised exactly (error diffusion, palette diffusion);
everything else is vectorised NumPy. In the browser all Image Studio work runs in a Web Worker, so the interface
stays responsive; renders are debounced and only the latest request is kept (desktop: "latest job only" worker
thread with cancellation). The cost estimate shown before rendering is calibrated on these numbers (±50 %);
renders estimated above 2.5 s or 600 MB ask for confirmation.

### GPU acceleration (evaluated, not adopted)

* **WebGPU** (Chromium in the desktop app's browser pane, adapter: NVIDIA Blackwell / RTX 5090): a WGSL compute
  shader implementing the same density-window glyph matcher (`tools/webgpu_glyph_benchmark.js`) processed 200,000
  random cells in **12 ms** including upload and read-back (85 ms on the first run, which includes pipeline
  creation) versus **290 ms** for the JS CPU matcher, with identical results on that data set. However, real
  renders spend most of their time outside matching and already finish in 15–150 ms in the worker, and an f32 GPU
  path would need exactness safeguards (CPU re-check of near ties) and an asynchronous render pipeline to keep the
  editions bit-identical. The GPU path was therefore **not integrated**; the CPU path is the only one shipped.
* **CUDA (Python)**: CuPy is not installed. Adding it means a ~1 GB dependency for operations that take under
  0.7 s on the CPU even at 200–500 columns, contrary to the requirement not to add large GPU dependencies for
  operations that are already fast enough. Not adopted; no CUDA timing is claimed.

## File sizes

| File | V2 | V3 |
|---|---|---|
| Python single file | 1,241,459 B | 4,358,389 B (601 genuine fonts + 336 raster + Arabic tables + DejaVu fonts + glyph masks + Image Studio) |
| HTML single file | 14,822,693 B | 4,145,712 B (−72 %) |
| Windows EXE | — | 35,350,392 B (includes Python runtime, Tk, Pillow, NumPy) |
| Font pack (`fontpack.bin`) | — | 2,313,719 B |

No GPU acceleration is used: all operations above complete in milliseconds on the CPU, so a GPU path
would add dependencies without a measurable benefit.
