/* LeerBox — animation, codecs (GIF decode/encode, baseline TIFF), typographic compositions and image projects
 * (port of src/leerbox/imganim.py plus browser-only codecs). Everything runs locally. */
(function (LB) {
  'use strict';
  var IC = function () { return LB.imgcore; };
  var MAX_FRAMES = 600, MAX_FRAME_PIXELS_TOTAL = 400000000;

  // ---------------------------------------------------------------- GIF decoder (LZW, disposal 0–3, transparency)
  function lzwDecode(data, minSize, npix) {
    var clear = 1 << minSize, eoi = clear + 1, size = minSize + 1, mask = (1 << size) - 1, next = eoi + 1, out = new Uint8Array(npix), op = 0;
    var prefix = new Int32Array(4096), suffix = new Uint8Array(4096), first = new Uint8Array(4096), stack = new Uint8Array(4097), old = -1, bits = 0, acc = 0, i, c;
    for (i = 0; i < clear; i++) { prefix[i] = -1; suffix[i] = i; first[i] = i; }
    for (var p = 0; p < data.length && op < npix; p++) {
      acc |= data[p] << bits; bits += 8;
      while (bits >= size && op < npix) {
        var code = acc & mask; acc >>>= size; bits -= size;
        if (code === clear) { size = minSize + 1; mask = (1 << size) - 1; next = eoi + 1; old = -1; continue; }
        if (code === eoi) return out;
        if (old === -1) { if (code >= clear) return out; out[op++] = suffix[code]; old = code; continue; }
        var sp = 0, in_ = code;
        if (code >= next) { if (code > next) return out; stack[sp++] = first[old]; c = old; }
        else c = code;
        while (c >= clear) { stack[sp++] = suffix[c]; c = prefix[c]; if (sp > 4096) return out; }
        stack[sp++] = c;
        if (next < 4096) { prefix[next] = old; suffix[next] = c; first[next] = first[old]; next++; if (next > mask && size < 12) { size++; mask = (1 << size) - 1; } }
        while (sp > 0 && op < npix) out[op++] = stack[--sp];
        old = in_;
      }
    }
    return out;
  }
  function decodeGif(b) {
    if (!(b[0] === 71 && b[1] === 73 && b[2] === 70)) throw new Error('not a GIF');
    var W = b[6] | (b[7] << 8), H = b[8] | (b[9] << 8), flags = b[10], bgIndex = b[11], pos = 13, gct = null;
    if (!W || !H || W * H > 50000000) throw new Error('invalid GIF dimensions');
    if (flags & 0x80) { var n = 3 << ((flags & 7) + 1); gct = b.subarray(pos, pos + n); pos += n; }
    var canvas = new Uint8ClampedArray(W * H * 4), frames = [], durations = [], loop = 1, gce = { disposal: 0, trans: -1, delay: 100 }, prev = null;
    while (pos < b.length) {
      var t = b[pos++];
      if (t === 0x3B) break;
      if (t === 0x21) {
        var label = b[pos++];
        if (label === 0xF9 && b[pos] === 4) { var pf = b[pos + 1]; gce = { disposal: (pf >> 2) & 7, trans: (pf & 1) ? b[pos + 4] : -1, delay: (b[pos + 2] | (b[pos + 3] << 8)) * 10 || 100 }; }
        if (label === 0xFF && b[pos] === 11 && String.fromCharCode.apply(null, b.subarray(pos + 1, pos + 12)) === 'NETSCAPE2.0') loop = b[pos + 14] | (b[pos + 15] << 8);
        while (pos < b.length) { var sz = b[pos++]; if (!sz) break; pos += sz; }
        continue;
      }
      if (t !== 0x2C) throw new Error('malformed GIF block');
      var fx = b[pos] | (b[pos + 1] << 8), fy = b[pos + 2] | (b[pos + 3] << 8), fw = b[pos + 4] | (b[pos + 5] << 8), fh = b[pos + 6] | (b[pos + 7] << 8), ff = b[pos + 8];
      pos += 9;
      var ct = gct;
      if (ff & 0x80) { var ln = 3 << ((ff & 7) + 1); ct = b.subarray(pos, pos + ln); pos += ln; }
      if (!ct) throw new Error('GIF frame without colour table');
      var minSize = b[pos++], chunks = [], total = 0;
      while (pos < b.length) { var s2 = b[pos++]; if (!s2) break; chunks.push(b.subarray(pos, pos + s2)); total += s2; pos += s2; }
      if ((frames.length + 1) * W * H > MAX_FRAME_PIXELS_TOTAL || frames.length >= MAX_FRAMES) break;
      var data = new Uint8Array(total), o = 0; chunks.forEach(function (c) { data.set(c, o); o += c.length; });
      var idx = lzwDecode(data, minSize, fw * fh);
      if (gce.disposal === 3) prev = new Uint8ClampedArray(canvas);
      var rowsOrder = [];
      if (ff & 0x40) { [[0, 8], [4, 8], [2, 4], [1, 2]].forEach(function (pp) { for (var r = pp[0]; r < fh; r += pp[1]) rowsOrder.push(r); }); }
      else for (var r2 = 0; r2 < fh; r2++) rowsOrder.push(r2);
      for (var k = 0; k < fh; k++) {
        var yy = fy + rowsOrder[k]; if (yy >= H) continue;
        for (var x = 0; x < fw; x++) {
          var xx = fx + x; if (xx >= W) continue;
          var ci = idx[k * fw + x]; if (ci === gce.trans) continue;
          var di = (yy * W + xx) * 4; canvas[di] = ct[ci * 3]; canvas[di + 1] = ct[ci * 3 + 1]; canvas[di + 2] = ct[ci * 3 + 2]; canvas[di + 3] = 255;
        }
      }
      frames.push(new Uint8ClampedArray(canvas)); durations.push(gce.delay);
      if (gce.disposal === 2) { for (var y3 = fy; y3 < Math.min(H, fy + fh); y3++) for (var x3 = fx; x3 < Math.min(W, fx + fw); x3++) { var d3 = (y3 * W + x3) * 4; canvas[d3] = canvas[d3 + 1] = canvas[d3 + 2] = canvas[d3 + 3] = 0; } }
      else if (gce.disposal === 3 && prev) canvas = prev;
      gce = { disposal: 0, trans: -1, delay: 100 };
    }
    void bgIndex;
    return { w: W, h: H, frames: frames, durations: durations, loop: loop };
  }

  // ---------------------------------------------------------------- GIF encoder
  function lzwEncode(idx, minSize) {
    var clear = 1 << minSize, eoi = clear + 1, size = minSize + 1, next = eoi + 1, dict = new Map(), out = [], acc = 0, bits = 0;
    var emit = function (code) { acc |= code << bits; bits += size; while (bits >= 8) { out.push(acc & 255); acc >>>= 8; bits -= 8; } };
    emit(clear);
    var cur = idx[0];
    for (var i = 1; i < idx.length; i++) {
      var k = idx[i], key = cur * 256 + k, hit = dict.get(key);
      if (hit !== undefined) { cur = hit; continue; }
      emit(cur);
      if (next < 4096) { dict.set(key, next++); if (next > (1 << size) && size < 12) size++; }
      else { emit(clear); dict.clear(); size = minSize + 1; next = eoi + 1; }
      cur = k;
    }
    emit(cur); emit(eoi);
    if (bits > 0) out.push(acc & 255);
    return out;
  }
  /* frames: array of {w,h,data:RGBA}; durations ms. Builds one global 256-colour median-cut palette. */
  function encodeGif(frames, durations, loop) {
    var W = frames[0].w, H = frames[0].h, samples = [], f, i;
    frames.forEach(function (fr) { var step = Math.max(1, Math.floor(fr.w * fr.h / 4000)); for (i = 0; i < fr.w * fr.h; i += step) samples.push(fr.data[i * 4] / 255, fr.data[i * 4 + 1] / 255, fr.data[i * 4 + 2] / 255); });
    var pal = IC().medianCut(new Float64Array(samples), samples.length / 3, 256).map(function (c) { return [Math.round(c[0] * 255), Math.round(c[1] * 255), Math.round(c[2] * 255)]; });
    while (pal.length < 256) pal.push([0, 0, 0]);
    var cache = new Map(), nearest = function (r, g, b) {
      var key = (r << 16) | (g << 8) | b, hit = cache.get(key); if (hit !== undefined) return hit;
      var bd = Infinity, bi = 0; for (var j = 0; j < 256; j++) { var p = pal[j], d = (r - p[0]) * (r - p[0]) + (g - p[1]) * (g - p[1]) + (b - p[2]) * (b - p[2]); if (d < bd) { bd = d; bi = j; } }
      cache.set(key, bi); return bi;
    };
    var out = [], push = function () { for (var a = 0; a < arguments.length; a++) out.push(arguments[a]); }, u16 = function (v) { push(v & 255, (v >> 8) & 255); };
    'GIF89a'.split('').forEach(function (c) { out.push(c.charCodeAt(0)); });
    u16(W); u16(H); push(0xF7, 0, 0);
    pal.forEach(function (p) { push(p[0], p[1], p[2]); });
    push(0x21, 0xFF, 11); 'NETSCAPE2.0'.split('').forEach(function (c) { out.push(c.charCodeAt(0)); }); push(3, 1); u16(loop ? 0 : 1); push(0);
    for (f = 0; f < frames.length; f++) {
      var fr = frames[f], idx = new Uint8Array(W * H);
      for (i = 0; i < W * H; i++) { var a = fr.data[i * 4 + 3] / 255; idx[i] = nearest(Math.round(fr.data[i * 4] * a), Math.round(fr.data[i * 4 + 1] * a), Math.round(fr.data[i * 4 + 2] * a)); }
      push(0x21, 0xF9, 4, 4); u16(Math.max(2, Math.round((durations[f] || 100) / 10))); push(0, 0);
      push(0x2C); u16(0); u16(0); u16(W); u16(H); push(0);
      push(8);
      var lz = lzwEncode(idx, 8);
      for (i = 0; i < lz.length; i += 255) { var chunk = lz.slice(i, i + 255); out.push(chunk.length); for (var c2 = 0; c2 < chunk.length; c2++) out.push(chunk[c2]); }
      push(0);
    }
    push(0x3B);
    return new Uint8Array(out);
  }

  // ---------------------------------------------------------------- baseline TIFF decoder
  function decodeTiff(b) {
    var le = b[0] === 0x49, dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    var u16 = function (o) { return dv.getUint16(o, le); }, u32 = function (o) { return dv.getUint32(o, le); };
    var ifd = u32(4), n = u16(ifd), tags = {};
    for (var i = 0; i < n; i++) {
      var e = ifd + 2 + i * 12, tag = u16(e), type = u16(e + 2), cnt = u32(e + 4), sz = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8 }[type] || 1, vo = cnt * sz <= 4 ? e + 8 : u32(e + 8), vals = [];
      for (var k = 0; k < Math.min(cnt, 1 << 20); k++) vals.push(type === 3 ? u16(vo + k * 2) : type === 4 ? u32(vo + k * 4) : b[vo + k]);
      tags[tag] = vals;
    }
    var W = tags[256][0], H = tags[257][0], spp = (tags[277] || [1])[0], bps = (tags[258] || [1])[0], comp = (tags[259] || [1])[0], photo = (tags[262] || [1])[0];
    var pred = (tags[317] || [1])[0], planar = (tags[284] || [1])[0], offs = tags[273], counts = tags[279], rps = (tags[278] || [H])[0];
    if (!W || !H || W * H > 50000000) throw new Error('invalid TIFF dimensions');
    if (bps !== 8 || planar !== 1 || [1, 5, 32773].indexOf(comp) < 0) throw new Error('unsupported TIFF variant (only 8-bit, chunky, uncompressed/LZW/PackBits are decoded in the browser)');
    var raw = new Uint8Array(W * H * spp), rp = 0;
    offs.forEach(function (off, s) {
      var src = b.subarray(off, off + counts[s]), rowsHere = Math.min(rps, H - s * rps), need = rowsHere * W * spp, dec;
      if (comp === 1) dec = src;
      else if (comp === 32773) { dec = new Uint8Array(need); var p = 0, q = 0; while (p < src.length && q < need) { var c = src[p++]; c = c > 127 ? c - 256 : c; if (c >= 0) { for (var j = 0; j <= c && q < need; j++) dec[q++] = src[p++]; } else if (c !== -128) { var v = src[p++]; for (var j2 = 0; j2 < 1 - c && q < need; j2++) dec[q++] = v; } } }
      else {
        dec = new Uint8Array(need); var tab = [], size = 9, bitPos = 0, q2 = 0, prevS = null;
        var reset = function () { tab = []; for (var t = 0; t < 256; t++) tab.push([t]); tab.push(null, null); size = 9; };
        reset();
        for (;;) {
          if ((bitPos + size) > src.length * 8) break;
          var code = 0; for (var bb = 0; bb < size; bb++) { var bit = (src[(bitPos + bb) >> 3] >> (7 - ((bitPos + bb) & 7))) & 1; code = (code << 1) | bit; }
          bitPos += size;
          if (code === 257) break;
          if (code === 256) { reset(); prevS = null; continue; }
          var entry = code < tab.length && tab[code] ? tab[code] : (prevS ? prevS.concat([prevS[0]]) : null);
          if (!entry) break;
          for (var e2 = 0; e2 < entry.length && q2 < need; e2++) dec[q2++] = entry[e2];
          if (prevS) tab.push(prevS.concat([entry[0]]));
          prevS = entry;
          if (tab.length + 1 >= (1 << size) && size < 12) size++;
        }
      }
      raw.set(dec.subarray(0, Math.min(need, raw.length - rp)), rp); rp += need;
    });
    if (pred === 2) for (var y = 0; y < H; y++) for (var x = 1; x < W; x++) for (var c2 = 0; c2 < spp; c2++) { var o = (y * W + x) * spp + c2; raw[o] = (raw[o] + raw[o - spp]) & 255; }
    var out = new Uint8ClampedArray(W * H * 4), cmap = tags[320];
    for (i = 0; i < W * H; i++) {
      var r, g, bl, a = 255;
      if (photo === 2) { r = raw[i * spp]; g = raw[i * spp + 1]; bl = raw[i * spp + 2]; if (spp >= 4) a = raw[i * spp + 3]; }
      else if (photo === 3 && cmap) { var ix = raw[i * spp], ncol = cmap.length / 3; r = cmap[ix] >> 8; g = cmap[ncol + ix] >> 8; bl = cmap[2 * ncol + ix] >> 8; }
      else { var v2 = raw[i * spp]; if (photo === 0) v2 = 255 - v2; r = g = bl = v2; if (spp >= 2) a = raw[i * spp + 1]; }
      out[i * 4] = r; out[i * 4 + 1] = g; out[i * 4 + 2] = bl; out[i * 4 + 3] = a;
    }
    return { w: W, h: H, data: out };
  }

  // ---------------------------------------------------------------- animation conversion & exports
  function selectFrames(n, start, end, step) {
    end = (end === undefined || end < 0 || end >= n) ? n - 1 : end; start = Math.max(0, Math.min(start || 0, end)); step = Math.max(1, step || 1);
    var out = []; for (var i = start; i <= end && out.length < MAX_FRAMES; i += step) out.push(i);
    return out;
  }
  function convertAnimation(frames, durations, params, start, end, step, fps, progress) {
    var idx = selectFrames(frames.length, start, end, step), p = LB.imgmodes.sanitizeParams(params), arts = [], durs = [], t0 = Date.now();
    idx.forEach(function (i, k) {
      arts.push(LB.imgmodes.renderImageArt(frames[i], p).art);
      if (fps > 0) durs.push(Math.round(1000 / fps));
      else { var s = 0; for (var j = i; j < Math.min(frames.length, i + Math.max(1, step || 1)); j++) s += durations[j]; durs.push(s); }
      if (progress) progress(k + 1, idx.length);
    });
    return { arts: arts, durations: durs, stats: { frames: arts.length, ms: Date.now() - t0, mode: p.mode } };
  }
  function toAnimatedHtml(arts, durs, s, loop, title) {
    s = LB.exporter.settings(s);
    var data = JSON.stringify({ frames: arts.map(function (a) { return LB.exporter.toHtmlFragment(a, s); }), durations: durs.map(function (d) { return Math.max(10, d | 0); }), loop: !!loop });
    data = data.replace(/<\//g, '<\\/').replace(/<!--/g, '<\\!--');
    var esc = function (t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'">' +
      '<title>' + esc(title || 'LeerBox Animation') + '</title><style>body{margin:0;background:' + (s.transparent ? 'transparent' : esc(s.background)) + ';color:#ccc;font:13px system-ui}#bar{position:fixed;bottom:8px;right:8px;opacity:.8}button{font:inherit}</style></head><body>' +
      '<div id="stage"></div><div id="bar"><button id="pp">Pause</button> <span id="fi"></span></div>' +
      '<script>var D=' + data + ";var i=0,playing=true,t=null,st=document.getElementById('stage'),fi=document.getElementById('fi');" +
      "function show(){st.innerHTML=D.frames[i];fi.textContent=(i+1)+'/'+D.frames.length;}" +
      "function step(){show();t=setTimeout(function(){i++;if(i>=D.frames.length){if(!D.loop){i=D.frames.length-1;return;}i=0;}if(playing)step();},D.durations[i]);}" +
      "document.getElementById('pp').onclick=function(){playing=!playing;this.textContent=playing?'Pause':'Play';if(playing){clearTimeout(t);step();}};step();</script></body></html>\n";
  }
  function toAnsiScript(arts, durs, shell, mode, loop) {
    var frames = arts.map(function (a) { return LB.exporter.toAnsi(a, mode || 'truecolor'); });
    if (shell === 'powershell') {
      var L = ['# LeerBox ANSI animation (PowerShell 7+). Ctrl+C to stop.', '$e = [char]27', '$frames = @('];
      frames.forEach(function (f) { L.push("  ('" + f.replace(/'/g, "''").replace(/\x1b/g, "' + $e + '") + "'),"); });
      L[L.length - 1] = L[L.length - 1].replace(/,$/, '');
      L.push(')', '$delays = @(' + durs.map(function (d) { return Math.max(10, d | 0); }).join(', ') + ')', '[Console]::Write("$e[2J$e[?25l")', 'try {', '  do {',
        '    for ($i = 0; $i -lt $frames.Count; $i++) {', '      [Console]::Write("$e[H" + $frames[$i]); Start-Sleep -Milliseconds $delays[$i]', '    }',
        '  } while ($' + (loop ? 'true' : 'false') + ')', '} finally { [Console]::Write("$e[0m$e[?25h") }', '');
      return L.join('\n');
    }
    var out = ['#!/usr/bin/env bash', '# LeerBox ANSI animation. Ctrl+C to stop.', 'frames=()'];
    frames.forEach(function (f) { out.push("frames+=($'" + f.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\x1b/g, '\\e').replace(/\n/g, '\\n') + "')"); });
    out.push('delays=(' + durs.map(function (d) { return (Math.max(10, d | 0) / 1000).toFixed(3); }).join(' ') + ')');
    var body = ['for i in "${!frames[@]}"; do', "  printf '\\e[H%s' \"${frames[$i]}\"", '  sleep "${delays[$i]}"', 'done'];
    out.push("trap 'printf \"\\e[0m\\e[?25h\\n\"; exit' INT TERM", "printf '\\e[2J\\e[?25l'");
    out = out.concat(loop ? ['while :; do'].concat(body.map(function (b) { return '  ' + b; }), ['done']) : body);
    out.push("printf '\\e[0m\\e[?25h\\n'", '');
    return out.join('\n');
  }
  async function toFrameZip(arts, fmt, s, durs) {
    var files = [], enc = new TextEncoder(), ext = { txt: 'txt', ansi: 'ans', png: 'png', svg: 'svg', html: 'html' }[fmt];
    for (var i = 0; i < arts.length; i++) {
      var blob = await LB.exporter.exportBlob(arts[i], fmt, s);
      files.push({ name: 'frame_' + ('000' + (i + 1)).slice(-4) + '.' + ext, data: new Uint8Array(await blob.arrayBuffer()) });
    }
    files.push({ name: 'frames.json', data: enc.encode(JSON.stringify({ frames: arts.length, durations_ms: durs || arts.map(function () { return 100; }), format: ext }, null, 1)) });
    return LB.zipWrite(files);
  }

  // ---------------------------------------------------------------- typographic composition (graphical)
  function composeTypographic(src, params, fontSize, vary, rotate, maxSide) {
    var p = LB.imgmodes.sanitizeParams(params), fs = Math.max(4, Math.min(64, +fontSize || 12)), cw = fs * 0.6021, lh = fs * 1.15, img = src;
    if (rotate === 90) img = IC().rotate90(src, 270);
    var scale = Math.min(1, (maxSide || 2400) / Math.max(img.w, img.h)), Wd = img.w * scale, Hd = img.h * scale;
    var cols = Math.max(4, Math.floor(Wd / cw)), rows = Math.max(2, Math.floor(Hd / lh)), smp = IC().resampleArea(img, cols, rows);
    var rgb = IC().composite(smp, p.light_on_dark ? 0x000000 : 0xFFFFFF), ts = LB.imgmodes.textStream(p.text, p.text_dir), stream = ts[0], rtl = ts[1], runs = [], k = 0;
    for (var y = 0; y < rows; y++) for (var j = 0; j < cols; j++) {
      var x = rtl ? cols - 1 - j : j, i = y * cols + x;
      if (p.transparent_bg && smp.a[i] < 0.5) continue;
      var g = stream[k % stream.length][0]; k++;
      if (!g.trim()) continue;
      var v = IC().lumOf(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 'rec709'), ink = p.light_on_dark ? v : 1 - v;
      var color = p.color !== 'none' ? '#' + [0, 1, 2].map(function (q) { return ('0' + Math.floor(rgb[i * 3 + q] * 255 + 0.5).toString(16)).slice(-2); }).join('') : (p.light_on_dark ? '#ffffff' : '#000000');
      var run = { x: Math.round(x * cw * 100) / 100, y: Math.round((y * lh + fs) * 100) / 100, ch: g, color: color, alpha: 1, size: fs, bold: false };
      if (vary === 'opacity') run.alpha = Math.round(Math.max(0.06, ink) * 1000) / 1000;
      else if (vary === 'size') run.size = Math.round(fs * (0.35 + 0.9 * ink) * 100) / 100;
      else if (vary === 'weight') { run.bold = ink > 0.5; run.alpha = Math.round(Math.max(0.15, ink) * 1000) / 1000; }
      runs.push(run);
    }
    return { kind: 'typographic-composition', width: Math.round(cols * cw * 100) / 100, height: Math.round(rows * lh * 100) / 100,
      background: p.light_on_dark ? '#000000' : '#ffffff', font_size: fs, rotate: rotate || 0, rtl: rtl, runs: runs };
  }
  function compositionSvg(comp) {
    var esc = function (t) { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }, W = comp.width, H = comp.height;
    var g = comp.rotate === 90 ? '<g transform="rotate(90 ' + W / 2 + ' ' + H / 2 + ')" font-family="DejaVu Sans Mono, Consolas, monospace">' : '<g font-family="DejaVu Sans Mono, Consolas, monospace">';
    var out = ['<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">', '<rect width="100%" height="100%" fill="' + comp.background + '"/>', g];
    comp.runs.forEach(function (r) { out.push('<text x="' + r.x + '" y="' + r.y + '" font-size="' + r.size + '" fill="' + r.color + '"' + (r.alpha < 1 ? ' fill-opacity="' + r.alpha + '"' : '') + (r.bold ? ' font-weight="bold"' : '') + '>' + esc(r.ch) + '</text>'); });
    out.push('</g></svg>\n');
    return out.join('');
  }
  function compositionCanvas(comp, scale) {
    scale = scale || 1;
    var W = Math.round(comp.width * scale), H = Math.round(comp.height * scale), cv = document.createElement('canvas'), cx;
    var rot = comp.rotate === 90;
    cv.width = rot ? H : W; cv.height = rot ? W : H; cx = cv.getContext('2d');
    cx.fillStyle = comp.background; cx.fillRect(0, 0, cv.width, cv.height);
    if (rot) { cx.translate(H, 0); cx.rotate(Math.PI / 2); }
    comp.runs.forEach(function (r) {
      cx.globalAlpha = r.alpha; cx.fillStyle = r.color;
      cx.font = (r.bold ? 'bold ' : '') + Math.max(3, Math.round(r.size * scale)) + "px 'LeerBox Mono','DejaVu Sans Mono',sans-serif";
      cx.fillText(r.ch, r.x * scale, r.y * scale);
    });
    cx.globalAlpha = 1;
    return cv;
  }
  function comparisonCanvas(src, art, s, layout) {
    var ac = LB.exporter.renderCanvas(art, s), oc = document.createElement('canvas'), id = new ImageData(IC().toRgba(src), src.w, src.h);
    oc.width = src.w; oc.height = src.h; oc.getContext('2d').putImageData(id, 0, 0);
    var h = ac.height, w = Math.max(1, Math.round(src.w * h / src.h)), gap = 16, cv = document.createElement('canvas'), cx;
    if (layout === 'stack') { w = ac.width; h = Math.max(1, Math.round(src.h * w / src.w)); cv.width = ac.width; cv.height = h + gap + ac.height; }
    else { cv.width = w + gap + ac.width; cv.height = Math.max(h, ac.height); }
    cx = cv.getContext('2d'); cx.fillStyle = LB.exporter.settings(s).background; cx.fillRect(0, 0, cv.width, cv.height);
    cx.imageSmoothingQuality = 'high'; cx.drawImage(oc, 0, 0, w, h);
    if (layout === 'stack') cx.drawImage(ac, 0, h + gap); else cx.drawImage(ac, w + gap, 0);
    return cv;
  }

  // ---------------------------------------------------------------- Image Studio projects
  var MAX_PROJECT_IMAGE = 25 * 1024 * 1024;
  function bytesToB64(bytes) { var s = ''; for (var i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)); return btoa(s); }
  function makeImageProject(params, imageBytes, imageName, effects, exp, workspace) {
    if (imageBytes && imageBytes.length > MAX_PROJECT_IMAGE) imageBytes = null;
    return JSON.stringify({ format: 'leerbox-image-project', version: 1, workspace: workspace || 'image', params: LB.imgmodes.sanitizeParams(params),
      effects: effects || [], export: exp || {}, image: imageBytes ? { name: String(imageName || '').slice(0, 200), data: bytesToB64(imageBytes) } : null });
  }
  function parseImageProject(text) {
    if (text.length > 40 * 1024 * 1024) throw new Error('project file too large');
    var d; try { d = JSON.parse(text.replace(/^﻿/, '')); } catch (e) { throw new Error('invalid project: ' + e.message); }
    if (!d || typeof d !== 'object' || d.format !== 'leerbox-image-project') throw new Error('not a LeerBox image project');
    var out = { workspace: d.workspace === 'animation' ? 'animation' : 'image', params: LB.imgmodes.sanitizeParams(d.params && typeof d.params === 'object' ? d.params : {}),
      effects: LB.project.sanitizeEffects(d.effects || []), export: d.export && typeof d.export === 'object' ? d.export : {}, image: null, image_name: '' };
    if (d.image && typeof d.image.data === 'string') {
      if (!/^[A-Za-z0-9+/=\s]*$/.test(d.image.data)) throw new Error('embedded image is not valid base64');
      var raw = LB.b64ToBytes(d.image.data.replace(/\s+/g, ''));
      if (raw.length > MAX_PROJECT_IMAGE) throw new Error('embedded image too large');
      out.image = raw; out.image_name = String(d.image.name || '').slice(0, 200);
    }
    return out;
  }

  LB.imganim = { decodeGif: decodeGif, lzwDecode: lzwDecode, encodeGif: encodeGif, decodeTiff: decodeTiff, selectFrames: selectFrames, convertAnimation: convertAnimation,
    toAnimatedHtml: toAnimatedHtml, toAnsiScript: toAnsiScript, toFrameZip: toFrameZip, composeTypographic: composeTypographic, compositionSvg: compositionSvg,
    compositionCanvas: compositionCanvas, comparisonCanvas: comparisonCanvas, makeImageProject: makeImageProject, parseImageProject: parseImageProject, bytesToB64: bytesToB64 };
  LB.imgcodecs = { decodeGif: decodeGif, decodeTiff: decodeTiff, encodeGif: encodeGif };
  if (typeof module !== 'undefined' && module.exports) module.exports = LB;
})(LB);
