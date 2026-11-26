/* LeerBox — image analysis, recommendations, reconstruction metrics and Smart Optimize (port of imganalysis.py).
 * Deterministic signal processing and rules; the quality metrics approximate visual quality. */
(function (LB) {
  'use strict';
  var IC = function () { return LB.imgcore; };
  var ORIENT_NAMES = ['horizontal', 'diagonal ↗', 'vertical', 'diagonal ↘'];
  function r4(v, d) { var f = Math.pow(10, d === undefined ? 4 : d); return Math.round(v * f) / f; }
  function percentile(sorted, q) {
    var n = sorted.length; if (!n) return 0;
    var pos = q / 100 * (n - 1), lo = Math.floor(pos), hi = Math.min(n - 1, lo + 1);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function mean(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; return a.length ? s / a.length : 0; }
  function std(a) { var m = mean(a), s = 0; for (var i = 0; i < a.length; i++) s += (a[i] - m) * (a[i] - m); return a.length ? Math.sqrt(s / a.length) : 0; }

  function analyze(src) {
    var C = IC(), s = Math.min(1, 384 / Math.max(src.w, src.h));
    var work = C.resampleArea(src, Math.max(8, Math.round(src.w * s)), Math.max(8, Math.round(src.h * s))), W = work.w, H = work.h, n = W * H, i;
    var flat = C.composite(work, 0xFFFFFF), L = C.luminance(flat, n, 'rec709'), sorted = Array.prototype.slice.call(L).sort(function (a, b) { return a - b; });
    var pct = [1, 5, 50, 95, 99].map(function (q) { return percentile(sorted, q); });
    var hist = new Array(16).fill(0); for (i = 0; i < n; i++) hist[Math.min(15, Math.max(0, Math.floor(L[i] * 16)))] += 1 / n;
    var rg = new Float64Array(n), yb = new Float64Array(n);
    for (i = 0; i < n; i++) { var r = flat[i * 3] * 255, g = flat[i * 3 + 1] * 255, b = flat[i * 3 + 2] * 255; rg[i] = r - g; yb[i] = 0.5 * (r + g) - b; }
    var colorfulness = Math.sqrt(std(rg) * std(rg) + std(yb) * std(yb)) + 0.3 * Math.sqrt(mean(rg) * mean(rg) + mean(yb) * mean(yb));
    var gr = C.sobel(L, W, H), mag = new Float64Array(n), edges = 0;
    for (i = 0; i < n; i++) { mag[i] = Math.sqrt(gr[0][i] * gr[0][i] + gr[1][i] * gr[1][i]) / 4; if (mag[i] > 0.1) edges++; }
    var L2 = new Float64Array(n); for (i = 0; i < n; i++) L2[i] = L[i] * L[i];
    var m1 = C.boxMean(L, W, H, 2), m2 = C.boxMean(L2, W, H, 2), tex = 0; for (i = 0; i < n; i++) tex += Math.sqrt(Math.max(m2[i] - m1[i] * m1[i], 0));
    var bl = C.blur(L, W, H, 1, 1.0), detail = 0; for (i = 0; i < n; i++) detail += Math.abs(L[i] - bl[i]);
    var t = C.otsu(L), lo = [], hi = []; for (i = 0; i < n; i++) (L[i] < t ? lo : hi).push(L[i]);
    var v = std(L) * std(L) || 1e-9, between = (lo.length * hi.length / (n * n)) * Math.pow((hi.length ? mean(hi) : 0) - (lo.length ? mean(lo) : 0), 2);
    var border = [], x, y; for (x = 0; x < W; x++) border.push(L[x], L[(H - 1) * W + x]); for (y = 0; y < H; y++) border.push(L[y * W], L[y * W + W - 1]);
    var center = []; for (y = H >> 2; y < (3 * H) >> 2; y++) for (x = W >> 2; x < (3 * W) >> 2; x++) center.push(L[y * W + x]);
    var transp = 0, partial = 0; for (i = 0; i < n; i++) { if (work.a[i] < 0.5) transp++; if (work.a[i] > 0.02 && work.a[i] < 0.98) partial++; }
    var pal = C.medianCut(flat, n, 6), labs = pal.map(function (c) { return C.labOf(c[0], c[1], c[2]); }), share = new Array(pal.length).fill(0), step = Math.max(1, Math.floor(n / 20000)), cnt = 0;
    for (i = 0; i < n; i += step) {
      var lab = C.labOf(flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2]), bd = Infinity, bi = 0;
      labs.forEach(function (q, j) { var d = (lab[0] - q[0]) * (lab[0] - q[0]) + (lab[1] - q[1]) * (lab[1] - q[1]) + (lab[2] - q[2]) * (lab[2] - q[2]); if (d < bd) { bd = d; bi = j; } });
      share[bi]++; cnt++;
    }
    var hex = function (c) { return '#' + c.map(function (q) { return ('0' + Math.round(q * 255).toString(16)).slice(-2); }).join(''); };
    var dominant = pal.map(function (c, j) { return { color: hex(c), share: r4(share[j] / cnt, 3) }; }).sort(function (a, b) { return b.share - a.share; });
    var grid = []; for (var gy = 0; gy < 4; gy++) { var row = []; for (var gx = 0; gx < 4; gx++) { var s2 = 0, c2 = 0; for (y = Math.floor(gy * H / 4); y < Math.floor((gy + 1) * H / 4); y++) for (x = Math.floor(gx * W / 4); x < Math.floor((gx + 1) * W / 4); x++) { s2 += L[y * W + x]; c2++; } row.push(r4(c2 ? s2 / c2 : 0, 3)); } grid.push(row); }
    var ob = [0, 0, 0, 0], tot = 0;
    for (i = 0; i < n; i++) { var ang = ((Math.atan2(-gr[1][i], gr[0][i]) * 180 / Math.PI + 90) % 180 + 180) % 180, bin = Math.min(3, Math.floor(((ang + 22.5) % 180) / 45)); ob[bin] += mag[i]; tot += mag[i]; }
    var uniq = new Set(); for (i = 0; i < n; i++) uniq.add(Math.floor(flat[i * 3] * 15.99) * 256 + Math.floor(flat[i * 3 + 1] * 15.99) * 16 + Math.floor(flat[i * 3 + 2] * 15.99));
    var m = { width: src.w, height: src.h, aspect: r4(src.w / src.h), mean_luminance: r4(mean(L)), luminance_std: r4(std(L)),
      percentiles: { p1: r4(pct[0]), p5: r4(pct[1]), p50: r4(pct[2]), p95: r4(pct[3]), p99: r4(pct[4]) }, dynamic_range: r4(pct[4] - pct[0]),
      histogram16: hist.map(function (q) { return r4(q); }), colorfulness: r4(colorfulness, 2), edge_density: r4(edges / n), texture: r4(tex / n), detail: r4(detail / n),
      otsu_threshold: r4(t), fg_bg_separation: r4(between / v), border_contrast: r4(Math.abs(mean(border) - mean(center))), transparent_fraction: r4(transp / n),
      partial_alpha_fraction: r4(partial / n), dominant_colors: dominant, local_luminance_4x4: grid, gradient_orientation: {}, quantized_colors_4bit: uniq.size };
    ORIENT_NAMES.forEach(function (nm, j) { m.gradient_orientation[nm] = r4(tot ? ob[j] / tot : 0, 3); });
    return { metrics: m, recommendations: recommend(m) };
  }
  function recommend(m) {
    var rec = [], add = function (k, v, r) { rec.push({ key: k, value: v, reason: r }); };
    var logo = m.fg_bg_separation > 0.75 && m.quantized_colors_4bit < 400 && m.texture < 0.08, colorful = m.colorfulness > 35, transparent = m.transparent_fraction > 0.05;
    if (transparent && logo) add('mode', 'silhouette', 'transparent background and few flat colours → crisp silhouette');
    else if (logo && colorful) add('mode', 'sextant', 'flat-colour logo/graphic → sextant blocks with fitted colours keep edges sharp');
    else if (logo) add('mode', 'quadrant', 'high-contrast graphic with clear figure/ground → quadrant blocks');
    else if (colorful) add('mode', 'truecolor', 'colourful image (colourfulness ' + m.colorfulness.toFixed(0) + ') → half-block true colour');
    else if (m.detail > 0.035) add('mode', 'braille', 'fine detail without much colour → Braille gives 8 dots per cell');
    else add('mode', 'classic', 'smooth monochrome image → density-mapped ASCII reads well');
    var cols = 80;
    if (m.detail > 0.05 || m.edge_density > 0.25) cols = 140; else if (m.detail > 0.025) cols = 110; else if (m.detail < 0.01) cols = 60;
    if (m.aspect > 1.6) cols = Math.floor(cols * 1.25);
    add('cols', Math.min(300, cols), 'detail ' + m.detail.toFixed(3) + ', edge density ' + m.edge_density.toFixed(2) + ', aspect ' + m.aspect.toFixed(2));
    if (m.dynamic_range < 0.55) add('equalize', 'clahe', 'narrow luminance range (' + m.dynamic_range.toFixed(2) + ') → adaptive histogram equalization');
    else if (m.dynamic_range < 0.8) add('contrast', Math.round(Math.min(2, 0.9 / Math.max(0.2, m.dynamic_range)) * 100) / 100, 'moderate range → stretch contrast');
    if (m.mean_luminance < 0.3) add('shadows', 0.4, 'dark image → lift shadows'); else if (m.mean_luminance > 0.78) add('highlights', -0.4, 'bright image → recover highlights');
    add('palette', m.texture > 0.06 ? 'ascii_high' : 'ascii_extended', m.texture > 0.06 ? 'textured image → larger glyph set' : 'smooth image → measured 70-glyph ramp');
    add('edge_strength', m.edge_density < 0.06 ? 1.6 : (m.edge_density > 0.3 ? 0.8 : 1.0), 'edge density ' + m.edge_density.toFixed(2));
    add('color', m.colorfulness < 8 ? 'none' : (m.colorfulness < 30 ? 'ansi256' : 'original'), 'colourfulness ' + m.colorfulness.toFixed(0) + ': ' +
      (m.colorfulness < 8 ? 'practically grey' : m.colorfulness < 30 ? 'moderate → 256 colours suffice' : 'rich colour → keep original colours'));
    var smooth = m.texture < 0.05 && m.dynamic_range > 0.5;
    add('dither', logo ? 'none' : (smooth ? 'floyd' : 'atkinson'), logo ? 'flat graphic: dithering would add noise' : smooth ? 'smooth gradients → Floyd–Steinberg avoids banding' : 'textured → Atkinson keeps contrast');
    if (transparent) add('transparent_bg', true, Math.round(m.transparent_fraction * 100) + '% transparent pixels stay empty');
    return rec;
  }
  function recommendedParams(analysis, base) { var p = Object.assign({}, base || {}); analysis.recommendations.forEach(function (r) { p[r.key] = r.value; }); return LB.imgmodes.sanitizeParams(p); }

  // ---------------------------------------------------------------- reconstruction & metrics
  function isBlockLike(c) { var o = c.codePointAt(0); return (o >= 0x2580 && o < 0x25A0) || (o >= 0x1FB00 && o < 0x1FB3C); }
  function reconstruct(art, p, fw, fh) {
    fw = fw || 4; fh = fh || 8;
    var rows = art.height, cols = art.width, lod = p.light_on_dark !== false, dfg = lod ? 0xEBEBEB : 0x0D0D0D, dbg = lod ? 0x0D0D0D : 0xF7F7F7;
    var emoji = new Map(LB.imgglyphs.EMOJI_COLORS), masks = new Map(), textMax = 0, x, y, W = cols * fw, H = rows * fh, out = new Float64Array(W * H * 3);
    var chars = art.chars.map(function (r) { return r.slice(); }), fgs = art.fg.map(function (r) { return r.slice(); }), bgs = art.bg.map(function (r) { return r.slice(); });
    for (y = 0; y < rows; y++) for (x = 1; x < cols; x++) if (chars[y][x] === '') { chars[y][x] = chars[y][x - 1]; fgs[y][x] = fgs[y][x - 1]; bgs[y][x] = bgs[y][x - 1]; }
    var getMask = function (c) {
      if (masks.has(c)) return masks.get(c);
      var arr = new Float64Array(fw * fh), m = emoji.has(c) ? null : LB.imgglyphs.glyphMask(c), bx = 8 / fw, by = 16 / fh;
      if (emoji.has(c)) arr.fill(1);
      else if (!m) arr.fill(0.2);
      else { for (var yy = 0; yy < 16; yy++) for (var xx = 0; xx < 8; xx++) arr[((yy / by) | 0) * fw + ((xx / bx) | 0)] += m[yy * 8 + xx] / 255; for (var k = 0; k < arr.length; k++) arr[k] /= bx * by; }
      if (!emoji.has(c) && Array.from(c).length === 1 && !isBlockLike(c) && c.trim()) textMax = Math.max(textMax, mean(arr));
      masks.set(c, arr); return arr;
    };
    for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) getMask(chars[y][x]);
    var norm = textMax > 0 && textMax < 0.8 ? 1 / textMax : 1, rgb = IC().intToRgb01;
    for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
      var c = chars[y][x], m = masks.get(c), single = !emoji.has(c) && Array.from(c).length === 1 && !isBlockLike(c);
      var f = rgb(emoji.has(c) ? emoji.get(c) : (fgs[y][x] !== null ? fgs[y][x] : dfg)), b = rgb(bgs[y][x] !== null ? bgs[y][x] : dbg);
      for (var fy = 0; fy < fh; fy++) for (var fx = 0; fx < fw; fx++) {
        var mv = m[fy * fw + fx]; if (single) mv = Math.min(1, Math.max(0, mv * norm));
        var o = ((y * fh + fy) * W + x * fw + fx) * 3;
        for (var k2 = 0; k2 < 3; k2++) out[o + k2] = mv * f[k2] + (1 - mv) * b[k2];
      }
    }
    return { rgb: out, w: W, h: H };
  }
  function ssim(a, b, W, H) {
    var C = IC(), c1 = 0.0001, c2 = 0.0009, n = W * H, aa = new Float64Array(n), bb = new Float64Array(n), ab = new Float64Array(n), i;
    for (i = 0; i < n; i++) { aa[i] = a[i] * a[i]; bb[i] = b[i] * b[i]; ab[i] = a[i] * b[i]; }
    var ma = C.blur(a, W, H, 1, 1.5), mb = C.blur(b, W, H, 1, 1.5), va = C.blur(aa, W, H, 1, 1.5), vb = C.blur(bb, W, H, 1, 1.5), cv = C.blur(ab, W, H, 1, 1.5), s = 0;
    for (i = 0; i < n; i++) {
      var sa = va[i] - ma[i] * ma[i], sb = vb[i] - mb[i] * mb[i], co = cv[i] - ma[i] * mb[i];
      s += ((2 * ma[i] * mb[i] + c1) * (2 * co + c2)) / ((ma[i] * ma[i] + mb[i] * mb[i] + c1) * (sa + sb + c2));
    }
    return s / n;
  }
  function qualityMetrics(ref, rec, W, H, sizeBytes) {
    var C = IC(), n = W * H, ra = C.blur(ref, W, H, 3, 1.0), rb = C.blur(rec, W, H, 3, 1.0), la = C.luminance(ra, n, 'rec709'), lb = C.luminance(rb, n, 'rec709'), i, se = 0;
    for (i = 0; i < n; i++) se += (la[i] - lb[i]) * (la[i] - lb[i]);
    var ga = C.sobel(la, W, H), gb = C.sobel(lb, W, H), A = new Float64Array(n), B = new Float64Array(n);
    for (i = 0; i < n; i++) { A[i] = Math.sqrt(ga[0][i] * ga[0][i] + ga[1][i] * ga[1][i]); B[i] = Math.sqrt(gb[0][i] * gb[0][i] + gb[1][i] * gb[1][i]); }
    var mA = mean(A), mB = mean(B), num = 0, dA = 0, dB = 0, de = 0;
    for (i = 0; i < n; i++) { num += (A[i] - mA) * (B[i] - mB); dA += (A[i] - mA) * (A[i] - mA); dB += (B[i] - mB) * (B[i] - mB); }
    for (i = 0; i < n; i++) { var p = C.labOf(ra[i * 3], ra[i * 3 + 1], ra[i * 3 + 2]), q = C.labOf(rb[i * 3], rb[i * 3 + 1], rb[i * 3 + 2]); de += Math.sqrt((p[0] - q[0]) * (p[0] - q[0]) + (p[1] - q[1]) * (p[1] - q[1]) + (p[2] - q[2]) * (p[2] - q[2])); }
    var den = Math.sqrt(dA * dB);
    return { lum_rmse: r4(Math.sqrt(se / n)), ssim: r4(ssim(la, lb, W, H)), edge_corr: r4(den > 1e-12 ? num / den : 0), color_de: r4(de / n, 2), bytes: sizeBytes | 0 };
  }
  function evaluate(src, art, p) {
    p = LB.imgmodes.sanitizeParams(p);
    var work = LB.imgmodes.prepare(src, p)[0], fw = 4, fh = 8, ref = IC().resampleArea(work, art.width * fw, art.height * fh), n = ref.w * ref.h, refRgb = new Float64Array(n * 3);
    var bg = p.light_on_dark ? 0.05 : 0.97;
    for (var i = 0; i < n; i++) for (var k = 0; k < 3; k++) refRgb[i * 3 + k] = ref.rgb[i * 3 + k] * ref.a[i] + bg * (1 - ref.a[i]);
    var rec = reconstruct(art, p, fw, fh);
    var ex = LB.exporter, size = new TextEncoder().encode(art.fg.some(function (r) { return r.some(function (c) { return c !== null; }); }) || art.bg.some(function (r) { return r.some(function (c) { return c !== null; }); }) ? ex.toAnsi(art, 'truecolor') : art.toText()).length;
    return qualityMetrics(refRgb, rec.rgb, rec.w, rec.h, size);
  }
  var COMPAT_SCORE = { ascii: 1.0, cp437: 0.9, unicode: 0.8, braille: 0.7, sextant: 0.45, katakana: 0.4, emoji: 0.3 };
  var OPT_PRESETS = {
    detail: { label: 'Maximum detail', w: { ssim: 0.45, edge: 0.45, lum: 0.1 }, cands: [{ mode: 'sextant', color: 'original' }, { mode: 'braille', dither: 'floyd' }, { mode: 'braille', adaptive: true }, { mode: 'dense' }, { mode: 'quadrant', color: 'original' }, { mode: 'typographic' }, { mode: 'truecolor' }] },
    similarity: { label: 'Maximum visual similarity', w: { ssim: 0.35, lum: 0.3, color: 0.35 }, cands: [{ mode: 'truecolor' }, { mode: 'dense' }, { mode: 'mosaic' }, { mode: 'sextant', color: 'original' }, { mode: 'quadrant', color: 'original' }, { mode: 'ansi256' }, { mode: 'multilayer' }] },
    readability: { label: 'Maximum text readability', w: { ssim: 0.35, edge: 0.3, compat: 0.35 }, cands: [{ mode: 'classic' }, { mode: 'classic', dither: 'floyd' }, { mode: 'typographic' }, { mode: 'adaptive' }, { mode: 'hybrid' }, { mode: 'extended' }] },
    small: { label: 'Minimum output size', w: { size: 0.55, ssim: 0.45 }, cands: [{ mode: 'classic', cols: 60 }, { mode: 'blocks', cols: 60 }, { mode: 'braille', cols: 50 }, { mode: 'mono', cols: 60 }, { mode: 'binary', cols: 60 }, { mode: 'classic', cols: 80 }] },
    terminal: { label: 'Terminal compatibility', w: { ssim: 0.45, compat: 0.4, color: 0.15 }, cands: [{ mode: 'ansi256', cols: 80 }, { mode: 'ansi16', cols: 80 }, { mode: 'half', cols: 80 }, { mode: 'classic', cols: 80 }, { mode: 'mono', cols: 80 }, { mode: 'truecolor', cols: 80 }] },
    portrait: { label: 'Portrait mode', w: { ssim: 0.5, edge: 0.3, lum: 0.2 }, cands: [{ mode: 'braille', dither: 'floyd', local_contrast: 0.6 }, { mode: 'typographic', equalize: 'clahe' }, { mode: 'adaptive', local_contrast: 0.5 }, { mode: 'truecolor' }, { mode: 'classic', dither: 'floyd', equalize: 'clahe' }] },
    landscape: { label: 'Landscape mode', w: { ssim: 0.35, color: 0.4, lum: 0.25 }, cands: [{ mode: 'truecolor', cols: 160 }, { mode: 'sextant', color: 'original', cols: 160 }, { mode: 'mosaic', cols: 140 }, { mode: 'ansi256', cols: 160 }, { mode: 'dense', cols: 140 }] },
    logo: { label: 'Logo mode', w: { edge: 0.5, ssim: 0.5 }, cands: [{ mode: 'silhouette' }, { mode: 'quadrant' }, { mode: 'sextant' }, { mode: 'quadrant', color: 'original' }, { mode: 'sextant', color: 'original' }, { mode: 'edge' }, { mode: 'contour' }] },
    braille: { label: 'Braille mode', w: { ssim: 0.6, edge: 0.4 }, cands: [{ mode: 'braille', threshold: 0.35 }, { mode: 'braille', threshold: 0.5 }, { mode: 'braille', threshold: 0.65 }, { mode: 'braille', adaptive: true }, { mode: 'braille', dither: 'floyd' }, { mode: 'braille', dither: 'atkinson' }, { mode: 'braille', dither: 'bayer' }] }
  };
  var METRIC_NOTE = 'Scores are automated approximations of visual quality (luminance RMSE, SSIM, edge correlation, CIELAB colour error, output size and terminal compatibility); they do not replace looking at the result.';
  function optimize(src, base, preset, top, progress) {
    var spec = OPT_PRESETS[preset], M = LB.imgmodes, t0 = Date.now(), results = [];
    base = M.sanitizeParams(base);
    spec.cands.forEach(function (ov, i) {
      var p = Object.assign({}, base, { dither: 'none', adaptive: false, color: 'none' }, ov);
      p = M.sanitizeParams(p);
      var r = M.renderImageArt(src, p);
      results.push({ params: p, art: r.art, stats: r.stats, metrics: evaluate(src, r.art, p) });
      if (progress) progress(i + 1, spec.cands.length);
    });
    var maxBytes = Math.max.apply(null, results.map(function (r) { return r.metrics.bytes; })) || 1;
    results.forEach(function (r) {
      var q = r.metrics, parts = { ssim: Math.max(0, q.ssim), lum: Math.max(0, 1 - q.lum_rmse * 2), edge: (q.edge_corr + 1) / 2, color: Math.max(0, 1 - q.color_de / 50),
        size: 1 - q.bytes / maxBytes, compat: COMPAT_SCORE[M.MODES[r.params.mode][5]] }, s = 0;
      Object.keys(parts).forEach(function (k) { s += (spec.w[k] || 0) * parts[k]; });
      r.score = r4(s); r.parts = {}; Object.keys(spec.w).forEach(function (k) { r.parts[k] = r4(parts[k], 3); });
    });
    results.sort(function (a, b) { return b.score - a.score; });
    return { preset: preset, label: spec.label, note: METRIC_NOTE, ms: Date.now() - t0, results: results.slice(0, top || 6), evaluated: results.length };
  }
  LB.imganalysis = { analyze: analyze, recommend: recommend, recommendedParams: recommendedParams, reconstruct: reconstruct, qualityMetrics: qualityMetrics,
    evaluate: evaluate, optimize: optimize, OPT_PRESETS: OPT_PRESETS, METRIC_NOTE: METRIC_NOTE, COMPAT_SCORE: COMPAT_SCORE };
})(LB);
