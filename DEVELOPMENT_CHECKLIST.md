# Development Checklist — LeerBox Text Art Studio 3.0

Status legend: [x] done and tested · [~] done, partially verified · [ ] not done

## Workflow
- [x] Inspect and audit V2 Python and HTML sources (see CHANGELOG › audit findings)
- [x] Preserve V2 originals (`legacy_v2/`, SHA-256 recorded before changes)
- [x] Inventory V2 fonts (347 raster designs) and dependencies (Tk stdlib only)
- [x] Establish modular architecture (`src/leerbox`, `web/src`, `tools`, `tests`)
- [x] Acquire font collections (pyfiglet, figlet.js, xero, phracker, TOIlet; OFL Arabic; DejaVu)
- [x] Validate, de-duplicate (exact + near-duplicate), categorize, record licenses
- [x] Rendering engines (FIGlet, raster, Arabic, effects, Unicode, image)
- [x] Professional interface (Tk desktop, HTML)
- [x] Export system (15 formats + projects, clipboard, batch)
- [x] Creative tools
- [x] Performance work (lazy parsing, caches, debouncing, worker threads/Web Worker, virtualization)
- [x] Automated + integration tests, golden fixtures, cross-edition checks
- [x] Build standalone `.py`, `.html`; [~] `.exe` (built and verified once; final rebuild blocked by Smart App Control)
- [x] README, CHANGELOG, FONT_MANIFEST.json, THIRD_PARTY_LICENSES.txt, TEST_REPORT.md, PERFORMANCE_REPORT.md

## Image & Animation Studio
- [x] Decoding (PNG/JPEG/WebP/BMP/GIF/TIFF/ICO/AVIF, safe SVG), EXIF, transparency, limits, clipboard, batch
- [~] HEIC/HEIF (only with pillow-heif or Safari — neither available here, so untested)
- [x] 30 modes, analysis, Smart Optimize, palettes, glyph matching, colour engine, adjustments, geometry
- [x] Tk workspaces (scripted screenshots) and HTML workspaces (Chromium, Web Worker)
- [x] Animation: GIF frames, playback, HTML/GIF/ZIP/ANSI exports; [~] video (HTML only; WebM recording tested, video decoding not tested with a real file)
- [x] Cross-edition: 206/206 fixture cases bit-identical
- [x] Benchmarks + WebGPU evaluation; [ ] CUDA (CuPy not installed — deliberately not added)
- [ ] Desktop drag-and-drop (Tk has no native support)

## Verification gaps (open)
- [ ] Test HTML in Brave, Edge, Firefox and from `file://` (only Chromium over localhost was available)
- [ ] Code-sign the EXE (required where Smart App Control / WDAC is enforced)
- [ ] Compile C/C++ literal exports with a real compiler
- [ ] Manual (human) UI pass on high-DPI displays
