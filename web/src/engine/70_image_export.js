/* LeerBox — image-to-art conversion and the export system (ports of imageart.py / export.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };
  var C = function () { return LB.color; };

  // ------------------------------------------------------------------ image art
  var RAMPS = { standard: ' .:-=+*#%@', detailed: " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    blocks: ' \u2591\u2592\u2593\u2588', simple: ' .oO@', dots: ' \u00b7\u2022\u25cf', binary: ' 01', lines: ' -=\u2261' };
  var BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  var QUAD = cps(' \u2598\u259d\u2580\u2596\u258c\u259e\u259b\u2597\u259a\u2590\u259c\u2584\u2599\u259f\u2588');
  function resample(img, tw, th) {
    tw = Math.max(1, tw); th = Math.max(1, th);
    var n = tw * th, sr = new Float64Array(n), sg = new Float64Array(n), sb = new Float64Array(n), cnt = new Uint32Array(n);
    var W = img.width, H = img.height, px = img.pixels, xs = new Uint32Array(W), x, y;
    for (x = 0; x < W; x++) xs[x] = Math.min(tw - 1, Math.floor(x * tw / W));
    for (y = 0; y < H; y++) {
      var ty = Math.min(th - 1, Math.floor(y * th / H)) * tw, base = y * W;
      for (x = 0; x < W; x++) { var p = px[base + x], i = ty + xs[x]; sr[i] += p >> 16; sg[i] += (p >> 8) & 255; sb[i] += p & 255; cnt[i]++; }
    }
    var out = [];
    for (y = 0; y < th; y++) { var r = []; for (x = 0; x < tw; x++) { var k = y * tw + x, c = Math.max(1, cnt[k]); r.push(C().joinRgb(sr[k] / c, sg[k] / c, sb[k] / c)); } out.push(r); }
    return out;
  }
  function luma(c) { return (0.2126 * ((c >> 16) & 255) + 0.7152 * ((c >> 8) & 255) + 0.0722 * (c & 255)) / 255; }
  function adjust(v, o) {
    v = (v - 0.5) * o.contrast + 0.5 + o.brightness;
    v = v < 0 ? 0 : v > 1 ? 1 : v;
    if (o.gamma !== 1 && v > 0) v = Math.pow(v, o.gamma);
    return o.invert ? 1 - v : v;
  }
  function quantize(gray, levels, dither) {
    var h = gray.length, w = h ? gray[0].length : 0, g = gray.map(function (r) { return r.slice(); }), out = [], n = levels - 1;
    for (var y = 0; y < h; y++) {
      var row = [];
      for (var x = 0; x < w; x++) {
        var v = g[y][x];
        if (dither === 'ordered') v = v + (BAYER4[y % 4][x % 4] / 16 - 0.5) / Math.max(1, n);
        var q = Math.floor(v * n + 0.5); q = q < 0 ? 0 : q > n ? n : q;
        row.push(q);
        if (dither === 'floyd' || dither === 'atkinson') {
          var err = v - q / Math.max(1, n), list = dither === 'floyd'
            ? [[1, 0, 7 / 16], [-1, 1, 3 / 16], [0, 1, 5 / 16], [1, 1, 1 / 16]]
            : [[1, 0, 1 / 8], [2, 0, 1 / 8], [-1, 1, 1 / 8], [0, 1, 1 / 8], [1, 1, 1 / 8], [0, 2, 1 / 8]];
          list.forEach(function (d) { var xx = x + d[0], yy = y + d[1]; if (xx >= 0 && xx < w && yy < h) g[yy][xx] += err * d[2]; });
        }
      }
      out.push(row);
    }
    return out;
  }
  function imageToArt(img, o) {
    o = Object.assign({ cols: 100, mode: 'ascii', ramp: 'standard', brightness: 0, contrast: 1, gamma: 1, invert: false, dither: 'none',
      color: 'none', aspect: 0.5, threshold: 0.5 }, o || {});
    var cols = Math.max(4, Math.min(1000, o.cols | 0)), aspect = Math.max(0.2, Math.min(2, o.aspect));
    var rows = Math.max(1, Math.floor(img.height / img.width * cols * aspect + 0.5)), colored = o.color !== 'none';
    var art = LB.Art.blank(cols, rows), x, y;
    if (o.mode === 'half') {
      var grid = resample(img, cols, rows * 2);
      for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
        var top = grid[2 * y][x], bot = 2 * y + 1 < grid.length ? grid[2 * y + 1][x] : 0xFFFFFF;
        if (colored) { art.chars[y][x] = '\u2580'; art.fg[y][x] = top; art.bg[y][x] = bot; }
        else { var a = adjust(luma(top), o) < o.threshold ? 1 : 0, b = adjust(luma(bot), o) < o.threshold ? 1 : 0; art.chars[y][x] = ' \u2580\u2584\u2588'[a | (b << 1)]; }
      }
      return art;
    }
    if (o.mode === 'braille' || o.mode === 'quarter') {
      var sx = 2, sy = o.mode === 'braille' ? 4 : 2, g2 = resample(img, cols * sx, rows * sy);
      var gray = g2.map(function (r) { return r.map(function (c) { return adjust(luma(c), o); }); }), bits;
      if (o.dither !== 'none') bits = quantize(gray, 2, o.dither).map(function (r) { return r.map(function (v) { return 1 - v; }); });
      else bits = gray.map(function (r) { return r.map(function (v) { return v < o.threshold ? 1 : 0; }); });
      for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) {
        var bt = function (dx, dy) { var yy = y * sy + dy, xx = x * sx + dx; return yy < bits.length && xx < bits[0].length ? bits[yy][xx] : 0; };
        if (o.mode === 'braille') {
          var v = bt(0, 0) | (bt(0, 1) << 1) | (bt(0, 2) << 2) | (bt(1, 0) << 3) | (bt(1, 1) << 4) | (bt(1, 2) << 5) | (bt(0, 3) << 6) | (bt(1, 3) << 7);
          art.chars[y][x] = String.fromCharCode(0x2800 + v);
        } else art.chars[y][x] = QUAD[bt(0, 0) | (bt(1, 0) << 1) | (bt(0, 1) << 2) | (bt(1, 1) << 3)];
        if (colored) {
          var rs = 0, gs = 0, bs = 0, n = 0;
          for (var dy = 0; dy < sy; dy++) for (var dx = 0; dx < sx; dx++) { var yy = y * sy + dy, xx = x * sx + dx; if (yy < g2.length && xx < g2[0].length) { var c = g2[yy][xx]; rs += c >> 16; gs += (c >> 8) & 255; bs += c & 255; n++; } }
          n = Math.max(1, n); art.fg[y][x] = C().joinRgb(rs / n, gs / n, bs / n);
        }
      }
      return art;
    }
    var ramp = o.mode === 'ascii' ? (RAMPS[o.ramp] || o.ramp) : RAMPS.blocks;
    var chars = LB.figlet.graphemes(ramp); if (!chars.length) chars = cps(' .:-=+*#%@'); if (chars.length < 2) chars = [' '].concat(chars);
    var g3 = resample(img, cols, rows);
    var q = quantize(g3.map(function (r) { return r.map(function (c) { return 1 - adjust(luma(c), o); }); }), chars.length, o.dither);
    for (y = 0; y < rows; y++) for (x = 0; x < cols; x++) { art.chars[y][x] = chars[q[y][x]]; if (colored) art.fg[y][x] = g3[y][x]; }
    return art;
  }

  // ------------------------------------------------------------------ exports
  var ANSI16 = [[0, 0, 0], [205, 49, 49], [13, 188, 121], [229, 229, 16], [36, 114, 200], [188, 63, 188], [17, 168, 205], [229, 229, 229],
    [102, 102, 102], [241, 76, 76], [35, 209, 139], [245, 245, 67], [59, 142, 234], [214, 112, 214], [41, 184, 219], [255, 255, 255]];
  var SET_DEFAULTS = { font_size: 16, line_height: 1.2, padding: 24, background: '#0d1117', transparent: false, foreground: '#e6edf3',
    scale: 1.0, ansi_mode: 'truecolor', embed_font: false, jpeg_quality: 92, title: 'LeerBox Text Art', letter_spacing: 0 };
  function settings(d) {
    var s = Object.assign({}, SET_DEFAULTS);
    Object.keys(d || {}).forEach(function (k) {
      if (!(k in SET_DEFAULTS)) return;
      var t = typeof SET_DEFAULTS[k], v = d[k];
      if (t === 'number') { var n = parseFloat(v); if (!isNaN(n)) s[k] = (k === 'font_size' || k === 'padding' || k === 'jpeg_quality') ? Math.trunc(n) : n; }
      else if (t === 'boolean') s[k] = !!v; else s[k] = String(v);
    });
    s.font_size = Math.max(4, Math.min(200, s.font_size)); s.padding = Math.max(0, Math.min(1000, s.padding));
    s.scale = Math.max(0.25, Math.min(8, s.scale)); s.line_height = Math.max(0.8, Math.min(3, s.line_height));
    s.jpeg_quality = Math.max(10, Math.min(100, s.jpeg_quality));
    s.letter_spacing = Math.max(0, Math.min(2, s.letter_spacing));
    return s;
  }
  function clean(c) { return cps(c).map(function (ch) { var o = ch.codePointAt(0); return (o >= 32 && !(o >= 0x7F && o < 0xA0)) ? ch : ' '; }).join(''); }
  function rstripPy(s) { var a = cps(s), k = a.length; while (k > 0 && LB.figlet.PY_SPACE.has(a[k - 1])) k--; return a.slice(0, k).join(''); }
  function toTxt(art) { return art.chars.map(function (r) { return rstripPy(r.map(clean).join('')); }).join('\n') + '\n'; }
  function rgbTo256(c) {
    var r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
    if (r === g && g === b) { if (r < 8) return 16; if (r > 248) return 231; return 232 + Math.floor((r - 8) / 247 * 24 + 0.5); }
    var q = function (v) { return v < 48 ? 0 : v < 115 ? 1 : Math.floor((v - 35) / 40); };
    return 16 + 36 * q(r) + 6 * q(g) + q(b);
  }
  function rgbTo16(c) {
    var r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255, best = 0, bd = Infinity;
    ANSI16.forEach(function (p, i) { var d = (r - p[0]) * (r - p[0]) + (g - p[1]) * (g - p[1]) + (b - p[2]) * (b - p[2]); if (d < bd) { best = i; bd = d; } });
    return best;
  }
  function sgr(fg, bg, mode) {
    var parts = ['0'];
    if (fg !== null) {
      if (mode === 'truecolor') parts.push('38;2;' + C().splitRgb(fg).join(';'));
      else if (mode === '256') parts.push('38;5;' + rgbTo256(fg));
      else { var i = rgbTo16(fg); parts.push(String(i < 8 ? 30 + i : 90 + i - 8)); }
    }
    if (bg !== null) {
      if (mode === 'truecolor') parts.push('48;2;' + C().splitRgb(bg).join(';'));
      else if (mode === '256') parts.push('48;5;' + rgbTo256(bg));
      else { var j = rgbTo16(bg); parts.push(String(j < 8 ? 40 + j : 100 + j - 8)); }
    }
    return '\x1b[' + parts.join(';') + 'm';
  }
  function toAnsi(art, mode) {
    if (mode === 'none') return toTxt(art);
    var lines = [];
    for (var y = 0; y < art.height; y++) {
      var row = art.chars[y], out = [], cf = null, cb = null, last = row.length;
      while (last > 0 && (row[last - 1] === ' ' || row[last - 1] === '') && art.bg[y][last - 1] === null) last--;
      for (var x = 0; x < last; x++) {
        var c = row[x];
        if (c === '') continue;
        var f = c !== ' ' ? art.fg[y][x] : null, b = art.bg[y][x];
        if (f !== cf || b !== cb) { out.push((f !== null || b !== null) ? sgr(f, b, mode) : '\x1b[0m'); cf = f; cb = b; }
        out.push(clean(c));
      }
      if (cf !== null || cb !== null) out.push('\x1b[0m');
      lines.push(out.join(''));
    }
    return lines.join('\n') + '\n';
  }
  var FONT_STACK = "'DejaVu Sans Mono','Cascadia Mono',Consolas,Menlo,'Liberation Mono',monospace";
  function esc(s, quote) {
    s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return quote === false ? s : s.replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }
  function runs(art, y) {
    var row = art.chars[y], out = [], x = 0, w = row.length;
    while (x < w) {
      var fg = art.fg[y][x], bg = art.bg[y][x], start = x, buf = [];
      while (x < w && art.fg[y][x] === fg && art.bg[y][x] === bg) { buf.push(row[x] !== '' ? clean(row[x]) : ''); x++; }
      out.push([start, buf.join(''), fg, bg]);
    }
    return out;
  }
  function fontFaceCss() { return LB.resources.monoFontB64 ? "@font-face{font-family:'DejaVu Sans Mono';src:url(data:font/ttf;base64," + LB.resources.monoFontB64 + ") format('truetype');}" : ''; }
  function toHtmlFragment(art, s) {
    s = settings(s);
    var glow = art.meta.glow, shadow = '';
    if (glow) shadow = 'text-shadow:0 0 ' + glow.radius + 'px ' + esc(glow.color) + ',0 0 ' + (glow.radius * 2) + 'px ' + esc(glow.color) + ';';
    var bg = s.transparent ? 'transparent' : esc(s.background);
    var parts = ['<pre style="margin:0;padding:' + s.padding + 'px;background:' + bg + ';color:' + esc(s.foreground) + ';font:' + s.font_size + 'px/' + s.line_height + ' ' + FONT_STACK + ';' + shadow + 'white-space:pre' + (s.letter_spacing ? ';letter-spacing:' + (s.letter_spacing * 0.6021).toFixed(3) + 'em' : '') + '">'];
    for (var y = 0; y < art.height; y++) {
      runs(art, y).forEach(function (r) {
        var e = esc(r[1], false);
        if (r[2] === null && r[3] === null) parts.push(e);
        else parts.push('<span style="' + (r[2] !== null ? 'color:' + C().rgbToHex(r[2]) + ';' : '') + (r[3] !== null ? 'background:' + C().rgbToHex(r[3]) + ';' : '') + '">' + e + '</span>');
      });
      parts.push('\n');
    }
    parts.push('</pre>');
    return parts.join('');
  }
  function toHtml(art, s) {
    s = settings(s);
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(s.title) +
      '</title><style>' + (s.embed_font ? fontFaceCss() : '') + 'body{margin:0;background:' + (s.transparent ? 'transparent' : esc(s.background)) + '}</style></head><body>' + toHtmlFragment(art, s) + '</body></html>\n';
  }
  function f2(n) { return n.toFixed(2); }
  function toSvg(art, s) {
    s = settings(s);
    var fs = s.font_size * s.scale, cw = fs * 0.6021 * (1 + s.letter_spacing), ch = fs * s.line_height, pad = s.padding * s.scale;
    var W = Math.round((art.width * cw + 2 * pad) * 100) / 100, H = Math.round((art.height * ch + 2 * pad) * 100) / 100, glow = art.meta.glow;
    var out = ['<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">'];
    var style = 'text{font-family:' + FONT_STACK + ';font-size:' + f2(fs) + 'px;white-space:pre}';
    if (s.embed_font) style = fontFaceCss() + style;
    out.push('<style>' + esc(style, false) + '</style>');
    if (glow) out.push('<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="' + f2(Math.max(0.5, glow.radius * s.scale / 2)) + '" result="b"/><feFlood flood-color="' + esc(glow.color) + '" flood-opacity="' + f2(glow.strength) + '"/><feComposite in2="b" operator="in" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>');
    if (!s.transparent) out.push('<rect width="100%" height="100%" fill="' + esc(s.background) + '"/>');
    var y;
    for (y = 0; y < art.height; y++) runs(art, y).forEach(function (r) {
      if (r[3] !== null) out.push('<rect x="' + f2(pad + r[0] * cw) + '" y="' + f2(pad + y * ch) + '" width="' + f2(cps(r[1]).length * cw + 0.5) + '" height="' + f2(ch + 0.5) + '" fill="' + C().rgbToHex(r[3]) + '"/>');
    });
    out.push('<g' + (glow ? ' filter="url(#glow)"' : '') + ' fill="' + esc(s.foreground) + '">');
    var base = fs * 0.8 + (ch - fs) / 2;
    for (y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {  // block elements and sextants as exact rectangles
      var rc = BLOCKS[art.chars[y][x]];
      if (!rc) continue;
      var fc = art.fg[y][x] !== null ? ' fill="' + C().rgbToHex(art.fg[y][x]) + '"' : '';
      rc.forEach(function (q) { out.push('<rect x="' + f2(pad + (x + q[0]) * cw) + '" y="' + f2(pad + (y + q[1]) * ch) + '" width="' + f2((q[2] - q[0]) * cw + 0.3) + '" height="' + f2((q[3] - q[1]) * ch + 0.3) + '"' + fc + '/>'); });
    }
    for (y = 0; y < art.height; y++) {
      var spans = [];
      runs(art, y).forEach(function (r) {
        var t = cps(r[1]).map(function (c) { return BLOCKS[c] ? ' ' : c; }).join('');
        if (!t.trim()) return;
        var lead = cps(t).length - cps(t.replace(/^ +/, '')).length, core = cps(t.replace(/^ +/, '').replace(/ +$/, ''));
        var xs = core.map(function (_, i) { return f2(pad + (r[0] + lead + i) * cw); }).join(' ');
        spans.push('<tspan x="' + xs + '"' + (r[2] !== null ? ' fill="' + C().rgbToHex(r[2]) + '"' : '') + '>' + esc(core.join(''), false) + '</tspan>');
      });
      if (spans.length) out.push('<text y="' + f2(pad + y * ch + base) + '" xml:space="preserve">' + spans.join('') + '</text>');
    }
    out.push('</g></svg>\n');
    return out.join('');
  }
  function toMarkdown(art, title) {
    var body = toTxt(art).replace(/\n$/, ''), fence = '```';
    while (body.indexOf(fence) >= 0) fence += '`';
    return (title ? '## ' + title + '\n\n' : '') + fence + 'text\n' + body + '\n' + fence + '\n';
  }
  function escC(s, quote, nonAscii) {
    quote = quote || '"';
    var out = [];
    cps(s).forEach(function (ch) {
      var o = ch.codePointAt(0);
      if (ch === '\\') out.push('\\\\');
      else if (ch === quote) out.push('\\' + quote);
      else if (ch === '\x1b') out.push(nonAscii === 'octal' ? '\\033' : '\\x1b');
      else if (o < 32 || o === 127) out.push(nonAscii === 'octal' ? '\\' + ('00' + o.toString(8)).slice(-3) : '\\x' + ('0' + o.toString(16)).slice(-2));
      else if (o > 127 && nonAscii === 'octal') new TextEncoder().encode(ch).forEach(function (b) { out.push('\\' + ('00' + b.toString(8)).slice(-3)); });
      else out.push(ch);
    });
    return out.join('');
  }
  var CODE_LANGS = { python: 'Python', javascript: 'JavaScript', c: 'C', cpp: 'C++', powershell: 'PowerShell', bash: 'Bash' };
  function toCode(art, lang, v, ansi) {
    v = v || 'ART';
    var lines = (ansi ? toAnsi(art, ansi) : toTxt(art)).replace(/\n$/, '').split('\n'), lv = v.toLowerCase();
    if (lang === 'python') return v + ' = (\n' + lines.map(function (l) { return '    "' + escC(l) + '\\n"'; }).join('\n') + '\n)\nprint(' + v + ', end="")\n';
    if (lang === 'javascript') return 'const ' + lv + ' = [\n' + lines.map(function (l) { return '  "' + escC(l).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029') + '"'; }).join(',\n') + '\n].join("\\n");\nconsole.log(' + lv + ');\n';
    if (lang === 'c' || lang === 'cpp') {
      var body = lines.map(function (l) { return '    "' + escC(l, '"', 'octal') + '\\n"'; }).join('\n');
      if (lang === 'c') return '#include <stdio.h>\n\nstatic const char *' + lv + ' =\n' + body + ';\n\nint main(void) {\n    fputs(' + lv + ', stdout);\n    return 0;\n}\n';
      return '#include <iostream>\n\nstatic const char *' + lv + ' =\n' + body + ';\n\nint main() {\n    std::cout << ' + lv + ';\n    return 0;\n}\n';
    }
    if (lang === 'powershell') {
      if (ansi || lines.some(function (l) { return /^\s*'@/.test(l); })) {
        var ps = function (s) { return s.replace(/`/g, '``').replace(/"/g, '`"').replace(/\$/g, '`$').replace(/\x1b/g, '`e'); };
        return '$' + v + ' = @(\n' + lines.map(function (l) { return '    "' + ps(l) + '"'; }).join(',\n') + '\n) -join [Environment]::NewLine\nWrite-Output $' + v + '\n';
      }
      return '$' + v + " = @'\n" + lines.join('\n') + "\n'@\nWrite-Output $" + v + '\n';
    }
    if (lang === 'bash') {
      if (ansi) { var sh = function (s) { return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\x1b/g, '\\e'); }; return "#!/usr/bin/env bash\nprintf '%s\\n' \\\n" + lines.map(function (l) { return "  $'" + sh(l) + "'"; }).join(' \\\n') + '\n'; }
      var delim = 'LEERBOX_ART';
      while (lines.some(function (l) { return l.trim() === delim; })) delim += '_';
      return "#!/usr/bin/env bash\ncat <<'" + delim + "'\n" + lines.join('\n') + '\n' + delim + '\n';
    }
    throw new Error('unknown language ' + lang);
  }
  var FORMATS = { txt: ['Plain text', '.txt', 'text/plain'], ansi: ['ANSI art', '.ans', 'text/plain'], html: ['HTML page', '.html', 'text/html'],
    svg: ['SVG vector', '.svg', 'image/svg+xml'], png: ['PNG image', '.png', 'image/png'], jpeg: ['JPEG image', '.jpg', 'image/jpeg'],
    webp: ['WebP image', '.webp', 'image/webp'], bmp: ['BMP image', '.bmp', 'image/bmp'], md: ['Markdown', '.md', 'text/markdown'],
    py: ['Python literal', '.py', 'text/x-python'], js: ['JavaScript literal', '.js', 'text/javascript'], c: ['C literal', '.c', 'text/x-c'],
    cpp: ['C++ literal', '.cpp', 'text/x-c'], ps1: ['PowerShell string', '.ps1', 'text/plain'], sh: ['Bash string', '.sh', 'text/x-sh'],
    json: ['LeerBox project', '.leerbox.json', 'application/json'] };

  // ---- raster (browser canvas)
  var BLOCKS = { '\u2588': [[0, 0, 1, 1]], '\u2580': [[0, 0, 1, .5]], '\u2584': [[0, .5, 1, 1]], '\u258c': [[0, 0, .5, 1]], '\u2590': [[.5, 0, 1, 1]],
    '\u2596': [[0, .5, .5, 1]], '\u2597': [[.5, .5, 1, 1]], '\u2598': [[0, 0, .5, .5]], '\u259d': [[.5, 0, 1, .5]],
    '\u2599': [[0, 0, .5, 1], [.5, .5, 1, 1]], '\u259a': [[0, 0, .5, .5], [.5, .5, 1, 1]], '\u259b': [[0, 0, 1, .5], [0, .5, .5, 1]],
    '\u259c': [[0, 0, 1, .5], [.5, .5, 1, 1]], '\u259e': [[.5, 0, 1, .5], [0, .5, .5, 1]], '\u259f': [[.5, 0, 1, 1], [0, .5, .5, 1]],
    '\u2581': [[0, .875, 1, 1]], '\u2582': [[0, .75, 1, 1]], '\u2583': [[0, .625, 1, 1]], '\u2585': [[0, .375, 1, 1]], '\u2586': [[0, .25, 1, 1]],
    '\u2587': [[0, .125, 1, 1]], '\u2589': [[0, 0, .875, 1]], '\u258a': [[0, 0, .75, 1]], '\u258b': [[0, 0, .625, 1]], '\u258d': [[0, 0, .375, 1]],
    '\u258e': [[0, 0, .25, 1]], '\u258f': [[0, 0, .125, 1]], '\u2594': [[0, 0, 1, .125]], '\u2595': [[.875, 0, 1, 1]] };
  (function () {
    for (var bits = 1; bits < 63; bits++) {
      if (bits === 21 || bits === 42) continue;
      var n = bits - 1 - (bits > 21 ? 1 : 0) - (bits > 42 ? 1 : 0), rects = [];
      for (var b = 0; b < 6; b++) if (bits >> b & 1) rects.push([(b % 2) / 2, Math.floor(b / 2) / 3, (b % 2 + 1) / 2, (Math.floor(b / 2) + 1) / 3]);
      BLOCKS[String.fromCodePoint(0x1FB00 + n)] = rects;
    }
  })();
  var SHADES = { '\u2591': 0.25, '\u2592': 0.5, '\u2593': 0.75 };
  function cssColor(c, a) { var p = C().splitRgb(c); return a === undefined ? 'rgb(' + p.join(',') + ')' : 'rgba(' + p.join(',') + ',' + a + ')'; }
  function renderCanvas(art, s, canvas) {
    s = settings(s);
    var fs = s.font_size * s.scale, cw = fs * 0.6021 * (1 + s.letter_spacing), ch = fs * s.line_height, pad = s.padding * s.scale;
    var W = Math.ceil(art.width * cw + 2 * pad), H = Math.ceil(art.height * ch + 2 * pad);
    if (W * H > 120000000 || W > 30000 || H > 30000) throw new Error('image would be ' + W + '\u00d7' + H + 'px; reduce scale, font size or text');
    canvas = canvas || document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    if (!s.transparent) { ctx.fillStyle = s.background; ctx.fillRect(0, 0, W, H); }
    var glow = art.meta.glow, dfg = s.foreground, y, x;
    for (y = 0; y < art.height; y++) for (x = 0; x < art.width; x++) if (art.bg[y][x] !== null) {
      ctx.fillStyle = cssColor(art.bg[y][x]); ctx.fillRect(Math.floor(pad + x * cw), Math.floor(pad + y * ch), Math.ceil(cw) + 1, Math.ceil(ch) + 1);
    }
    var layer = document.createElement('canvas'); layer.width = W; layer.height = H;
    var lc = layer.getContext('2d');
    lc.font = Math.round(fs) + "px 'LeerBox Mono','DejaVu Sans Mono',Consolas,monospace";
    lc.textBaseline = 'alphabetic';
    var base = (ch - fs) / 2 + fs * 0.8;
    for (y = 0; y < art.height; y++) for (x = 0; x < art.width; x++) {
      var c = art.chars[y][x];
      if (c === ' ' || c === '' || c === '\u2800') continue;
      var x0 = pad + x * cw, y0 = pad + y * ch, colr = art.fg[y][x] !== null ? cssColor(art.fg[y][x]) : dfg;
      lc.fillStyle = colr;
      if (BLOCKS[c]) BLOCKS[c].forEach(function (r) { lc.fillRect(Math.floor(x0 + r[0] * cw), Math.floor(y0 + r[1] * ch), Math.ceil((r[2] - r[0]) * cw) + 0.5, Math.ceil((r[3] - r[1]) * ch) + 0.5); });
      else if (SHADES[c] !== undefined) { lc.globalAlpha = SHADES[c]; lc.fillRect(Math.floor(x0), Math.floor(y0), Math.ceil(cw), Math.ceil(ch)); lc.globalAlpha = 1; }
      else if (c.codePointAt(0) > 0x2800 && c.codePointAt(0) <= 0x28FF) {
        var v = c.codePointAt(0) - 0x2800, rr = Math.max(1, Math.min(cw / 4, ch / 8) * 0.8);
        [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [0, 3], [1, 3]].forEach(function (d, bit) {
          if (v >> bit & 1) { lc.beginPath(); lc.arc(x0 + cw * (0.3 + 0.4 * d[0]), y0 + ch * (0.14 + 0.24 * d[1]), rr, 0, 2 * Math.PI); lc.fill(); }
        });
      } else lc.fillText(c, x0, y0 + base);
    }
    if (glow) {
      ctx.save(); ctx.filter = 'blur(' + Math.max(1, glow.radius * s.scale / 2) + 'px)';
      ctx.globalAlpha = Math.min(1, 0.5 + glow.strength);
      var tint = document.createElement('canvas'); tint.width = W; tint.height = H;
      var tc = tint.getContext('2d'); tc.drawImage(layer, 0, 0); tc.globalCompositeOperation = 'source-in'; tc.fillStyle = glow.color; tc.fillRect(0, 0, W, H);
      ctx.drawImage(tint, 0, 0); ctx.drawImage(tint, 0, 0); ctx.restore();
    }
    ctx.drawImage(layer, 0, 0);
    return canvas;
  }
  function encodeBmp(canvas, bg) {
    var w = canvas.width, h = canvas.height, d = canvas.getContext('2d').getImageData(0, 0, w, h).data;
    var rowSize = (w * 3 + 3) & ~3, size = 54 + rowSize * h, buf = new Uint8Array(size), v = new DataView(buf.buffer);
    var b = C().splitRgb(C().hexToRgb(bg));
    buf[0] = 66; buf[1] = 77; v.setUint32(2, size, true); v.setUint32(10, 54, true); v.setUint32(14, 40, true);
    v.setInt32(18, w, true); v.setInt32(22, h, true); v.setUint16(26, 1, true); v.setUint16(28, 24, true); v.setUint32(34, rowSize * h, true);
    v.setInt32(38, 2835, true); v.setInt32(42, 2835, true);
    for (var y = 0; y < h; y++) {
      var o = 54 + (h - 1 - y) * rowSize;
      for (var x = 0; x < w; x++) {
        var i = (y * w + x) * 4, a = d[i + 3] / 255;
        buf[o + x * 3] = Math.round(d[i + 2] * a + b[2] * (1 - a));
        buf[o + x * 3 + 1] = Math.round(d[i + 1] * a + b[1] * (1 - a));
        buf[o + x * 3 + 2] = Math.round(d[i] * a + b[0] * (1 - a));
      }
    }
    return new Blob([buf], { type: 'image/bmp' });
  }
  function canvasBlob(canvas, type, q) {
    return new Promise(function (res, rej) {
      canvas.toBlob(function (b) {
        if (!b) return rej(new Error(type + ' encoding failed'));
        if (b.type !== type) return rej(new Error('this browser cannot encode ' + type + ' (it produced ' + b.type + ')'));
        res(b);
      }, type, q);
    });
  }
  async function exportBlob(art, fmt, s, project) {
    s = settings(s);
    var text;
    switch (fmt) {
      case 'txt': text = toTxt(art); break;
      case 'ansi': text = toAnsi(art, s.ansi_mode); break;
      case 'html': text = toHtml(art, s); break;
      case 'svg': text = toSvg(art, s); break;
      case 'md': text = toMarkdown(art, s.title !== 'LeerBox Text Art' ? s.title : ''); break;
      case 'py': text = toCode(art, 'python'); break;
      case 'js': text = toCode(art, 'javascript'); break;
      case 'c': text = toCode(art, 'c'); break;
      case 'cpp': text = toCode(art, 'cpp'); break;
      case 'ps1': text = '\ufeff' + toCode(art, 'powershell'); break;
      case 'sh': text = toCode(art, 'bash'); break;
      case 'json': text = JSON.stringify(project, null, 1); break;
    }
    if (text !== undefined) return new Blob([text], { type: FORMATS[fmt][2] + ';charset=utf-8' });
    if (fmt === 'bmp') { var s2 = Object.assign({}, s, { transparent: false }); return encodeBmp(renderCanvas(art, s2), s.background); }
    if (fmt === 'jpeg') return canvasBlob(renderCanvas(art, Object.assign({}, s, { transparent: false })), 'image/jpeg', s.jpeg_quality / 100);
    if (fmt === 'png') return canvasBlob(renderCanvas(art, s), 'image/png');
    if (fmt === 'webp') return canvasBlob(renderCanvas(art, s), 'image/webp', s.jpeg_quality / 100);
    throw new Error('unknown export format ' + fmt);
  }

  LB.imageart = { imageToArt: imageToArt, RAMPS: RAMPS };
  LB.exporter = { settings: settings, toTxt: toTxt, toAnsi: toAnsi, toHtml: toHtml, toHtmlFragment: toHtmlFragment, toSvg: toSvg,
    toMarkdown: toMarkdown, toCode: toCode, CODE_LANGS: CODE_LANGS, FORMATS: FORMATS, renderCanvas: renderCanvas, exportBlob: exportBlob,
    rgbTo256: rgbTo256, rgbTo16: rgbTo16 };
})(LB);
