/* LeerBox — Image Studio core (port of src/leerbox/imgcore.py).
 * Images: { w, h, rgb: Float64Array(w*h*3) sRGB 0..1 interleaved, a: Float64Array(w*h), info }.
 * Same formulas and summation order as the Python edition so both produce the same art. */
(function (LB) {
  'use strict';
  var MAX_FILE_BYTES = 100 * 1024 * 1024, MAX_SOURCE_PIXELS = 50000000, MAX_WORK_SIDE = 2048, SVG_MAX_BYTES = 5 * 1024 * 1024;

  function makeImage(w, h, info) { return { w: w, h: h, rgb: new Float64Array(w * h * 3), a: new Float64Array(w * h), info: info || {} }; }
  function fromRgba(w, h, data, info) {
    var img = makeImage(w, h, info), n = w * h;
    for (var i = 0; i < n; i++) { img.rgb[i * 3] = data[i * 4] / 255; img.rgb[i * 3 + 1] = data[i * 4 + 1] / 255; img.rgb[i * 3 + 2] = data[i * 4 + 2] / 255; img.a[i] = data[i * 4 + 3] / 255; }
    return img;
  }
  function toRgba(img) {
    var n = img.w * img.h, out = new Uint8ClampedArray(n * 4), q = function (v) { v = v < 0 ? 0 : v > 1 ? 1 : v; return Math.floor(v * 255 + 0.5); };
    for (var i = 0; i < n; i++) { out[i * 4] = q(img.rgb[i * 3]); out[i * 4 + 1] = q(img.rgb[i * 3 + 1]); out[i * 4 + 2] = q(img.rgb[i * 3 + 2]); out[i * 4 + 3] = q(img.a[i]); }
    return out;
  }
  function copyImage(img) { return { w: img.w, h: img.h, rgb: new Float64Array(img.rgb), a: new Float64Array(img.a), info: Object.assign({}, img.info) }; }
  function clip01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  // ------------------------------------------------------------------ formats
  function sniffFormat(b) {
    var s = function (o, str) { for (var i = 0; i < str.length; i++) if (b[o + i] !== str.charCodeAt(i)) return false; return true; };
    if (s(0, 'RIFF') && s(8, 'WEBP')) return 'WEBP';
    if (s(4, 'ftyp')) {
      var brand = String.fromCharCode(b[8], b[9], b[10], b[11]);
      if (brand === 'avif' || brand === 'avis') return 'AVIF';
      if (['heic', 'heix', 'hevc', 'hevx', 'mif1', 'msf1', 'heim', 'heis'].indexOf(brand) >= 0) return 'HEIF';
    }
    if (b[0] === 0x89 && s(1, 'PNG')) return 'PNG';
    if (b[0] === 0xFF && b[1] === 0xD8 && b[2] === 0xFF) return 'JPEG';
    if (s(0, 'GIF87a') || s(0, 'GIF89a')) return 'GIF';
    if (s(0, 'BM')) return 'BMP';
    if ((s(0, 'II') && b[2] === 42 && b[3] === 0) || (s(0, 'MM') && b[2] === 0 && b[3] === 42)) return 'TIFF';
    if (b[0] === 0 && b[1] === 0 && b[2] === 1 && b[3] === 0) return 'ICO';
    var head = new TextDecoder('utf-8').decode(b.subarray(0, 256)).replace(/^﻿/, '').replace(/^\s+/, '').toLowerCase();
    if (head.indexOf('<?xml') === 0 || head.indexOf('<svg') === 0 || head.indexOf('<!--') === 0 || (head.indexOf('<!doctype') === 0 && head.indexOf('<svg') >= 0)) return 'SVG';
    var t = new TextDecoder('utf-8').decode(b.subarray(0, 64));
    if (/^\s*\{/.test(t)) return 'JSON';
    return 'UNKNOWN';
  }
  var SVG_FORBIDDEN = /<!DOCTYPE|<!ENTITY|<script|<foreignObject|\son[a-z]+\s*=|javascript:|<iframe|<object|<embed|<image\b|<use\b[^>]*href\s*=\s*["'](?!#)|xlink:href\s*=\s*["'](?!#)|<style|@import|url\(\s*["']?(?!#)/i;
  function svgIsSafe(text) {
    if (text.length > SVG_MAX_BYTES) return [false, 'SVG larger than 5 MB'];
    var m = SVG_FORBIDDEN.exec(text);
    if (m) return [false, 'unsafe SVG construct rejected: ' + JSON.stringify(m[0].slice(0, 40))];
    return [true, ''];
  }

  // ------------------------------------------------------------------ resampling & geometry
  /* Exact area-average resampling of an interleaved (rows × n × ch) buffer along x, or (n × cols × ch) along y. */
  function axisArea(src, rows, n, ch, nOut, alongX) {
    // alongX: src is rows × n × ch → rows × nOut × ch ; else src is n × rows × ch → nOut × rows × ch
    var out = new Float64Array(rows * nOut * ch), c = new Float64Array((n + 1) * ch);
    var edges = new Float64Array(nOut + 1), fl = new Int32Array(nOut + 1), fr = new Float64Array(nOut + 1), nx = new Int32Array(nOut + 1);
    for (var i = 0; i <= nOut; i++) { edges[i] = i * n / nOut; fl[i] = Math.min(Math.floor(edges[i]), n); fr[i] = edges[i] - fl[i]; nx[i] = Math.min(fl[i] + 1, n); }
    for (var r = 0; r < rows; r++) {
      var k, j;
      for (k = 0; k < ch; k++) c[k] = 0;
      for (j = 0; j < n; j++) {
        var si = alongX ? (r * n + j) * ch : (j * rows + r) * ch;
        for (k = 0; k < ch; k++) c[(j + 1) * ch + k] = c[j * ch + k] + src[si + k];
      }
      for (i = 0; i < nOut; i++) {
        var oi = alongX ? (r * nOut + i) * ch : (i * rows + r) * ch, den = edges[i + 1] - edges[i];
        for (k = 0; k < ch; k++) {
          var F0 = c[fl[i] * ch + k] + fr[i] * (c[nx[i] * ch + k] - c[fl[i] * ch + k]);
          var F1 = c[fl[i + 1] * ch + k] + fr[i + 1] * (c[nx[i + 1] * ch + k] - c[fl[i + 1] * ch + k]);
          out[oi + k] = (F1 - F0) / den;
        }
      }
    }
    return out;
  }
  function resamplePlaneCh(buf, w, h, ch, nw, nh) {
    if (w !== nw) { buf = axisArea(buf, h, w, ch, nw, true); w = nw; }
    if (h !== nh) { buf = axisArea(buf, w, h, ch, nh, false); h = nh; }
    return buf;
  }
  function resamplePlane(p, w, h, nw, nh) { return resamplePlaneCh(p, w, h, 1, nw, nh); }
  function resampleArea(img, w, h) {
    w = Math.max(1, w | 0); h = Math.max(1, h | 0);
    var n = img.w * img.h, st = new Float64Array(n * 4);
    for (var i = 0; i < n; i++) { var a = img.a[i]; st[i * 4] = img.rgb[i * 3] * a; st[i * 4 + 1] = img.rgb[i * 3 + 1] * a; st[i * 4 + 2] = img.rgb[i * 3 + 2] * a; st[i * 4 + 3] = a; }
    st = resamplePlaneCh(st, img.w, img.h, 4, w, h);
    var out = makeImage(w, h, Object.assign({}, img.info)), m = w * h;
    for (i = 0; i < m; i++) {
      var aa = st[i * 4 + 3];
      for (var k = 0; k < 3; k++) out.rgb[i * 3 + k] = aa > 1e-9 ? clip01(st[i * 4 + k] / aa) : 0;
      out.a[i] = clip01(aa);
    }
    return out;
  }
  function crop(img, x0, y0, x1, y1) {
    var W = img.w, H = img.h, t;
    x0 = clip01(x0); x1 = clip01(x1); y0 = clip01(y0); y1 = clip01(y1);
    if (x0 > x1) { t = x0; x0 = x1; x1 = t; }
    if (y0 > y1) { t = y0; y0 = y1; y1 = t; }
    var a = Math.floor(x0 * W), b = Math.max(Math.floor(x0 * W) + 1, Math.ceil(x1 * W)), c = Math.floor(y0 * H), d = Math.max(Math.floor(y0 * H) + 1, Math.ceil(y1 * H));
    b = Math.min(b, W); d = Math.min(d, H); a = Math.min(a, b - 1); c = Math.min(c, d - 1);
    var out = makeImage(b - a, d - c, Object.assign({}, img.info));
    for (var y = c; y < d; y++) for (var x = a; x < b; x++) {
      var si = y * W + x, oi = (y - c) * out.w + (x - a);
      out.rgb[oi * 3] = img.rgb[si * 3]; out.rgb[oi * 3 + 1] = img.rgb[si * 3 + 1]; out.rgb[oi * 3 + 2] = img.rgb[si * 3 + 2]; out.a[oi] = img.a[si];
    }
    return out;
  }
  function remap(img, nw, nh, f) {
    var out = makeImage(nw, nh, Object.assign({}, img.info));
    for (var y = 0; y < nh; y++) for (var x = 0; x < nw; x++) {
      var s = f(x, y), si = s[1] * img.w + s[0], oi = y * nw + x;
      out.rgb[oi * 3] = img.rgb[si * 3]; out.rgb[oi * 3 + 1] = img.rgb[si * 3 + 1]; out.rgb[oi * 3 + 2] = img.rgb[si * 3 + 2]; out.a[oi] = img.a[si];
    }
    return out;
  }
  function rotate90(img, deg) {
    var k = ((deg / 90 | 0) % 4 + 4) % 4, W = img.w, H = img.h;
    if (k === 0) return img;
    if (k === 1) return remap(img, H, W, function (x, y) { return [y, H - 1 - x]; });
    if (k === 2) return remap(img, W, H, function (x, y) { return [W - 1 - x, H - 1 - y]; });
    return remap(img, H, W, function (x, y) { return [W - 1 - y, x]; });
  }
  function flip(img, h, v) {
    if (!h && !v) return img;
    var W = img.w, H = img.h;
    return remap(img, W, H, function (x, y) { return [h ? W - 1 - x : x, v ? H - 1 - y : y]; });
  }
  function rotateFree(img, angle) {
    if (Math.abs(angle) < 1e-9) return img;
    var t = angle * Math.PI / 180, c = Math.cos(t), s = Math.sin(t), W = img.w, H = img.h;
    var nw = Math.ceil(Math.abs(W * c) + Math.abs(H * s)), nh = Math.ceil(Math.abs(W * s) + Math.abs(H * c));
    var out = makeImage(nw, nh, Object.assign({}, img.info));
    for (var y = 0; y < nh; y++) for (var x = 0; x < nw; x++) {
      var dx = x + 0.5 - nw / 2, dy = y + 0.5 - nh / 2;
      var sx = c * dx + s * dy + W / 2 - 0.5, sy = -s * dx + c * dy + H / 2 - 0.5;
      var x0 = Math.floor(sx), y0 = Math.floor(sy), fx = sx - x0, fy = sy - y0, acc = [0, 0, 0, 0];
      var taps = [[0, 0, (1 - fx) * (1 - fy)], [0, 1, fx * (1 - fy)], [1, 0, (1 - fx) * fy], [1, 1, fx * fy]];
      for (var q = 0; q < 4; q++) {
        var xx = x0 + taps[q][1], yy = y0 + taps[q][0], wgt = taps[q][2];
        if (xx >= 0 && xx < W && yy >= 0 && yy < H) {
          var si = yy * W + xx, a = img.a[si];
          acc[0] += img.rgb[si * 3] * a * wgt; acc[1] += img.rgb[si * 3 + 1] * a * wgt; acc[2] += img.rgb[si * 3 + 2] * a * wgt; acc[3] += a * wgt;
        } else { acc[0] += 0; acc[1] += 0; acc[2] += 0; acc[3] += 0; }
      }
      var oi = y * nw + x, aa = acc[3];
      for (var k = 0; k < 3; k++) out.rgb[oi * 3 + k] = aa > 1e-9 ? clip01(acc[k] / aa) : 0;
      out.a[oi] = clip01(aa);
    }
    return out;
  }
  function pad(img, l, t, r, b) {
    if (!(l || t || r || b)) return img;
    var nw = img.w + l + r, nh = img.h + t + b, out = makeImage(nw, nh, Object.assign({}, img.info));
    for (var y = 0; y < img.h; y++) for (var x = 0; x < img.w; x++) {
      var si = y * img.w + x, oi = (y + t) * nw + x + l;
      out.rgb[oi * 3] = img.rgb[si * 3]; out.rgb[oi * 3 + 1] = img.rgb[si * 3 + 1]; out.rgb[oi * 3 + 2] = img.rgb[si * 3 + 2]; out.a[oi] = img.a[si];
    }
    return out;
  }

  // ------------------------------------------------------------------ colour
  function s2l(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function l2s(c) { c = c < 0 ? 0 : c; return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055; }
  function lumOf(r, g, b, method) {
    if (method === 'average') return (r + g + b) / 3;
    if (method === 'rec601') return 0.299 * r + 0.587 * g + 0.114 * b;
    if (method === 'linear' || method === 'perceptual') {
      var y = 0.2126 * s2l(r) + 0.7152 * s2l(g) + 0.0722 * s2l(b);
      if (method === 'linear') return y;
      return (y > 216 / 24389 ? 116 * Math.cbrt(y) - 16 : y * 24389 / 27) / 100;
    }
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function luminance(rgb, n, method) { var out = new Float64Array(n); for (var i = 0; i < n; i++) out[i] = lumOf(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], method); return out; }
  function labOf(r, g, b) {
    var lr = s2l(r), lg = s2l(g), lb = s2l(b);
    var x = (0.4124564 * lr + 0.3575761 * lg + 0.1804375 * lb) / 0.95047, y = 0.2126729 * lr + 0.7151522 * lg + 0.0721750 * lb, z = (0.0193339 * lr + 0.1191920 * lg + 0.9503041 * lb) / 1.08883;
    var f = function (t) { return t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116; };
    var fx = f(x), fy = f(y), fz = f(z);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  }
  function q255(v) { v = v < 0 ? 0 : v > 1 ? 1 : v; var q = Math.floor(v * 255 + 0.5); return q < 0 ? 0 : q > 255 ? 255 : q; }
  function rgbInt(r, g, b) { return (q255(r) << 16) | (q255(g) << 8) | q255(b); }
  function intToRgb01(c) { return [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255]; }
  function parseColorList(s) {
    var out = [];
    String(s || '').split(/[\s,;]+/).forEach(function (part) {
      var p = part.trim().replace(/^#/, '');
      if (p.length === 3) p = p.split('').map(function (c) { return c + c; }).join('');
      if (/^[0-9a-fA-F]{6}$/.test(p)) out.push(parseInt(p, 16));
    });
    return out.slice(0, 256);
  }

  // ------------------------------------------------------------------ filters
  function gaussianKernel(sigma) {
    var r = Math.max(1, Math.ceil(sigma * 3)), k = [], s = 0, i;
    for (i = -r; i <= r; i++) k.push(Math.exp(-(i * i) / (2 * sigma * sigma)));
    for (i = 0; i < k.length; i++) s += k[i];
    return k.map(function (v) { return v / s; });
  }
  function convAxis(p, w, h, ch, k, alongX) {
    var r = (k.length - 1) / 2, out = new Float64Array(p.length), n = alongX ? w : h;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) for (var c = 0; c < ch; c++) {
      var acc = 0, pos = alongX ? x : y;
      for (var j = 0; j < k.length; j++) {
        var q = pos + j - r; q = q < 0 ? 0 : q > n - 1 ? n - 1 : q;
        acc = acc + k[j] * p[((alongX ? y * w + q : q * w + x)) * ch + c];
      }
      out[(y * w + x) * ch + c] = acc;
    }
    return out;
  }
  function blur(p, w, h, ch, sigma) {
    if (sigma <= 0.05) return p;
    var k = gaussianKernel(sigma);
    return convAxis(convAxis(p, w, h, ch, k, true), w, h, ch, k, false);
  }
  function boxMean(p, w, h, r) {
    var ip = new Float64Array((h + 1) * (w + 1)), y, x, col = new Float64Array(w * h);
    for (x = 0; x < w; x++) { var acc = 0; for (y = 0; y < h; y++) { acc = acc + p[y * w + x]; col[y * w + x] = acc; } }
    for (y = 0; y < h; y++) { var a2 = 0; for (x = 0; x < w; x++) { a2 = a2 + col[y * w + x]; ip[(y + 1) * (w + 1) + x + 1] = a2; } }
    var out = new Float64Array(w * h);
    for (y = 0; y < h; y++) {
      var y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1);
      for (x = 0; x < w; x++) {
        var x0 = Math.max(0, x - r), x1 = Math.min(w, x + r + 1);
        var s = ip[y1 * (w + 1) + x1] - ip[y0 * (w + 1) + x1] - ip[y1 * (w + 1) + x0] + ip[y0 * (w + 1) + x0];
        out[y * w + x] = s / ((y1 - y0) * (x1 - x0));
      }
    }
    return out;
  }
  function median3(p, w, h, ch) {
    var out = new Float64Array(p.length), v = new Float64Array(9);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) for (var c = 0; c < ch; c++) {
      var n = 0;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        var yy = Math.min(h - 1, Math.max(0, y + dy)), xx = Math.min(w - 1, Math.max(0, x + dx));
        v[n++] = p[(yy * w + xx) * ch + c];
      }
      out[(y * w + x) * ch + c] = Array.prototype.slice.call(v).sort(function (a, b) { return a - b; })[4];
    }
    return out;
  }
  function sobel(L, w, h) {
    var gx = new Float64Array(w * h), gy = new Float64Array(w * h);
    for (var y = 0; y < h; y++) {
      var ym = Math.max(0, y - 1), yp = Math.min(h - 1, y + 1);
      for (var x = 0; x < w; x++) {
        var xm = Math.max(0, x - 1), xp = Math.min(w - 1, x + 1), at = function (yy, xx) { return L[yy * w + xx]; };
        gx[y * w + x] = (at(ym, xp) + 2 * at(y, xp) + at(yp, xp)) - (at(ym, xm) + 2 * at(y, xm) + at(yp, xm));
        gy[y * w + x] = (at(yp, xm) + 2 * at(yp, x) + at(yp, xp)) - (at(ym, xm) + 2 * at(ym, x) + at(ym, xp));
      }
    }
    return [gx, gy];
  }
  function canny(L, w, h, low, high, sigma) {
    var g = blur(L, w, h, 1, sigma === undefined ? 1 : sigma), gr = sobel(g, w, h), gx = gr[0], gy = gr[1], n = w * h;
    var mag = new Float64Array(n), sec = new Uint8Array(n), i, x, y;
    for (i = 0; i < n; i++) {
      mag[i] = Math.sqrt(gx[i] * gx[i] + gy[i] * gy[i]) / 4;
      var ang = Math.atan2(gy[i], gx[i]) * (180 / Math.PI) + 180; ang = ((ang % 180) + 180) % 180;
      sec[i] = (ang < 22.5 || ang >= 157.5) ? 0 : ang < 67.5 ? 1 : ang < 112.5 ? 2 : 3;
    }
    var offs = [[[0, 1], [0, -1]], [[1, 1], [-1, -1]], [[1, 0], [-1, 0]], [[1, -1], [-1, 1]]];
    var at = function (yy, xx) { return (yy < 0 || yy >= h || xx < 0 || xx >= w) ? 0 : mag[yy * w + xx]; };
    var nms = new Float64Array(n);
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      i = y * w + x; var o = offs[sec[i]];
      if (mag[i] >= at(y + o[0][0], x + o[0][1]) && mag[i] >= at(y + o[1][0], x + o[1][1])) nms[i] = mag[i];
    }
    var edges = new Uint8Array(n), stack = [];
    for (i = 0; i < n; i++) if (nms[i] >= high) { edges[i] = 1; stack.push(i); }
    while (stack.length) {
      var j = stack.pop(), jy = (j / w) | 0, jx = j - jy * w;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        var yy = jy + dy, xx = jx + dx;
        if (yy < 0 || yy >= h || xx < 0 || xx >= w) continue;
        var k = yy * w + xx;
        if (!edges[k] && nms[k] >= low) { edges[k] = 1; stack.push(k); }
      }
    }
    return edges;
  }
  function otsu(values) {
    var hst = new Float64Array(256), n = values.length, i, t;
    for (i = 0; i < n; i++) { var q = Math.floor(values[i] * 255 + 0.5); q = q < 0 ? 0 : q > 255 ? 255 : q; hst[q] += 1; }
    if (!n) return 0.5;
    var sumAll = 0; for (t = 0; t < 256; t++) sumAll += t * hst[t];
    var best = -1, bt = 127, wb = 0, sb = 0;
    for (t = 0; t < 256; t++) {
      wb += hst[t]; if (wb === 0) continue;
      var wf = n - wb; if (wf === 0) break;
      sb += t * hst[t];
      var mb = sb / wb, mf = (sumAll - sb) / wf, between = wb * wf * (mb - mf) * (mb - mf);
      if (between > best) { best = between; bt = t; }
    }
    return (bt + 0.5) / 255;
  }
  function equalize(L, w, h, clahe, tiles, clip) {
    tiles = tiles || 8; clip = clip || 2;
    var n = w * h, q = new Int32Array(n), i;
    for (i = 0; i < n; i++) { var v = Math.floor(L[i] * 255 + 0.5); q[i] = v < 0 ? 0 : v > 255 ? 255 : v; }
    function mapping(x0, x1, y0, y1) {
      var hs = new Float64Array(256), size = 0, x, y, k;
      for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) { hs[q[y * w + x]] += 1; size++; }
      if (clahe) {
        var limit = Math.max(1, clip * size / 256), excess = 0;
        for (k = 0; k < 256; k++) excess += Math.max(hs[k] - limit, 0);
        for (k = 0; k < 256; k++) hs[k] = Math.min(hs[k], limit) + excess / 256;
      }
      var c = new Float64Array(256), acc = 0;
      for (k = 0; k < 256; k++) { acc = acc + hs[k]; c[k] = acc; }
      var den = Math.max(1e-9, c[255] - c[0]), m = new Float64Array(256);
      for (k = 0; k < 256; k++) m[k] = (c[k] - c[0]) / den;
      return m;
    }
    var out = new Float64Array(n);
    if (!clahe) { var mp = mapping(0, w, 0, h); for (i = 0; i < n; i++) out[i] = mp[q[i]]; return out; }
    var ty = Math.max(1, Math.min(tiles, h)), tx = Math.max(1, Math.min(tiles, w)), ys = [], xs = [], a, b;
    for (a = 0; a <= ty; a++) ys.push(Math.floor(a * h / ty + 0.5));
    for (b = 0; b <= tx; b++) xs.push(Math.floor(b * w / tx + 0.5));
    var maps = [];
    for (a = 0; a < ty; a++) { var row = []; for (b = 0; b < tx; b++) row.push(mapping(xs[b], xs[b + 1], ys[a], ys[a + 1])); maps.push(row); }
    for (var y = 0; y < h; y++) {
      var cy = (y + 0.5) * ty / h - 0.5, y0 = Math.min(ty - 1, Math.max(0, Math.floor(cy))), y1 = Math.min(ty - 1, y0 + 1), fy = clip01(cy - y0);
      for (var x = 0; x < w; x++) {
        var cx = (x + 0.5) * tx / w - 0.5, x0 = Math.min(tx - 1, Math.max(0, Math.floor(cx))), x1 = Math.min(tx - 1, x0 + 1), fx = clip01(cx - x0), qq = q[y * w + x];
        var v00 = maps[y0][x0][qq], v01 = maps[y0][x1][qq], v10 = maps[y1][x0][qq], v11 = maps[y1][x1][qq];
        out[y * w + x] = (v00 * (1 - fx) + v01 * fx) * (1 - fy) + (v10 * (1 - fx) + v11 * fx) * fy;
      }
    }
    return out;
  }
  function median(arr) {
    var s = Array.prototype.slice.call(arr).sort(function (a, b) { return a - b; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function removeBackground(img, tol) {
    var W = img.w, H = img.h, n = W * H, bg = [0, 0, 0], x, y, k;
    for (k = 0; k < 3; k++) {
      var vals = [];
      for (x = 0; x < W; x++) vals.push(img.rgb[x * 3 + k]);
      for (x = 0; x < W; x++) vals.push(img.rgb[((H - 1) * W + x) * 3 + k]);
      for (y = 0; y < H; y++) vals.push(img.rgb[(y * W) * 3 + k]);
      for (y = 0; y < H; y++) vals.push(img.rgb[(y * W + W - 1) * 3 + k]);
      bg[k] = median(vals);
    }
    var cand = new Uint8Array(n), region = new Uint8Array(n), st = [], i;
    for (i = 0; i < n; i++) {
      var dr = img.rgb[i * 3] - bg[0], dg = img.rgb[i * 3 + 1] - bg[1], db = img.rgb[i * 3 + 2] - bg[2];
      cand[i] = (Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(3) <= tol && img.a[i] > 0.01) ? 1 : 0;
    }
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) if ((y === 0 || y === H - 1 || x === 0 || x === W - 1) && cand[y * W + x] && !region[y * W + x]) { region[y * W + x] = 1; st.push(y * W + x); }
    while (st.length) {
      var j = st.pop(), jy = (j / W) | 0, jx = j - jy * W;
      [[jy - 1, jx], [jy + 1, jx], [jy, jx - 1], [jy, jx + 1]].forEach(function (p) {
        if (p[0] < 0 || p[0] >= H || p[1] < 0 || p[1] >= W) return;
        var q = p[0] * W + p[1]; if (cand[q] && !region[q]) { region[q] = 1; st.push(q); }
      });
    }
    var out = copyImage(img);
    for (i = 0; i < n; i++) if (region[i]) out.a[i] = 0;
    return out;
  }

  // ------------------------------------------------------------------ adjustment pipeline
  var ADJUST_DEFAULTS = { exposure: 0, brightness: 0, contrast: 1, gamma: 1, saturation: 1, vibrance: 0, hue: 0, sharpness: 0, blur: 0, denoise: 0,
    black: 0, white: 1, highlights: 0, shadows: 0, posterize: 0, grayscale: false, invert: false, remove_bg: 0, equalize: 'none', local_contrast: 0 };
  function adjust(img, p) {
    var g = function (k) { return p[k] === undefined ? ADJUST_DEFAULTS[k] : p[k]; };
    var out = img;
    if (g('remove_bg') > 0) out = removeBackground(out, +g('remove_bg'));
    var W = out.w, H = out.h, n = W * H, N = n * 3, rgb = new Float64Array(out.rgb), i, v;
    if (g('exposure') !== 0) { var f = Math.pow(2, +g('exposure')); for (i = 0; i < N; i++) rgb[i] = l2s(s2l(rgb[i]) * f); }
    var b0 = +g('black'), w0 = +g('white');
    if (b0 !== 0 || w0 !== 1) { var den = Math.max(1e-3, w0 - b0); for (i = 0; i < N; i++) rgb[i] = (rgb[i] - b0) / den; }
    for (i = 0; i < N; i++) rgb[i] = clip01(rgb[i]);
    var sh = +g('shadows'), hi = +g('highlights');
    if (sh) for (i = 0; i < N; i++) { v = rgb[i]; rgb[i] = v + 0.9 * sh * v * ((1 - v) * (1 - v)); }
    if (hi) for (i = 0; i < N; i++) { v = rgb[i]; rgb[i] = v + 0.9 * hi * v * v * (1 - v); }
    if (g('brightness') !== 0 || g('contrast') !== 1) { var ct = +g('contrast'), br = +g('brightness'); for (i = 0; i < N; i++) rgb[i] = (rgb[i] - 0.5) * ct + 0.5 + br; }
    for (i = 0; i < N; i++) rgb[i] = clip01(rgb[i]);
    if (g('gamma') !== 1) { var ge = 1 / Math.max(0.05, +g('gamma')); for (i = 0; i < N; i++) rgb[i] = Math.pow(rgb[i], ge); }
    var sat = +g('saturation'), vib = +g('vibrance'), hue = +g('hue');
    if (sat !== 1 || vib !== 0) for (i = 0; i < n; i++) {
      var r = rgb[i * 3], gg = rgb[i * 3 + 1], b = rgb[i * 3 + 2], y = lumOf(r, gg, b, 'rec709'), fa = sat;
      if (vib) { var cur = Math.max(r, gg, b) - Math.min(r, gg, b); fa = fa * (1 + vib * (1 - cur)); }
      rgb[i * 3] = clip01(y + (r - y) * fa); rgb[i * 3 + 1] = clip01(y + (gg - y) * fa); rgb[i * 3 + 2] = clip01(y + (b - y) * fa);
    }
    if (hue) {
      var t = hue * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
      for (i = 0; i < n; i++) {
        var r_ = rgb[i * 3], g_ = rgb[i * 3 + 1], b_ = rgb[i * 3 + 2];
        var y_ = r_ * 0.299 + g_ * 0.587 + b_ * 0.114, i_ = r_ * 0.595716 + g_ * -0.274453 + b_ * -0.321263, q_ = r_ * 0.211456 + g_ * -0.522591 + b_ * 0.311135;
        var i2 = i_ * c - q_ * s, q2 = i_ * s + q_ * c;
        rgb[i * 3] = clip01(y_ + 0.9563 * i2 + 0.6210 * q2); rgb[i * 3 + 1] = clip01(y_ - 0.2721 * i2 - 0.6474 * q2); rgb[i * 3 + 2] = clip01(y_ - 1.1070 * i2 + 1.7046 * q2);
      }
    }
    if (g('grayscale')) for (i = 0; i < n; i++) { v = lumOf(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 'rec709'); rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = v; }
    var eq = g('equalize'), lc = +g('local_contrast');
    if (eq === 'global' || eq === 'clahe' || lc > 0) {
      var L = luminance(rgb, n, 'rec709'), L2 = L;
      if (eq === 'global' || eq === 'clahe') L2 = equalize(L2, W, H, eq === 'clahe');
      if (lc > 0) { var bl = blur(L2, W, H, 1, Math.max(1, Math.max(H, W) / 40)), L3 = new Float64Array(n); for (i = 0; i < n; i++) L3[i] = L2[i] + lc * (L2[i] - bl[i]); L2 = L3; }
      for (i = 0; i < n; i++) { var d = L2[i] - L[i]; for (var k = 0; k < 3; k++) rgb[i * 3 + k] = clip01(rgb[i * 3 + k] + d); }
    }
    if (g('denoise') > 0) { var dn = +g('denoise'), md = median3(rgb, W, H, 3); for (i = 0; i < N; i++) rgb[i] = rgb[i] * (1 - dn) + md[i] * dn; }
    if (g('blur') > 0) rgb = blur(rgb, W, H, 3, +g('blur'));
    if (g('sharpness') > 0) { var sp = +g('sharpness'), b1 = blur(rgb, W, H, 3, 1.0); for (i = 0; i < N; i++) rgb[i] = clip01(rgb[i] + sp * (rgb[i] - b1[i])); }
    var pz = g('posterize') | 0;
    if (pz >= 2) for (i = 0; i < N; i++) rgb[i] = Math.floor(rgb[i] * (pz - 1) + 0.5) / (pz - 1);
    if (g('invert')) for (i = 0; i < N; i++) rgb[i] = 1 - rgb[i];
    for (i = 0; i < N; i++) rgb[i] = clip01(rgb[i]);
    return { w: W, h: H, rgb: rgb, a: out.a, info: Object.assign({}, out.info) };
  }
  function composite(img, bg) {
    var c = intToRgb01(bg), n = img.w * img.h, out = new Float64Array(n * 3);
    for (var i = 0; i < n; i++) { var a = img.a[i]; for (var k = 0; k < 3; k++) out[i * 3 + k] = img.rgb[i * 3 + k] * a + c[k] * (1 - a); }
    return out;
  }
  function medianCut(rgb, n, k, maxSamples) {
    maxSamples = maxSamples || 20000;
    var step = Math.max(1, Math.floor(n / maxSamples)), px = [];
    for (var i = 0; i < n; i += step) px.push([rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]]);
    var boxes = [px];
    while (boxes.length < k) {
      var best = -1, bi = -1, bc = 0;
      boxes.forEach(function (b, idx) {
        if (b.length < 2) return;
        var lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
        b.forEach(function (p) { for (var c = 0; c < 3; c++) { if (p[c] < lo[c]) lo[c] = p[c]; if (p[c] > hi[c]) hi[c] = p[c]; } });
        var cc = 0, rng = hi[0] - lo[0];
        for (var c2 = 1; c2 < 3; c2++) if (hi[c2] - lo[c2] > rng) { rng = hi[c2] - lo[c2]; cc = c2; }
        if (rng > best) { best = rng; bi = idx; bc = cc; }
      });
      if (bi < 0 || best <= 0) break;
      var bx = boxes.splice(bi, 1)[0].map(function (p, j) { return [p, j]; });
      bx.sort(function (a, b) { return a[0][bc] - b[0][bc] || a[1] - b[1]; });
      var mid = bx.length >> 1;
      boxes.splice(bi, 0, bx.slice(0, mid).map(function (q) { return q[0]; }), bx.slice(mid).map(function (q) { return q[0]; }));
    }
    return boxes.filter(function (b) { return b.length; }).map(function (b) {
      var s = [0, 0, 0]; b.forEach(function (p) { s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; });
      return [s[0] / b.length, s[1] / b.length, s[2] / b.length];
    });
  }

  // ------------------------------------------------------------------ browser decoding
  function decodeInBrowser(bytes, name, maxSide) {
    maxSide = maxSide || MAX_WORK_SIDE;
    if (bytes.length > MAX_FILE_BYTES) return Promise.reject(new Error('file is larger than 100 MB'));
    if (!bytes.length) return Promise.reject(new Error('empty file'));
    var fmt = sniffFormat(bytes), info = { name: name || '', format: fmt, bytes: bytes.length };
    var type = { PNG: 'image/png', JPEG: 'image/jpeg', GIF: 'image/gif', BMP: 'image/bmp', WEBP: 'image/webp', AVIF: 'image/avif', HEIF: 'image/heic', ICO: 'image/x-icon', TIFF: 'image/tiff', SVG: 'image/svg+xml' }[fmt];
    if (fmt === 'TIFF' && LB.imgcodecs && LB.imgcodecs.decodeTiff) {
      try { var t = LB.imgcodecs.decodeTiff(bytes); return Promise.resolve(fitSide(fromRgba(t.w, t.h, t.data, Object.assign(info, { source_size: [t.w, t.h], decoder: 'built-in TIFF' })), maxSide)); }
      catch (e) { return Promise.reject(e); }
    }
    if (!type) return Promise.reject(new Error('unsupported or unrecognised image format (' + fmt + ')'));
    if (fmt === 'SVG') {
      var text = new TextDecoder('utf-8').decode(bytes), safe = svgIsSafe(text);
      if (!safe[0]) return Promise.reject(new Error(safe[1]));
    }
    var blob = new Blob([bytes], { type: type });
    var viaImg = function () {
      return new Promise(function (res, rej) {
        var url = URL.createObjectURL(blob), im = new Image();
        im.onload = function () { URL.revokeObjectURL(url); res(im); };
        im.onerror = function () { URL.revokeObjectURL(url); rej(new Error('this browser cannot decode ' + fmt + ' images')); };
        im.src = url;
      });
    };
    var p = (fmt !== 'SVG' && typeof createImageBitmap === 'function')
      ? createImageBitmap(blob, { imageOrientation: 'from-image' }).catch(viaImg) : viaImg();
    return p.then(function (bm) {
      var w = bm.width || bm.naturalWidth || 300, h = bm.height || bm.naturalHeight || 150;
      if (w * h > MAX_SOURCE_PIXELS) throw new Error('image dimensions ' + w + '×' + h + ' exceed the limit');
      info.source_size = [w, h]; info.exif_oriented = fmt !== 'SVG';
      var f = Math.min(1, maxSide / Math.max(w, h)), nw = Math.max(1, Math.round(w * f)), nh = Math.max(1, Math.round(h * f));
      if (f < 1) info.reduced_to = [nw, nh];
      var cv = document.createElement('canvas'); cv.width = nw; cv.height = nh;
      var cx = cv.getContext('2d', { willReadFrequently: true });
      cx.imageSmoothingQuality = 'high';
      cx.drawImage(bm, 0, 0, nw, nh);
      if (bm.close) bm.close();
      return fromRgba(nw, nh, cx.getImageData(0, 0, nw, nh).data, info);
    });
  }
  function fitSide(img, maxSide) {
    if (Math.max(img.w, img.h) <= maxSide) return img;
    var f = maxSide / Math.max(img.w, img.h);
    var out = resampleArea(img, Math.max(1, Math.round(img.w * f)), Math.max(1, Math.round(img.h * f)));
    out.info.reduced_to = [out.w, out.h];
    return out;
  }
  function decoderCapabilities() {
    var c = document.createElement('canvas');
    var enc = function (t) { try { return c.toDataURL(t).indexOf('data:' + t) === 0; } catch (e) { return false; } };
    return { formats: { PNG: true, JPEG: true, GIF: true, BMP: true, WEBP: 'browser-dependent', AVIF: 'browser-dependent', HEIF: 'Safari only',
      ICO: true, TIFF: 'built-in decoder (baseline: uncompressed, PackBits, LZW, 8-bit)', SVG: 'sanitised, rasterised by the browser', VIDEO: 'browser-dependent (WebM/MP4)' },
      encoders: { webp: enc('image/webp'), mediaRecorder: typeof MediaRecorder !== 'undefined' } };
  }

  LB.imgcore = { makeImage: makeImage, fromRgba: fromRgba, toRgba: toRgba, copyImage: copyImage, sniffFormat: sniffFormat, svgIsSafe: svgIsSafe,
    resampleArea: resampleArea, resamplePlane: resamplePlane, resamplePlaneCh: resamplePlaneCh, crop: crop, rotate90: rotate90, flip: flip,
    rotateFree: rotateFree, pad: pad, s2l: s2l, l2s: l2s, lumOf: lumOf, luminance: luminance, labOf: labOf, rgbInt: rgbInt, q255: q255,
    intToRgb01: intToRgb01, parseColorList: parseColorList, gaussianKernel: gaussianKernel, blur: blur, boxMean: boxMean, median3: median3,
    sobel: sobel, canny: canny, otsu: otsu, equalize: equalize, removeBackground: removeBackground, ADJUST_DEFAULTS: ADJUST_DEFAULTS,
    adjust: adjust, composite: composite, medianCut: medianCut, decodeInBrowser: decodeInBrowser, fitSide: fitSide,
    decoderCapabilities: decoderCapabilities, clip01: clip01, MAX_WORK_SIDE: MAX_WORK_SIDE };
})(LB);
