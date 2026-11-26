/* LeerBox — Image Studio conversion modes (port of src/leerbox/imgmodes.py). */
(function (LB) {
  'use strict';
  var IC = function () { return LB.imgcore; }, IG = function () { return LB.imgglyphs; };
  var P_CHOICES = { fit: ['stretch', 'contain', 'cover'], rotate: [0, 90, 180, 270], dither: ['none', 'floyd', 'atkinson', 'bayer'],
    edge_method: ['sobel', 'canny', 'dog'], luma: ['rec709', 'perceptual', 'linear', 'average'],
    color: ['none', 'original', 'grayscale', 'ansi16', 'ansi256', 'custom', 'gradient', 'dominant'], color_target: ['fg', 'bg', 'both'],
    equalize: ['none', 'global', 'clahe'], text_mode: ['flow', 'words', 'fill'], text_dir: ['auto', 'ltr', 'rtl'] };
  var IMG_PARAMS = {
    mode: ['str', 'classic'], cols: ['int', 100, 8, 1000], rows: ['int', 0, 0, 1000], cell_aspect: ['float', 0.5, 0.2, 2.0], lock_aspect: ['bool', true],
    target_aspect: ['float', 0, 0, 10], fit: ['choice', 'stretch'], crop_x0: ['float', 0, 0, 1], crop_y0: ['float', 0, 0, 1], crop_x1: ['float', 1, 0, 1],
    crop_y1: ['float', 1, 0, 1], rotate: ['choice', 0], angle: ['float', 0, -180, 180], flip_h: ['bool', false], flip_v: ['bool', false], pad: ['float', 0, 0, 0.5],
    exposure: ['float', 0, -3, 3], brightness: ['float', 0, -1, 1], contrast: ['float', 1, 0, 3], gamma: ['float', 1, 0.2, 5], saturation: ['float', 1, 0, 3],
    vibrance: ['float', 0, -1, 1], hue: ['float', 0, -180, 180], sharpness: ['float', 0, 0, 3], blur: ['float', 0, 0, 10], denoise: ['float', 0, 0, 1],
    black: ['float', 0, 0, 0.9], white: ['float', 1, 0.1, 1], highlights: ['float', 0, -1, 1], shadows: ['float', 0, -1, 1], posterize: ['int', 0, 0, 32],
    grayscale: ['bool', false], invert: ['bool', false], remove_bg: ['float', 0, 0, 1], equalize: ['choice', 'none'], local_contrast: ['float', 0, 0, 2],
    palette: ['str', ''], palette_reverse: ['bool', false], dither: ['choice', 'none'], dither_strength: ['float', 1, 0, 1], threshold: ['float', 0.5, 0, 1],
    adaptive: ['bool', false], edge_method: ['choice', 'sobel'], edge_strength: ['float', 1, 0, 3], edge_threshold: ['float', 0.25, 0, 1], levels: ['int', 6, 2, 16],
    luma: ['choice', 'rec709'], light_on_dark: ['bool', true], color: ['choice', 'none'], colors: ['str', '#000000,#ff0000,#ffff00,#ffffff'],
    gradient: ['str', '#0b1e3f,#2a9d8f,#e9c46a,#ffffff'], dominant_k: ['int', 6, 2, 16], color_target: ['choice', 'fg'], background: ['str', '#000000'],
    transparent_bg: ['bool', true], text: ['str', 'LeerBox'], text_mode: ['choice', 'flow'], text_dir: ['choice', 'auto'], seed: ['int', 7, 0, 2147483647] };
  var MODES = {
    classic: ['Classic ASCII', 'text', 1, 1, 1, 'ascii', 'Luminance → measured-density ASCII ramp (optional error diffusion)'],
    extended: ['Extended ASCII', 'text', 2, 2, 1, 'cp437', '2×2 structure matching over CP437/Latin-1 glyphs'],
    blocks: ['Unicode Block', 'block', 1, 1, 1, 'unicode', 'Shade blocks ░▒▓█ with Floyd–Steinberg error diffusion'],
    half: ['Unicode Half-Block', 'block', 1, 2, 1, 'unicode', '▀ with independent top/bottom colours (2 pixels per cell)'],
    quadrant: ['Unicode Quadrant', 'block', 2, 2, 1, 'unicode', '16 quadrant patterns; optimal two-colour partition per cell'],
    sextant: ['Unicode Sextant', 'block', 2, 3, 1, 'sextant', '64 sextant patterns (Unicode 13); optimal two-colour partition'],
    braille: ['Unicode Braille', 'braille', 2, 4, 1, 'braille', '2×4 dots per cell; threshold, adaptive or dithered'],
    ansi16: ['ANSI 16-Color', 'color', 1, 2, 1, 'unicode', 'Half blocks; colours chosen from the 16-colour palette in CIELAB with error diffusion'],
    ansi256: ['ANSI 256-Color', 'color', 1, 2, 1, 'unicode', 'Half blocks; nearest xterm-256 colours in CIELAB'],
    truecolor: ['ANSI TrueColor', 'color', 1, 2, 1, 'unicode', 'Half blocks with exact 24-bit colours'],
    mono: ['Monochrome', 'block', 1, 2, 1, 'unicode', '1-bit half blocks with error diffusion'],
    grayscale: ['Grayscale', 'color', 1, 2, 1, 'unicode', 'Half blocks in 26 grey levels with ordered dithering'],
    binary: ['Binary', 'text', 1, 1, 1, 'ascii', '0/1 digits from adaptive (local-mean) thresholds'],
    matrix: ['Matrix', 'text', 1, 1, 1, 'katakana', 'Half-width katakana & digits, green luminance with deterministic rain streaks'],
    emoji: ['Emoji', 'emoji', 1, 1, 2, 'emoji', 'Nearest emoji by colour (CIELAB ΔE); 2 columns per emoji'],
    pixel: ['Pixel Text', 'color', 1, 1, 2, 'unicode', 'Square pixels (██) in a median-cut palette'],
    dotted: ['Dotted', 'text', 1, 1, 1, 'unicode', 'Halftone dots with a 45° clustered screen'],
    edge: ['Edge Detection', 'edge', 1, 1, 1, 'ascii', 'Sobel/Canny/DoG edges drawn with orientation glyphs - / | \\'],
    contour: ['Contour', 'edge', 1, 1, 1, 'unicode', 'Iso-luminance contour lines via marching squares (box drawing)'],
    line: ['Line Art', 'edge', 4, 8, 1, 'ascii', 'Difference-of-Gaussians lines + template matching over line glyphs'],
    silhouette: ['Silhouette', 'block', 2, 2, 1, 'unicode', 'Foreground segmentation (alpha or Otsu) drawn with quadrants'],
    typographic: ['Typographic', 'text', 4, 8, 1, 'ascii', 'Glyph shape matching on 4×8 coverage features (structure-aware)'],
    words: ['Custom Word', 'text', 1, 1, 1, 'unicode', 'Image rebuilt from repeated user text (multilingual, RTL aware)'],
    math: ['Mathematical Symbol', 'text', 4, 8, 1, 'unicode', 'Shape matching over mathematical operators'],
    mosaic: ['Mosaic Character', 'color', 4, 8, 1, 'unicode', 'Geometric glyphs with least-squares foreground/background colours'],
    dense: ['High-Density Terminal', 'color', 4, 8, 1, 'sextant', 'Best of all block elements & sextants with fitted colours'],
    adaptive: ['Adaptive Character', 'text', 4, 8, 1, 'ascii', 'Flat regions: density ramp; detailed regions: shape matching'],
    hybrid: ['Hybrid Edge + Luminance', 'edge', 1, 1, 1, 'ascii', 'Density ramp with Sobel edge glyphs overlaid'],
    negative: ['Negative', 'text', 1, 1, 1, 'ascii', 'Photographic negative in linear light, perceptual density mapping'],
    multilayer: ['Multi-Layer', 'color', 4, 8, 1, 'ascii', 'Low-pass colour background + detail glyphs + edge layer'] };
  var COMPAT_NOTES = { ascii: 'Plain ASCII — works everywhere.', cp437: 'Latin-1/CP437 symbols — most terminal fonts.',
    unicode: 'Unicode block elements — all modern terminal fonts.',
    sextant: 'Sextants need a font with Unicode 13 Legacy Computing glyphs (e.g. Cascadia Code, Iosevka); others show boxes. DejaVu-based graphical exports draw them geometrically.',
    braille: 'Braille patterns — most modern fonts; spacing varies in some proportional fonts.',
    emoji: 'Emoji are double-width and need a colour-emoji font; terminal alignment can vary.',
    katakana: 'Half-width katakana need a CJK-capable font (e.g. MS Gothic, Noto Sans Mono CJK).' };
  var DEFAULT_PALETTE = { classic: 'ascii_extended', extended: 'cp437', blocks: 'blocks', binary: 'binary', dotted: 'dots', typographic: 'ascii_high',
    math: 'math', adaptive: 'ascii_high', hybrid: 'ascii_extended', negative: 'ascii_extended', multilayer: 'ascii_high', line: 'lines', matrix: 'katakana', emoji: 'emoji' };
  var DEFAULT_DITHER = { blocks: 'floyd', mono: 'floyd', ansi16: 'floyd', grayscale: 'bayer' };
  var ANSI16_RGB = [0x000000, 0xCD3131, 0x0DBC79, 0xE5E510, 0x2472C8, 0xBC3FBC, 0x11A8CD, 0xE5E5E5, 0x666666, 0xF14C4C, 0x23D18B, 0xF5F543, 0x3B8EEA, 0xD670D6, 0x29B8DB, 0xFFFFFF];
  function xterm256() {
    var lv = [0, 95, 135, 175, 215, 255], out = ANSI16_RGB.slice();
    lv.forEach(function (r) { lv.forEach(function (g) { lv.forEach(function (b) { out.push((r << 16) | (g << 8) | b); }); }); });
    for (var i = 0; i < 24; i++) { var v = 8 + 10 * i; out.push((v << 16) | (v << 8) | v); }
    return out;
  }
  var GRAY26 = [0x000000]; for (var gi = 0; gi < 24; gi++) GRAY26.push((8 + 10 * gi) * 0x010101); GRAY26.push(0xFFFFFF);
  var BAYER8 = [[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26], [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25], [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]];
  var MATRIX_GLYPHS = (function () { var s = ''; for (var c = 0xFF66; c < 0xFF9E; c++) s += String.fromCodePoint(c); return s + '0123456789'; })();

  function sanitizeParams(d) {
    var out = {}; d = d || {};
    Object.keys(IMG_PARAMS).forEach(function (k) {
      var spec = IMG_PARAMS[k], t = spec[0], def = spec[1], v = d[k] === undefined ? def : d[k];
      try {
        if (t === 'int') { v = Math.trunc(parseFloat(v)); if (isNaN(v)) v = def; v = Math.max(spec[2], Math.min(spec[3], v)); }
        else if (t === 'float') { v = parseFloat(v); if (!isFinite(v)) v = def; v = Math.max(spec[2], Math.min(spec[3], v)); }
        else if (t === 'bool') v = typeof v === 'boolean' ? v : ['1', 'true', 'yes', 'on'].indexOf(String(v).toLowerCase()) >= 0;
        else if (t === 'choice') { if (typeof def === 'number') v = Math.trunc(parseFloat(v)); if (P_CHOICES[k].indexOf(v) < 0) v = def; }
        else v = (k === 'palette' || k === 'text') ? IG().cleanPalette(v).slice(0, 2000) : String(v).slice(0, 2000);
      } catch (e) { v = def; }
      out[k] = v;
    });
    if (!MODES[out.mode]) out.mode = 'classic';
    return out;
  }

  function planGrid(srcW, srcH, p) {
    var m = MODES[p.mode], sx = m[2], sy = m[3], unit = m[4];
    var cols = Math.max(8, p.cols | 0), gcols = Math.max(4, Math.floor(cols / unit)), pixAspect = p.cell_aspect * unit;
    var srcAspect = srcW / Math.max(1, srcH), target = p.target_aspect > 0 ? p.target_aspect : srcAspect, rows;
    if (p.rows > 0 && p.lock_aspect) {
      rows = Math.max(1, Math.floor(gcols * pixAspect / target + 0.5));
      if (rows > p.rows) { rows = p.rows; gcols = Math.max(4, Math.floor(rows * target / pixAspect + 0.5)); }
    } else if (p.rows > 0) rows = p.rows;
    else rows = Math.max(1, Math.floor(gcols * pixAspect / target + 0.5));
    rows = Math.min(rows, 1000);
    return { cols: gcols * unit, gcols: gcols, rows: rows, sx: sx, sy: sy, unit: unit, sw: gcols * sx, sh: rows * sy, target_aspect: target };
  }
  var MODE_COST_US = { sextant: 3.3, quadrant: 1.6, dense: 1.6, ansi16: 5.8, line: 1.0, mosaic: 0.7, multilayer: 0.9, silhouette: 0.6, typographic: 0.45, math: 0.45, adaptive: 0.45, extended: 0.9 };
  function estimateCost(srcW, srcH, p) {  // calibrated on tools/benchmark_image.py (JS ≈ Python / 3.5), ±50 %
    var g = planGrid(srcW, srcH, p), cells = g.gcols * g.rows, samples = g.sw * g.sh, per = MODE_COST_US[p.mode] || 0.6;
    if (p.dither === 'floyd' || p.dither === 'atkinson' || p.mode === 'blocks' || p.mode === 'mono') per += 0.5;
    var ms = (60 + samples * per / 1000) / 3.5, mem = samples * 8 * 12 + cells * 120;
    return { cols: g.cols, rows: g.rows, cells: cells, samples: samples, est_ms: Math.round(ms * 10) / 10, est_text_bytes: cells * 3 + g.rows,
      est_ansi_bytes: cells * ((p.color !== 'none' || MODES[p.mode][1] === 'color') ? 40 : 3), est_memory_bytes: mem, heavy: ms > 2500 || mem > 600 * 1024 * 1024 };
  }
  function prepare(src, p) {
    var C = IC(), img = src;
    if (p.crop_x0 !== 0 || p.crop_y0 !== 0 || p.crop_x1 !== 1 || p.crop_y1 !== 1) img = C.crop(img, p.crop_x0, p.crop_y0, p.crop_x1, p.crop_y1);
    if (p.rotate) img = C.rotate90(img, p.rotate);
    if (p.flip_h || p.flip_v) img = C.flip(img, p.flip_h, p.flip_v);
    if (p.angle) img = C.rotateFree(img, p.angle);
    if (p.pad > 0) { var k = Math.floor(Math.max(img.w, img.h) * p.pad + 0.5); img = C.pad(img, k, k, k, k); }
    var g = planGrid(img.w, img.h, p);
    if (p.target_aspect > 0 && p.fit !== 'stretch') {
      var cur = img.w / img.h, tgt = p.target_aspect, extra;
      if (p.fit === 'contain') {
        if (cur > tgt) { extra = Math.floor(img.w / tgt - img.h + 0.5); img = C.pad(img, 0, extra >> 1, 0, extra - (extra >> 1)); }
        else { extra = Math.floor(img.h * tgt - img.w + 0.5); img = C.pad(img, extra >> 1, 0, extra - (extra >> 1), 0); }
      } else if (cur > tgt) { var nw = img.h * tgt / img.w; img = C.crop(img, (1 - nw) / 2, 0, (1 + nw) / 2, 1); }
      else { var nh = img.w / tgt / img.h; img = C.crop(img, 0, (1 - nh) / 2, 1, (1 + nh) / 2); }
    }
    var ww = Math.min(img.w, Math.max(g.sw * 2, 16)), wh = Math.max(1, Math.floor(img.h * ww / img.w + 0.5));
    if (ww !== img.w || wh !== img.h) img = C.resampleArea(img, ww, wh);
    var adj = {}; Object.keys(C.ADJUST_DEFAULTS).forEach(function (k2) { adj[k2] = p[k2]; });
    return [C.adjust(img, adj), g];
  }

  // ---------------------------------------------------------------- context
  function Ctx(work, g, p) {
    this.work = work; this.g = g; this.p = p; var bl = IC().parseColorList(p.background); this.bg = bl.length ? bl[0] : 0; this.cache = {};
  }
  Ctx.prototype.flat = function () { if (!this.cache.flat) this.cache.flat = IC().composite(this.work, this.bg); return this.cache.flat; };
  Ctx.prototype.grid = function (sx, sy) {
    var key = 'g' + sx + 'x' + sy;
    if (!this.cache[key]) {
      var w = this.g.gcols * sx, h = this.g.rows * sy, r = IC().resampleArea(this.work, w, h), c = IC().intToRgb01(this.bg), n = w * h, flat = new Float64Array(n * 3);
      for (var i = 0; i < n; i++) { var a = r.a[i]; for (var k = 0; k < 3; k++) flat[i * 3 + k] = r.rgb[i * 3 + k] * a + c[k] * (1 - a); }
      this.cache[key] = { rgb: flat, a: r.a, w: w, h: h };
    }
    return this.cache[key];
  };
  Ctx.prototype.lum = function (rgb, n) { return IC().luminance(rgb, n, this.p.luma); };
  Ctx.prototype.ink = function (G, lod) {
    var n = G.w * G.h, L = this.lum(G.rgb, n), out = new Float64Array(n), lo = lod === undefined ? this.p.light_on_dark : lod;
    for (var i = 0; i < n; i++) { var v = lo ? L[i] : 1 - L[i]; if (this.p.transparent_bg && G.a[i] < 0.5) v = 0; out[i] = IC().clip01(v); }
    return out;
  };
  Ctx.prototype.blank = function (a, n) { var out = new Uint8Array(n); if (this.p.transparent_bg) for (var i = 0; i < n; i++) out[i] = a[i] < 0.5 ? 1 : 0; return out; };

  // ---------------------------------------------------------------- colour engine
  function nearestPalette(rgb, n, palette) {
    var C = IC(), plab = palette.map(function (c) { var q = C.intToRgb01(c); return C.labOf(q[0], q[1], q[2]); }), cache = new Map(), out = new Array(n);
    for (var i = 0; i < n; i++) {
      var key = C.rgbInt(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]), hit = cache.get(key);
      if (hit === undefined) {
        var lab = C.labOf(((key >> 16) & 255) / 255, ((key >> 8) & 255) / 255, (key & 255) / 255), bd = Infinity, bi = 0;
        for (var j = 0; j < plab.length; j++) { var q = plab[j], d = (lab[0] - q[0]) * (lab[0] - q[0]) + (lab[1] - q[1]) * (lab[1] - q[1]) + (lab[2] - q[2]) * (lab[2] - q[2]); if (d < bd) { bd = d; bi = j; } }
        hit = palette[bi]; cache.set(key, hit);
      }
      out[i] = hit;
    }
    return out;
  }
  function colorPalette(ctx, mode) {
    if (mode === 'ansi16') return ANSI16_RGB;
    if (mode === 'ansi256') return xterm256();
    if (mode === 'custom') { var l = IC().parseColorList(ctx.p.colors); return l.length ? l : [0, 0xFFFFFF]; }
    if (mode === 'dominant') {
      if (!ctx.cache.dominant) ctx.cache.dominant = IC().medianCut(ctx.flat(), ctx.work.w * ctx.work.h, ctx.p.dominant_k).map(function (c) {
        return (Math.floor(c[0] * 255 + 0.5) << 16) | (Math.floor(c[1] * 255 + 0.5) << 8) | Math.floor(c[2] * 255 + 0.5); });
      return ctx.cache.dominant;
    }
    return null;
  }
  function mapColors(ctx, rgb, n, mode) {
    var C = IC(); mode = mode === undefined ? ctx.p.color : mode;
    if (mode === 'none') return null;
    var out = new Array(n), i;
    if (mode === 'original') { for (i = 0; i < n; i++) out[i] = C.rgbInt(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]); return out; }
    if (mode === 'grayscale') { for (i = 0; i < n; i++) { var L = C.lumOf(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 'rec709'); out[i] = C.rgbInt(L, L, L); } return out; }
    if (mode === 'gradient') {
      var stops = C.parseColorList(ctx.p.gradient); if (!stops.length) stops = [0, 0xFFFFFF];
      var lut = []; for (i = 0; i < 256; i++) lut.push(LB.effects.gradientColor(stops, i / 255));
      for (i = 0; i < n; i++) { var L2 = C.lumOf(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 'rec709'), q = Math.floor(L2 * 255 + 0.5); out[i] = lut[q < 0 ? 0 : q > 255 ? 255 : q]; }
      return out;
    }
    return nearestPalette(rgb, n, colorPalette(ctx, mode));
  }
  function contrastFg(c) { var r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255; return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140 ? 0x111111 : 0xF5F5F5; }
  function dim(c, f) { return (Math.floor(((c >> 16) & 255) * f + 0.5) << 16) | (Math.floor(((c >> 8) & 255) * f + 0.5) << 8) | Math.floor((c & 255) * f + 0.5); }
  /* chars: flat array (rows*cols); fg/bg: flat arrays or null; blank: Uint8Array or null */
  function buildArt(chars, cols, rows, fg, bg, blank) {
    var C = [], F = [], B = [];
    for (var y = 0; y < rows; y++) {
      var cr = [], fr = [], br = [];
      for (var x = 0; x < cols; x++) {
        var i = y * cols + x, bl = blank && blank[i];
        cr.push(bl ? ' ' : chars[i]); fr.push(!bl && fg ? fg[i] : null); br.push(!bl && bg ? bg[i] : null);
      }
      C.push(cr); F.push(fr); B.push(br);
    }
    return new LB.Art(C, F, B);
  }
  function applyCharColors(ctx, chars, rgb, blank) {
    var cols = ctx.g.gcols, rows = ctx.g.rows, n = cols * rows, cl = mapColors(ctx, rgb, n);
    if (cl === null) return buildArt(chars, cols, rows, null, null, blank);
    var t = ctx.p.color_target;
    if (t === 'fg') return buildArt(chars, cols, rows, cl, null, blank);
    if (t === 'bg') return buildArt(chars, cols, rows, cl.map(contrastFg), cl, blank);
    return buildArt(chars, cols, rows, cl, cl.map(function (c) { return dim(c, 0.3); }), blank);
  }

  // ---------------------------------------------------------------- quantisation / dithering
  function densityLevels(chars) {
    var s = chars.map(function (c) { return IG().coverageSum(c); }), lo = Math.min.apply(null, s), hi = Math.max.apply(null, s), n = chars.length;
    if (hi === lo) return chars.map(function (_, i) { return i / Math.max(1, n - 1); });
    return s.map(function (v) { return (v - lo) / (hi - lo); });
  }
  function nearestLevel(levels, v) {
    var n = levels.length, lo = 0, hi = n;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (levels[mid] < v) lo = mid + 1; else hi = mid; }
    var i = lo;
    if (i <= 0) return 0;
    if (i >= n) return n - 1;
    return (v - levels[i - 1] <= levels[i] - v) ? i - 1 : i;
  }
  function quantizeLevels(values, W, H, levels, method, strength) {
    var n = levels.length, out = new Int32Array(W * H), x, y;
    if (method === 'none' || method === 'bayer') {
      var step = n > 1 ? 1 / (n - 1) : 0;
      for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        var v = values[y * W + x];
        if (method === 'bayer' && n > 1) v = v + (BAYER8[y % 8][x % 8] / 64 - 0.5 + 1 / 128) * step * strength;
        out[y * W + x] = nearestLevel(levels, v);
      }
      return out;
    }
    var g = new Float64Array(values), taps = method === 'floyd' ? [[1, 0, 7 / 16], [-1, 1, 3 / 16], [0, 1, 5 / 16], [1, 1, 1 / 16]]
      : [[1, 0, 1 / 8], [2, 0, 1 / 8], [-1, 1, 1 / 8], [0, 1, 1 / 8], [1, 1, 1 / 8], [0, 2, 1 / 8]];
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
      var vv = g[y * W + x], q = nearestLevel(levels, vv);
      out[y * W + x] = q;
      var err = (vv - levels[q]) * strength;
      if (err) for (var t = 0; t < taps.length; t++) {
        var xx = x + taps[t][0], yy = y + taps[t][1];
        if (xx >= 0 && xx < W && yy < H) g[yy * W + xx] += err * taps[t][2];
      }
    }
    return out;
  }
  function adaptiveMask(ink, W, H, threshold, radius) {
    var r = radius === undefined ? Math.max(2, Math.floor(Math.min(H, W) / 12)) : radius, mean = IC().boxMean(ink, W, H, r), out = new Uint8Array(W * H);
    for (var i = 0; i < W * H; i++) out[i] = ink[i] > mean[i] + (threshold - 0.5) * 0.4 ? 1 : 0;
    return out;
  }
  function binarize(ctx, ink, W, H) {
    var p = ctx.p, out, i;
    if (p.adaptive) { out = adaptiveMask(ink, W, H, p.threshold); for (i = 0; i < W * H; i++) out[i] = out[i] && ink[i] > 0.04 ? 1 : 0; return out; }
    out = new Uint8Array(W * H);
    if (p.dither !== 'none') { var q = quantizeLevels(ink, W, H, [0, 1], p.dither, p.dither_strength); for (i = 0; i < W * H; i++) out[i] = q[i] === 1 ? 1 : 0; return out; }
    for (i = 0; i < W * H; i++) out[i] = ink[i] >= p.threshold ? 1 : 0;
    return out;
  }

  // ---------------------------------------------------------------- shared renderers
  function palette(ctx, mode) { return IG().resolvePalette(ctx.p.palette || DEFAULT_PALETTE[mode] || 'ascii_extended', null, ctx.p.palette_reverse); }
  function ramp(ctx, chars, ink, G, dither) {
    var q = quantizeLevels(ink, G.w, G.h, densityLevels(chars), dither || ctx.p.dither, ctx.p.dither_strength), out = new Array(G.w * G.h);
    for (var i = 0; i < out.length; i++) out[i] = chars[q[i]];
    return applyCharColors(ctx, out, G.rgb, ctx.blank(G.a, G.w * G.h));
  }
  /* (rows*fh) × (cols*fw) × ch → n × (fh*fw) × ch in reading order */
  function cellFeatures(arr, W, H, fw, fh, ch) {
    var rows = H / fh, cols = W / fw, F = fw * fh, out = new Float64Array(rows * cols * F * ch);
    for (var r = 0; r < rows; r++) for (var c = 0; c < cols; c++) for (var fy = 0; fy < fh; fy++) for (var fx = 0; fx < fw; fx++) {
      var si = ((r * fh + fy) * W + c * fw + fx) * ch, oi = (((r * cols + c) * F) + fy * fw + fx) * ch;
      for (var k = 0; k < ch; k++) out[oi + k] = arr[si + k];
    }
    return out;
  }
  function cellMean(arr, W, H, fw, fh, ch) {
    var rows = H / fh, cols = W / fw, F = fw * fh, f = cellFeatures(arr, W, H, fw, fh, ch), out = new Float64Array(rows * cols * ch);
    for (var i = 0; i < rows * cols; i++) for (var k = 0; k < ch; k++) { var s = 0; for (var j = 0; j < F; j++) s += f[(i * F + j) * ch + k]; out[i * ch + k] = s / F; }
    return out;
  }
  var matchers = new Map();
  function matcherFor(chars, fw, fh, k) {
    var key = chars.join('') + '|' + fw + '|' + fh + '|' + k, m = matchers.get(key);
    if (!m) { if (matchers.size > 24) matchers.clear(); m = new (IG().GlyphMatcher)(chars, fw, fh, k); matchers.set(key, m); }
    return m;
  }
  function shapeMatch(ctx, chars, fw, fh, k, ink) {
    var G = ctx.grid(fw, fh); if (!ink) ink = ctx.ink(G);
    var m = matcherFor(chars, fw, fh, k), n = ctx.g.gcols * ctx.g.rows, idx = m.match(cellFeatures(ink, G.w, G.h, fw, fh, 1), n), out = new Array(n);
    for (var i = 0; i < n; i++) out[i] = m.chars[idx[i]];
    return { chars: out, rgb: cellMean(G.rgb, G.w, G.h, fw, fh, 3), a: cellMean(G.a, G.w, G.h, fw, fh, 1) };
  }
  /* least-squares two-colour fit of each cell P (n×F×3) against masks M (list of Float64Array F) */
  function fitMasks(P, n, F, M) {
    var Gn = M.length, s1 = [], s2 = [], a11 = [], a12 = [], a22 = [], det = [], sing = [], g, i, j, k;
    for (g = 0; g < Gn; g++) {
      var t1 = 0, t2 = 0; for (j = 0; j < F; j++) { t1 += M[g][j]; t2 += M[g][j] * M[g][j]; }
      s1.push(t1); s2.push(t2); a11.push(t2); a12.push(t1 - t2); a22.push(F - 2 * t1 + t2);
      det.push(t2 * (F - 2 * t1 + t2) - (t1 - t2) * (t1 - t2)); sing.push(Math.abs(det[g]) < 1e-9);
    }
    var bestG = new Int32Array(n), bestFg = new Float64Array(n * 3), bestBg = new Float64Array(n * 3), mp = [0, 0, 0], b2 = [0, 0, 0], fg = [0, 0, 0], bg = [0, 0, 0];
    for (i = 0; i < n; i++) {
      var sumP = [0, 0, 0], sq = 0, base = i * F * 3;
      for (j = 0; j < F; j++) for (k = 0; k < 3; k++) { var v = P[base + j * 3 + k]; sumP[k] += v; sq += v * v; }
      var be = Infinity, bi = 0;
      for (g = 0; g < Gn; g++) {
        var m = M[g];
        for (k = 0; k < 3; k++) { var acc = 0; for (j = 0; j < F; j++) acc += P[base + j * 3 + k] * m[j]; mp[k] = acc; b2[k] = sumP[k] - acc; }
        for (k = 0; k < 3; k++) {
          if (sing[g]) { fg[k] = bg[k] = sumP[k] / F; }
          else { fg[k] = (a22[g] * mp[k] - a12[g] * b2[k]) / det[g]; bg[k] = (a11[g] * b2[k] - a12[g] * mp[k]) / det[g]; }
          fg[k] = fg[k] < 0 ? 0 : fg[k] > 1 ? 1 : fg[k]; bg[k] = bg[k] < 0 ? 0 : bg[k] > 1 ? 1 : bg[k];
        }
        var e = sq - 2 * (fg[0] * mp[0] + fg[1] * mp[1] + fg[2] * mp[2]) - 2 * (bg[0] * b2[0] + bg[1] * b2[1] + bg[2] * b2[2])
          + (fg[0] * fg[0] + fg[1] * fg[1] + fg[2] * fg[2]) * s2[g] + 2 * (fg[0] * bg[0] + fg[1] * bg[1] + fg[2] * bg[2]) * a12[g]
          + (bg[0] * bg[0] + bg[1] * bg[1] + bg[2] * bg[2]) * a22[g];
        e = Math.floor(e * 1e8 + 0.5);
        if (e < be) { be = e; bi = g; for (k = 0; k < 3; k++) { bestFg[i * 3 + k] = fg[k]; bestBg[i * 3 + k] = bg[k]; } }
      }
      bestG[i] = bi;
    }
    return [bestG, bestFg, bestBg];
  }
  function twoColorPatterns(ctx, sx, sy, charOf) {
    var G = ctx.grid(sx, sy), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, k = sx * sy, F = k, i, j;
    var blank = ctx.blank(cellMean(G.a, G.w, G.h, sx, sy, 1), n), chars = new Array(n);
    if (ctx.p.color === 'none') {
      var bits = binarize(ctx, ctx.ink(G), G.w, G.h), B = cellFeatures(bits, G.w, G.h, sx, sy, 1);
      for (i = 0; i < n; i++) { var code = 0; for (j = 0; j < k; j++) code += B[i * k + j] * (1 << j); chars[i] = charOf(code); }
      return buildArt(chars, cols, rows, null, null, blank);
    }
    var P = cellFeatures(G.rgb, G.w, G.h, sx, sy, 3), M = [], codes = [];
    for (var c = 1; c < (1 << k); c++) { var mm = new Float64Array(k); for (j = 0; j < k; j++) mm[j] = (c >> j) & 1; M.push(mm); codes.push(c); }
    var r = fitMasks(P, n, F, M), cm = (ctx.p.color === 'none' || ctx.p.color === 'original') ? 'original' : undefined;
    for (i = 0; i < n; i++) {
      var cd = codes[r[0][i]]; chars[i] = charOf(cd);
      if (cd === (1 << k) - 1) for (j = 0; j < 3; j++) r[2][i * 3 + j] = r[1][i * 3 + j];
    }
    return buildArt(chars, cols, rows, mapColors(ctx, r[1], n, cm), mapColors(ctx, r[2], n, cm), blank);
  }
  function fitGlyphColors(ctx, chars, fw, fh) {
    var G = ctx.grid(fw, fh), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, F = fw * fh;
    var r = fitMasks(cellFeatures(G.rgb, G.w, G.h, fw, fh, 3), n, F, IG().masksFloat(chars, fw, fh)), out = new Array(n);
    for (var i = 0; i < n; i++) out[i] = chars[r[0][i]];
    var cm = (ctx.p.color === 'none' || ctx.p.color === 'original') ? 'original' : undefined;
    return buildArt(out, cols, rows, mapColors(ctx, r[1], n, cm), mapColors(ctx, r[2], n, cm), ctx.blank(cellMean(G.a, G.w, G.h, fw, fh, 1), n));
  }
  function edgeField(ctx) {
    if (ctx.cache.edges) return ctx.cache.edges;
    var C = IC(), W = ctx.work.w, H = ctx.work.h, n = W * H, L = ctx.lum(ctx.flat(), n), gr = C.sobel(C.blur(L, W, H, 1, 0.7), W, H), gx = gr[0], gy = gr[1];
    var mag = new Float64Array(n), jxx = new Float64Array(n), jyy = new Float64Array(n), jxy = new Float64Array(n), i, p = ctx.p;
    for (i = 0; i < n; i++) { mag[i] = Math.sqrt(gx[i] * gx[i] + gy[i] * gy[i]) / 4 * p.edge_strength; jxx[i] = gx[i] * gx[i]; jyy[i] = gy[i] * gy[i]; jxy[i] = gx[i] * gy[i]; }
    if (p.edge_method === 'canny') {
      var e = C.canny(L, W, H, p.edge_threshold * 0.5, p.edge_threshold);
      for (i = 0; i < n; i++) mag[i] = e[i] ? Math.max(mag[i], p.edge_threshold + 1e-6) : 0;
    } else if (p.edge_method === 'dog') {
      var b1 = C.blur(L, W, H, 1, 1.0), b2 = C.blur(L, W, H, 1, 1.6);
      for (i = 0; i < n; i++) mag[i] = C.clip01(Math.abs(b1[i] - b2[i]) * 12 * p.edge_strength);
    }
    for (i = 0; i < n; i++) mag[i] = C.clip01(mag[i]);
    ctx.cache.edges = [mag, jxx, jyy, jxy];
    return ctx.cache.edges;
  }
  function orientationChars(ctx) {
    var f = edgeField(ctx), W = ctx.work.w, H = ctx.work.h, rows = ctx.g.rows, cols = ctx.g.gcols, C = IC();
    var M = C.resamplePlane(f[0], W, H, cols, rows), Jxx = C.resamplePlane(f[1], W, H, cols, rows), Jyy = C.resamplePlane(f[2], W, H, cols, rows), Jxy = C.resamplePlane(f[3], W, H, cols, rows);
    var glyph = new Array(rows * cols);
    for (var i = 0; i < rows * cols; i++) {
      var phi = 0.5 * Math.atan2(2 * Jxy[i], Jxx[i] - Jyy[i]), e = ((-phi * (180 / Math.PI) + 90) % 180 + 180) % 180;
      glyph[i] = (e < 31.5 || e >= 148.5) ? '-' : e < 76.5 ? '/' : e < 103.5 ? '|' : '\\';
    }
    return [M, glyph];
  }

  // ---------------------------------------------------------------- the 30 modes
  var R = {};
  R.classic = function (ctx) { var G = ctx.grid(1, 1); return ramp(ctx, palette(ctx, 'classic'), ctx.ink(G), G); };
  R.extended = function (ctx) { var s = shapeMatch(ctx, palette(ctx, 'extended'), 2, 2, 32); return applyCharColors(ctx, s.chars, s.rgb, ctx.blank(s.a, s.chars.length)); };
  R.blocks = function (ctx) {
    var G = ctx.grid(1, 1), chars = IG().resolvePalette(ctx.p.palette || 'blocks', null, ctx.p.palette_reverse);
    return ramp(ctx, chars, ctx.ink(G), G, ctx.p.dither !== 'none' ? ctx.p.dither : 'floyd');
  };
  R.half = function (ctx) {
    var G = ctx.grid(1, 2), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, x, y, i, chars = new Array(n);
    if (ctx.p.color === 'none') {
      var bits = binarize(ctx, ctx.ink(G), G.w, G.h), HB = [' ', '▀', '▄', '█'];
      for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) chars[y * cols + x] = HB[bits[(2 * y) * cols + x] | (bits[(2 * y + 1) * cols + x] << 1)];
      return buildArt(chars, cols, rows);
    }
    var top = new Float64Array(n * 3), bot = new Float64Array(n * 3), at = new Float64Array(n), ab = new Float64Array(n);
    for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
      i = y * cols + x; var t = (2 * y) * cols + x, b = (2 * y + 1) * cols + x;
      for (var k = 0; k < 3; k++) { top[i * 3 + k] = G.rgb[t * 3 + k]; bot[i * 3 + k] = G.rgb[b * 3 + k]; }
      at[i] = G.a[t]; ab[i] = G.a[b];
    }
    var fg = mapColors(ctx, top, n), bg = mapColors(ctx, bot, n);
    for (i = 0; i < n; i++) chars[i] = '▀';
    if (ctx.p.transparent_bg) {
      var fg2 = new Array(n), bg2 = new Array(n);
      for (i = 0; i < n; i++) {
        var tt = at[i] < 0.5, tb = ab[i] < 0.5;
        chars[i] = tt && tb ? ' ' : tt ? '▄' : '▀';
        fg2[i] = chars[i] === ' ' ? null : (tt ? bg[i] : fg[i]); bg2[i] = (tt || tb) ? null : bg[i];
      }
      return buildArt(chars, cols, rows, fg2, bg2);
    }
    return buildArt(chars, cols, rows, fg, bg);
  };
  R.quadrant = function (ctx) { return twoColorPatterns(ctx, 2, 2, function (c) { return IG().QUADRANT_CHARS[c]; }); };
  R.sextant = function (ctx) { return twoColorPatterns(ctx, 2, 3, IG().sextantChar); };
  R.braille = function (ctx) {
    var G = ctx.grid(2, 4), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, on = binarize(ctx, ctx.ink(G), G.w, G.h), i, x, y, chars = new Array(n);
    if (ctx.p.transparent_bg) for (i = 0; i < on.length; i++) if (G.a[i] < 0.5) on[i] = 0;
    var D = IG().BRAILLE_DOTS;
    for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
      var code = 0;
      for (var b = 0; b < 8; b++) code |= on[(y * 4 + D[b][1]) * G.w + x * 2 + D[b][0]] << b;
      chars[y * cols + x] = String.fromCodePoint(0x2800 + code);
    }
    if (ctx.p.color === 'none') return buildArt(chars, cols, rows);
    var Fe = cellFeatures(G.rgb, G.w, G.h, 2, 4, 3), O = cellFeatures(on, G.w, G.h, 2, 4, 1), col = new Float64Array(n * 3);
    for (i = 0; i < n; i++) {
      var cnt = 0, so = [0, 0, 0], sa = [0, 0, 0];
      for (var j = 0; j < 8; j++) for (var k = 0; k < 3; k++) { var v = Fe[(i * 8 + j) * 3 + k]; sa[k] += v; if (O[i * 8 + j]) so[k] += v * O[i * 8 + j]; }
      for (j = 0; j < 8; j++) cnt += O[i * 8 + j];
      for (k = 0; k < 3; k++) col[i * 3 + k] = cnt > 0 ? so[k] / Math.max(cnt, 1) : sa[k] / 8;
    }
    return applyCharColors(ctx, chars, col, null);
  };
  function paletteDiffuse(rgb, W, H, pal, dither, strength) {
    var C = IC(), plab = pal.map(function (c) { var q = C.intToRgb01(c); return C.labOf(q[0], q[1], q[2]); }), prgb = pal.map(C.intToRgb01), cache = new Map();
    var nearest = function (r, g, b) {
      var kr = Math.min(255, r > 0 ? Math.floor(r * 255 + 0.5) : 0), kg = Math.min(255, g > 0 ? Math.floor(g * 255 + 0.5) : 0), kb = Math.min(255, b > 0 ? Math.floor(b * 255 + 0.5) : 0);
      var key = (kr << 16) | (kg << 8) | kb, hit = cache.get(key);
      if (hit !== undefined) return hit;
      var lab = C.labOf(kr / 255, kg / 255, kb / 255), bi = 0, bd = Infinity;
      for (var i = 0; i < plab.length; i++) { var q = plab[i], d = (lab[0] - q[0]) * (lab[0] - q[0]) + (lab[1] - q[1]) * (lab[1] - q[1]) + (lab[2] - q[2]) * (lab[2] - q[2]); if (d < bd) { bd = d; bi = i; } }
      cache.set(key, bi); return bi;
    };
    var g = new Float64Array(rgb), out = new Array(W * H), taps = dither === 'floyd' ? [[1, 0, 7 / 16], [-1, 1, 3 / 16], [0, 1, 5 / 16], [1, 1, 1 / 16]]
      : [[1, 0, 1 / 8], [2, 0, 1 / 8], [-1, 1, 1 / 8], [0, 1, 1 / 8], [1, 1, 1 / 8], [0, 2, 1 / 8]];
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) {
      var o = (y * W + x) * 3, r = g[o], gg = g[o + 1], b = g[o + 2], i = nearest(r, gg, b), q = prgb[i];
      out[y * W + x] = pal[i];
      var er = (r - q[0]) * strength, eg = (gg - q[1]) * strength, eb = (b - q[2]) * strength;
      for (var t = 0; t < taps.length; t++) {
        var xx = x + taps[t][0], yy = y + taps[t][1];
        if (xx >= 0 && xx < W && yy < H) { var oo = (yy * W + xx) * 3; g[oo] = g[oo] + er * taps[t][2]; g[oo + 1] = g[oo + 1] + eg * taps[t][2]; g[oo + 2] = g[oo + 2] + eb * taps[t][2]; }
      }
    }
    return out;
  }
  function halfFromColors(ctx, colors, G) {
    var rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, fg = new Array(n), bg = new Array(n), chars = new Array(n), blank = new Uint8Array(n);
    for (var y = 0; y < rows; y++) for (var x = 0; x < cols; x++) {
      var i = y * cols + x; fg[i] = colors[(2 * y) * cols + x]; bg[i] = colors[(2 * y + 1) * cols + x]; chars[i] = '▀';
      blank[i] = ctx.p.transparent_bg && Math.max(G.a[(2 * y) * cols + x], G.a[(2 * y + 1) * cols + x]) < 0.5 ? 1 : 0;
    }
    return buildArt(chars, cols, rows, fg, bg, blank);
  }
  function ansiPaletteMode(ctx, pal, defDither) {
    var G = ctx.grid(1, 2), d = ctx.p.dither !== 'none' ? ctx.p.dither : defDither;
    var colors = (d === 'floyd' || d === 'atkinson') ? paletteDiffuse(G.rgb, G.w, G.h, pal, d, ctx.p.dither_strength) : nearestPalette(G.rgb, G.w * G.h, pal);
    return halfFromColors(ctx, colors, G);
  }
  R.ansi16 = function (ctx) { return ansiPaletteMode(ctx, ANSI16_RGB, 'floyd'); };
  R.ansi256 = function (ctx) { return ansiPaletteMode(ctx, xterm256(), 'none'); };
  R.truecolor = function (ctx) { var G = ctx.grid(1, 2); return halfFromColors(ctx, mapColors(ctx, G.rgb, G.w * G.h, 'original'), G); };
  R.mono = function (ctx) {
    var G = ctx.grid(1, 2), ink = ctx.ink(G), d = ctx.p.dither !== 'none' ? ctx.p.dither : 'floyd', bits, i;
    if (ctx.p.adaptive) bits = adaptiveMask(ink, G.w, G.h, ctx.p.threshold);
    else { var q = quantizeLevels(ink, G.w, G.h, [0, 1], d, ctx.p.dither_strength); bits = new Uint8Array(q.length); for (i = 0; i < q.length; i++) bits[i] = q[i] === 1 ? 1 : 0; }
    var rows = ctx.g.rows, cols = ctx.g.gcols, chars = new Array(rows * cols), HB = [' ', '▀', '▄', '█'];
    for (var y = 0; y < rows; y++) for (var x = 0; x < cols; x++) chars[y * cols + x] = HB[bits[(2 * y) * cols + x] | (bits[(2 * y + 1) * cols + x] << 1)];
    return buildArt(chars, cols, rows);
  };
  R.grayscale = function (ctx) {
    var G = ctx.grid(1, 2), L = ctx.lum(G.rgb, G.w * G.h), levels = GRAY26.map(function (c) { return ((c >> 16) & 255) / 255; });
    var q = quantizeLevels(L, G.w, G.h, levels, ctx.p.dither !== 'none' ? ctx.p.dither : 'bayer', ctx.p.dither_strength), colors = new Array(q.length);
    for (var i = 0; i < q.length; i++) colors[i] = GRAY26[q[i]];
    return halfFromColors(ctx, colors, G);
  };
  R.binary = function (ctx) {
    var G = ctx.grid(1, 1), ink = ctx.ink(G), r = Math.max(2, Math.floor(Math.min(G.h, G.w) / 10)), mean = IC().boxMean(ink, G.w, G.h, r), t = ctx.p.threshold, n = G.w * G.h, chars = new Array(n);
    for (var i = 0; i < n; i++) chars[i] = ink[i] > Math.max(mean[i], t) ? '1' : ink[i] > Math.min(mean[i], t) * 0.5 ? '0' : ' ';
    return applyCharColors(ctx, chars, G.rgb, ctx.blank(G.a, n));
  };
  R.matrix = function (ctx) {
    var G = ctx.grid(1, 1), rows = ctx.g.rows, cols = ctx.g.gcols, L = ctx.lum(G.rgb, G.w * G.h), rng = new LB.effects.Rng(ctx.p.seed), glyphs = IG().graphemes(MATRIX_GLYPHS);
    var heads = [], trail = [], x, y, i;
    for (x = 0; x < cols; x++) heads.push(rng.int(rows + 8));
    for (x = 0; x < cols; x++) trail.push(4 + rng.int(Math.max(4, Math.floor(rows / 2))));
    var chars = [], fg = [], blank = ctx.blank(G.a, G.w * G.h);
    for (y = 0; y < rows; y++) {
      var cr = [], fr = [];
      for (x = 0; x < cols; x++) {
        i = y * cols + x; var v = ctx.p.light_on_dark ? L[i] : 1 - L[i], g = glyphs[rng.int(glyphs.length)];
        if (v < 0.08 || blank[i]) { cr.push(' '); fr.push(null); continue; }
        var d = heads[x] - y, boost = d === 0 ? 1 : (d > 0 && d < trail[x] ? 0.35 * (1 - d / trail[x]) : 0), gl = Math.min(1, v * 0.9 + boost * 0.5);
        cr.push(g);
        fr.push(d === 0 ? (((180 + 75 * gl) | 0) << 16) | (255 << 8) | ((180 + 75 * gl) | 0) : (((30 * gl) | 0) << 16) | (((60 + 195 * gl) | 0) << 8) | ((40 * gl) | 0));
      }
      chars.push(cr); fg.push(fr);
    }
    return new LB.Art(chars, fg, null);
  };
  R.emoji = function (ctx) {
    var G = ctx.grid(1, 1), rows = ctx.g.rows, cols = ctx.g.gcols, spec = ctx.p.palette, pal = IG().EMOJI_COLORS;
    if (spec && spec !== 'emoji') { var allowed = new Set(IG().graphemes(spec)), f = pal.filter(function (e) { return allowed.has(e[0]); }); if (f.length) pal = f; }
    var picked = nearestPalette(G.rgb, G.w * G.h, pal.map(function (e) { return e[1]; })), byColor = new Map(), blank = ctx.blank(G.a, G.w * G.h), chars = [];
    pal.forEach(function (e) { if (!byColor.has(e[1])) byColor.set(e[1], e[0]); });
    for (var y = 0; y < rows; y++) { var r = []; for (var x = 0; x < cols; x++) { var i = y * cols + x; if (blank[i]) r.push(' ', ' '); else r.push(byColor.get(picked[i]), ''); } chars.push(r); }
    return new LB.Art(chars);
  };
  R.pixel = function (ctx) {
    var G = ctx.grid(1, 1), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, mode = ctx.p.color, colors;
    if (mode === 'none') colors = nearestPalette(G.rgb, n, IC().medianCut(ctx.flat(), ctx.work.w * ctx.work.h, Math.max(2, ctx.p.dominant_k)).map(function (c) {
      return (Math.floor(c[0] * 255 + 0.5) << 16) | (Math.floor(c[1] * 255 + 0.5) << 8) | Math.floor(c[2] * 255 + 0.5); }));
    else if (mode === 'original') colors = mapColors(ctx, G.rgb, n, 'original');
    else colors = mapColors(ctx, G.rgb, n);
    var blank = ctx.blank(G.a, n), chars = [], fg = [];
    for (var y = 0; y < rows; y++) {
      var cr = [], fr = [];
      for (var x = 0; x < cols; x++) { var i = y * cols + x, bl = blank[i]; cr.push(bl ? ' ' : '█', bl ? ' ' : '█'); fr.push(bl ? null : colors[i], bl ? null : colors[i]); }
      chars.push(cr); fg.push(fr);
    }
    return new LB.Art(chars, fg, null);
  };
  R.dotted = function (ctx) {
    var G = ctx.grid(1, 1), chars = IG().resolvePalette(ctx.p.palette || 'dots', null, ctx.p.palette_reverse), levels = densityLevels(chars), ink = ctx.ink(G), n = levels.length, W = G.w, H = G.h, v = new Float64Array(W * H);
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) { var off = ((y + x) % 2 === 0 ? -0.25 : 0.25) / Math.max(1, n - 1); v[y * W + x] = IC().clip01(ink[y * W + x] + off); }
    var q = quantizeLevels(v, W, H, levels, 'none'), out = new Array(W * H);
    for (var i = 0; i < out.length; i++) out[i] = chars[q[i]];
    return applyCharColors(ctx, out, G.rgb, ctx.blank(G.a, W * H));
  };
  R.edge = function (ctx) {
    var G = ctx.grid(1, 1), o = orientationChars(ctx), n = G.w * G.h, chars = new Array(n);
    for (var i = 0; i < n; i++) chars[i] = o[0][i] >= ctx.p.edge_threshold * 0.5 ? o[1][i] : ' ';
    return applyCharColors(ctx, chars, G.rgb, ctx.blank(G.a, n));
  };
  var CONTOUR_CHARS = { 1: '╯', 2: '╰', 4: '╭', 8: '╮', 3: '─', 12: '─', 9: '│', 6: '│', 5: '╳', 10: '╳' };
  R.contour = function (ctx) {
    var C = IC(), rows = ctx.g.rows, cols = ctx.g.gcols, W = ctx.work.w, H = ctx.work.h, L = ctx.lum(ctx.flat(), W * H);
    var Lc = C.resamplePlane(C.blur(L, W, H, 1, 1.0), W, H, cols + 1, rows + 1), nl = ctx.p.levels, band = new Int32Array(Lc.length), i;
    for (i = 0; i < Lc.length; i++) { var b = Math.floor(Lc[i] * nl); band[i] = b < 0 ? 0 : b > nl - 1 ? nl - 1 : b; }
    var chars = new Array(rows * cols), mxs = new Int32Array(rows * cols);
    for (var y = 0; y < rows; y++) for (var x = 0; x < cols; x++) {
      var tl = band[y * (cols + 1) + x], tr = band[y * (cols + 1) + x + 1], br = band[(y + 1) * (cols + 1) + x + 1], bl = band[(y + 1) * (cols + 1) + x];
      var mx = Math.max(tl, tr, br, bl), mask = (tl === mx ? 1 : 0) | (tr === mx ? 2 : 0) | (br === mx ? 4 : 0) | (bl === mx ? 8 : 0);
      var pc = (mask & 1) + ((mask >> 1) & 1) + ((mask >> 2) & 1) + ((mask >> 3) & 1);
      if (pc > 2) mask = 15 - mask;
      chars[y * cols + x] = CONTOUR_CHARS[mask] || ' '; mxs[y * cols + x] = mx;
    }
    var G = ctx.grid(1, 1), blank = ctx.blank(G.a, rows * cols);
    if (ctx.p.color === 'none') return buildArt(chars, cols, rows, null, null, blank);
    if (ctx.p.color === 'gradient') {
      var stops = C.parseColorList(ctx.p.gradient); if (!stops.length) stops = [0, 0xFFFFFF];
      var lut = []; for (i = 0; i < nl; i++) lut.push(LB.effects.gradientColor(stops, i / Math.max(1, nl - 1)));
      return buildArt(chars, cols, rows, Array.from(mxs).map(function (m) { return lut[m]; }), null, blank);
    }
    return applyCharColors(ctx, chars, G.rgb, blank);
  };
  R.line = function (ctx) {
    var C = IC(), G = ctx.grid(4, 8), W = ctx.work.w, H = ctx.work.h, L = ctx.lum(ctx.flat(), W * H);
    var s = Math.max(0.6, W / (ctx.g.gcols * 4) * 0.6), b1 = C.blur(L, W, H, 1, s), b2 = C.blur(L, W, H, 1, s * 1.6), lines = new Float64Array(W * H), i;
    for (i = 0; i < W * H; i++) lines[i] = C.clip01(-(b1[i] - b2[i]) * 40 * ctx.p.edge_strength - ctx.p.edge_threshold);
    var lw = C.resamplePlane(lines, W, H, G.w, G.h);
    if (ctx.p.transparent_bg) for (i = 0; i < lw.length; i++) if (G.a[i] < 0.5) lw[i] = 0;
    var sm = shapeMatch(ctx, palette(ctx, 'line'), 4, 8, 18, lw);
    return applyCharColors(ctx, sm.chars, sm.rgb, null);
  };
  function foregroundMask(ctx) {
    var W = ctx.work.w, H = ctx.work.h, n = W * H, out = new Uint8Array(n), i, t = 0;
    for (i = 0; i < n; i++) if (ctx.work.a[i] < 0.5) t++;
    if (t / n > 0.01) { for (i = 0; i < n; i++) out[i] = ctx.work.a[i] >= 0.5 ? 1 : 0; return out; }
    var L = ctx.lum(ctx.flat(), n), th = IC().otsu(L), bc = 0, bn = 0, x, y;
    for (i = 0; i < n; i++) out[i] = L[i] < th ? 1 : 0;
    for (x = 0; x < W; x++) { bc += out[x] + out[(H - 1) * W + x]; bn += 2; }
    for (y = 0; y < H; y++) { bc += out[y * W] + out[y * W + W - 1]; bn += 2; }
    if (bc / bn >= 0.5) for (i = 0; i < n; i++) out[i] = 1 - out[i];
    return out;
  }
  R.silhouette = function (ctx) {
    var rows = ctx.g.rows, cols = ctx.g.gcols, fm = foregroundMask(ctx), W = ctx.work.w, H = ctx.work.h, f = new Float64Array(W * H);
    for (var i = 0; i < f.length; i++) f[i] = fm[i];
    var m = IC().resamplePlane(f, W, H, cols * 2, rows * 2), chars = new Array(rows * cols), Q = IG().QUADRANT_CHARS;
    for (var y = 0; y < rows; y++) for (var x = 0; x < cols; x++) {
      var w2 = cols * 2, code = (m[(2 * y) * w2 + 2 * x] >= 0.5 ? 1 : 0) | (m[(2 * y) * w2 + 2 * x + 1] >= 0.5 ? 2 : 0) | (m[(2 * y + 1) * w2 + 2 * x] >= 0.5 ? 4 : 0) | (m[(2 * y + 1) * w2 + 2 * x + 1] >= 0.5 ? 8 : 0);
      chars[y * cols + x] = Q[code];
    }
    return applyCharColors(ctx, chars, ctx.grid(1, 1).rgb, null);
  };
  R.typographic = function (ctx) { var s = shapeMatch(ctx, palette(ctx, 'typographic'), 4, 8, 24); return applyCharColors(ctx, s.chars, s.rgb, ctx.blank(s.a, s.chars.length)); };
  function textStream(text, direction) {
    text = IG().cleanPalette(text).split(/\s+/).filter(Boolean).join(' ') || 'LeerBox';
    var rtl = direction === 'rtl' || (direction === 'auto' && LB.arabic.paragraphLevel(text, 'auto') === 1);
    if (LB.arabic.containsArabic(text)) text = LB.arabic.shape(text);
    return [IG().graphemes(text + ' ').map(function (g) { return [g, Math.max(1, LB.figlet.charWidth(g))]; }), rtl];
  }
  R.words = function (ctx) {
    var G = ctx.grid(1, 1), rows = ctx.g.rows, cols = ctx.g.gcols, ink = ctx.ink(G), p = ctx.p, ts = textStream(p.text, p.text_dir), stream = ts[0], rtl = ts[1];
    var words = [], cur = [], x, y, k;
    stream.forEach(function (gw) { cur.push(gw); if (gw[0] === ' ') { words.push(cur); cur = []; } });
    if (cur.length) words.push(cur);
    var on = new Uint8Array(rows * cols);
    for (var i = 0; i < on.length; i++) on[i] = (p.text_mode === 'fill' || ink[i] >= p.threshold * 0.6) && !(p.transparent_bg && G.a[i] < 0.5) ? 1 : 0;
    var chars = []; for (y = 0; y < rows; y++) { var rr = []; for (x = 0; x < cols; x++) rr.push(' '); chars.push(rr); }
    var si = 0, wi = 0;
    for (y = 0; y < rows; y++) {
      var xs = []; for (x = 0; x < cols; x++) xs.push(rtl ? cols - 1 - x : x);
      var onl = function (j) { return on[y * cols + xs[j]]; };
      k = 0;
      if (p.text_mode === 'words') {
        while (k < xs.length) {
          if (!onl(k)) { k++; continue; }
          var run = 0; while (k + run < xs.length && onl(k + run)) run++;
          var pos = k;
          for (;;) {
            var word = words[wi % words.length], wl = 0; word.forEach(function (gw) { wl += gw[1]; });
            if (pos + wl - (word[word.length - 1][0] === ' ' ? 1 : 0) > k + run) break;
            for (var t = 0; t < word.length; t++) {
              var g = word[t][0], w = word[t][1];
              if (pos >= k + run) break;
              if (w === 2 && pos + 1 < k + run) { if (rtl) { chars[y][xs[pos + 1]] = g; chars[y][xs[pos]] = ''; } else { chars[y][xs[pos]] = g; chars[y][xs[pos + 1]] = ''; } pos += 2; }
              else if (w === 1) { chars[y][xs[pos]] = g; pos += 1; }
              else pos += 1;
            }
            wi++;
          }
          for (var j = pos; j < k + run; j++) chars[y][xs[j]] = '·';
          k += run;
        }
      } else {
        while (k < xs.length) {
          if (!onl(k)) { k++; continue; }
          var gw2 = stream[si % stream.length];
          if (gw2[1] === 2) {
            if (k + 1 < xs.length && onl(k + 1)) { if (rtl) { chars[y][xs[k + 1]] = gw2[0]; chars[y][xs[k]] = ''; } else { chars[y][xs[k]] = gw2[0]; chars[y][xs[k + 1]] = ''; } k += 2; si++; }
            else k++;
            continue;
          }
          chars[y][xs[k]] = gw2[0]; k++; si++;
        }
      }
    }
    var flat = []; chars.forEach(function (r) { flat.push.apply(flat, r); });
    var art = applyCharColors(ctx, flat, G.rgb, null);
    if (p.color === 'none' && p.text_mode === 'fill') {
      for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
        var c = art.chars[y][x], iv = ink[y * cols + x];
        if (c.length === 1 && iv < 0.35) art.chars[y][x] = iv >= 0.12 ? c.toLowerCase() : (c.trim() ? '.' : c);
        else if (c.length === 1) art.chars[y][x] = c.toUpperCase();
      }
    }
    return art;
  };
  R.math = function (ctx) { var s = shapeMatch(ctx, palette(ctx, 'math'), 4, 8, 16); return applyCharColors(ctx, s.chars, s.rgb, ctx.blank(s.a, s.chars.length)); };
  var MOSAIC_GLYPHS = [' ', '█', '▀', '▄', '▌', '▐', '◢', '◣', '◤', '◥', '●', '◆', '▲', '▼', '■', '◖', '◗'];
  R.mosaic = function (ctx) { return fitGlyphColors(ctx, MOSAIC_GLYPHS.filter(function (c) { return IG().glyphAtlas().has(c) || c === ' '; }), 4, 8); };
  var DENSE_GLYPHS = (function () {
    var a = [' ', '█', '▀', '▄', '▌', '▐', '▖', '▗', '▘', '▝', '▚', '▞', '▙', '▛', '▜', '▟'], c;
    for (c = 0x2581; c < 0x2588; c++) a.push(String.fromCodePoint(c));
    for (c = 0x2589; c < 0x2590; c++) a.push(String.fromCodePoint(c));
    for (c = 0x1FB00; c < 0x1FB3C; c++) a.push(String.fromCodePoint(c));
    return a;
  })();
  R.dense = function (ctx) { return fitGlyphColors(ctx, DENSE_GLYPHS, 4, 8); };
  R.adaptive = function (ctx) {
    var G = ctx.grid(4, 8), ink = ctx.ink(G), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, feats = cellFeatures(ink, G.w, G.h, 4, 8, 1), chars = palette(ctx, 'adaptive');
    var sm = shapeMatch(ctx, chars, 4, 8, 24, ink), meanInk = new Float64Array(n), std = new Float64Array(n), i, j;
    for (i = 0; i < n; i++) {
      var s = 0; for (j = 0; j < 32; j++) s += feats[i * 32 + j]; var m = s / 32, v = 0;
      for (j = 0; j < 32; j++) { var d = Math.abs(feats[i * 32 + j] - m); v += d * d; }
      meanInk[i] = m; std[i] = Math.sqrt(v / 32);
    }
    var q = quantizeLevels(meanInk, cols, rows, densityLevels(chars), ctx.p.dither, ctx.p.dither_strength), out = new Array(n), th = 0.12 + (ctx.p.edge_threshold - 0.25) * 0.3;
    for (i = 0; i < n; i++) out[i] = std[i] > th ? sm.chars[i] : chars[q[i]];
    return applyCharColors(ctx, out, sm.rgb, ctx.blank(sm.a, n));
  };
  R.hybrid = function (ctx) {
    var G = ctx.grid(1, 1), chars = palette(ctx, 'hybrid'), n = G.w * G.h, q = quantizeLevels(ctx.ink(G), G.w, G.h, densityLevels(chars), ctx.p.dither, ctx.p.dither_strength);
    var o = orientationChars(ctx), out = new Array(n);
    for (var i = 0; i < n; i++) out[i] = o[0][i] >= ctx.p.edge_threshold ? o[1][i] : chars[q[i]];
    return applyCharColors(ctx, out, G.rgb, ctx.blank(G.a, n));
  };
  R.negative = function (ctx) {
    var C = IC(), G = ctx.grid(1, 1), n = G.w * G.h, neg = new Float64Array(n * 3), ink = new Float64Array(n), i;
    for (i = 0; i < n * 3; i++) neg[i] = C.l2s(1 - C.s2l(G.rgb[i]));
    for (i = 0; i < n; i++) {
      var L = C.lumOf(neg[i * 3], neg[i * 3 + 1], neg[i * 3 + 2], 'perceptual'), v = ctx.p.light_on_dark ? L : 1 - L;
      if (ctx.p.transparent_bg && G.a[i] < 0.5) v = 0;
      ink[i] = C.clip01(v);
    }
    var chars = palette(ctx, 'negative'), q = quantizeLevels(ink, G.w, G.h, densityLevels(chars), ctx.p.dither, ctx.p.dither_strength), out = new Array(n);
    for (i = 0; i < n; i++) out[i] = chars[q[i]];
    return applyCharColors(ctx, out, neg, ctx.blank(G.a, n));
  };
  R.multilayer = function (ctx) {
    var C = IC(), G = ctx.grid(4, 8), rows = ctx.g.rows, cols = ctx.g.gcols, n = rows * cols, i;
    var cm = cellMean(G.rgb, G.w, G.h, 4, 8, 3), low = C.blur(cm, cols, rows, 3, 1.5), L = ctx.lum(G.rgb, G.w * G.h), bl = C.blur(L, G.w, G.h, 1, 3.0), ad = new Float64Array(L.length);
    for (i = 0; i < L.length; i++) ad[i] = Math.abs(L[i] - bl[i]);
    var det = cellMean(ad, G.w, G.h, 4, 8, 1), detn = new Float64Array(n);
    for (i = 0; i < n; i++) detn[i] = C.clip01(det[i] * 6);
    var chars = palette(ctx, 'multilayer'), q = quantizeLevels(detn, cols, rows, densityLevels(chars), 'none'), o = orientationChars(ctx), out = new Array(n), fg = new Array(n), bg = new Array(n);
    var lowd = new Float64Array(n * 3); for (i = 0; i < n * 3; i++) lowd[i] = low[i] * 0.55;
    for (i = 0; i < n; i++) {
      var edge = o[0][i] >= ctx.p.edge_threshold;
      out[i] = edge ? o[1][i] : chars[q[i]];
      bg[i] = C.rgbInt(lowd[i * 3], lowd[i * 3 + 1], lowd[i * 3 + 2]);
      fg[i] = edge ? C.rgbInt(C.clip01(cm[i * 3] * 0.5 + 0.5), C.clip01(cm[i * 3 + 1] * 0.5 + 0.5), C.clip01(cm[i * 3 + 2] * 0.5 + 0.5))
        : C.rgbInt(C.clip01(cm[i * 3] * 1.25 + 0.08), C.clip01(cm[i * 3 + 1] * 1.25 + 0.08), C.clip01(cm[i * 3 + 2] * 1.25 + 0.08));
    }
    if (ctx.p.color !== 'none' && ctx.p.color !== 'original') { fg = mapColors(ctx, cm, n); bg = mapColors(ctx, lowd, n); }
    var art = buildArt(out, cols, rows, fg, bg, ctx.blank(cellMean(G.a, G.w, G.h, 4, 8, 1), n));
    art.meta.layers = ['background: low-pass colour', 'detail: high-pass luminance glyphs', 'edges: orientation glyphs'];
    return art;
  };

  function renderImageArt(src, params) {
    var p = sanitizeParams(params), t0 = Date.now(), pr = prepare(src, p), work = pr[0], g = pr[1], ctx = new Ctx(work, g, p);
    var art = R[p.mode](ctx);
    art.meta.image_mode = p.mode;
    var bytes = 0; art.chars.forEach(function (r) { bytes += new TextEncoder().encode(r.join('').replace(/\s+$/, '')).length + 1; });
    return { art: art, stats: { mode: p.mode, label: MODES[p.mode][0], cols: art.width, rows: art.height, chars: art.width * art.height,
      source: [src.w, src.h], work: [work.w, work.h], ms: Date.now() - t0, text_bytes: bytes, compat: COMPAT_NOTES[MODES[p.mode][5]],
      est_memory_bytes: work.w * work.h * 8 * 6 + art.width * art.height * 120 } };
  }
  LB.imgmodes = { IMG_PARAMS: IMG_PARAMS, P_CHOICES: P_CHOICES, MODES: MODES, MODE_KEYS: Object.keys(MODES), COMPAT_NOTES: COMPAT_NOTES,
    DEFAULT_PALETTE: DEFAULT_PALETTE, sanitizeParams: sanitizeParams, planGrid: planGrid, estimateCost: estimateCost, prepare: prepare, Ctx: Ctx,
    renderImageArt: renderImageArt, mapColors: mapColors, nearestPalette: nearestPalette, xterm256: xterm256, ANSI16_RGB: ANSI16_RGB,
    densityLevels: densityLevels, quantizeLevels: quantizeLevels, textStream: textStream, RENDERERS: R };
})(LB);
