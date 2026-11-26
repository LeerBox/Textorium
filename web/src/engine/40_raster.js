/* LeerBox — bitmap (raster typography) fonts and renderer (port of raster.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };
  var MARK_STYLES = { block: '█', ascii: '#', money: '$', shade: '▓', dots: '•', binary: '1', at: '@', star: '*' };
  var QUAD = cps(' ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█');

  // Decode a hex row (bit i = column i, LSB = leftmost) into an array of set column indices.
  function hexBits(h) {
    var cols = [];
    if (!h) return cols;
    for (var i = 0; i < h.length; i++) {
      var v = parseInt(h[h.length - 1 - i], 16);
      for (var b = 0; b < 4; b++) if (v & (1 << b)) cols.push(i * 4 + b);
    }
    return cols;
  }
  function decodeGlyph(data, h) {
    var rows = [], width = 0;
    for (var i = 2; i < data.length; i++) {
      var bits = hexBits(data[i]); rows.push(bits);
      if (bits.length && bits[bits.length - 1] + 1 > width) width = bits[bits.length - 1] + 1;
    }
    while (rows.length < h) rows.push([]);
    return { adv: data[0] | 0, xoff: data[1] | 0, width: width, rows: rows };
  }
  function parseRaster(obj, name) {
    var h = obj.h | 0;
    if (!(h >= 1 && h <= 400)) throw new Error('invalid raster font height');
    var glyphs = new Map(), marks = new Map();
    Object.keys(obj.g).forEach(function (ch) { glyphs.set(ch, decodeGlyph(obj.g[ch], h)); });
    Object.keys(obj.m || {}).forEach(function (ch) { marks.set(ch, decodeGlyph(obj.m[ch], h)); });
    return { raster: true, name: name, height: h, baseline: obj.base !== undefined ? obj.base : h, script: obj.script || 'latin',
      glyphs: glyphs, marks: marks };
  }
  function findGlyph(font, ch) {
    if (font.glyphs.has(ch)) return font.glyphs.get(ch);
    var base = cps(ch.normalize('NFKD')).filter(function (c) { return !LB.figlet.isMark(c); }).join('');
    var alts = [base, ch.toUpperCase(), ch.toLowerCase(), base ? base.toUpperCase() : '', base ? base.toLowerCase() : ''];
    for (var i = 0; i < alts.length; i++) if (alts[i] && font.glyphs.has(alts[i])) return font.glyphs.get(alts[i]);
    return font.glyphs.get('?') || null;
  }
  var JOINS_LEFT = null;
  function joinsLeft() {
    if (!JOINS_LEFT) {
      JOINS_LEFT = new Set(['ـ']);
      var f = LB.resources.arabicTables.forms;
      Object.keys(f).forEach(function (k) { if (f[k][2]) JOINS_LEFT.add(f[k][2]); if (f[k][3]) JOINS_LEFT.add(f[k][3]); });
    }
    return JOINS_LEFT;
  }
  function defaults(o) {
    return Object.assign({ mode: 'block', char: '@', scale: 1, aspect: 1, letterSpacing: 0, lineSpacing: 2, align: 'auto',
      direction: 'auto', arabicShaping: true, ligatures: true, diacritics: true, digits: 'keep', invert: false, maxInput: 2000 }, o || {});
  }
  function renderLineBitmap(font, line, o) {
    var A = LB.arabic;
    var isAr = A.containsArabic(line);
    if (o.digits !== 'keep') line = A.convertDigits(line, o.digits);
    if (!o.diacritics) line = A.stripDiacritics(line);
    if (isAr && o.arabicShaping) line = A.shape(line, o.ligatures);
    var clusters = A.visualClusters(line, o.direction);
    var rtl = A.paragraphLevel(line, o.direction) === 1;
    var JL = joinsLeft();
    var placed = [], marks = [], pen = 0, i;
    for (i = 0; i < clusters.length; i++) {
      var cl = cps(clusters[i]), base = cl[0];
      if (base === '‌' || base === '‍' || base === '‎' || base === '‏') continue;
      var g = base !== ' ' ? findGlyph(font, base) : (font.glyphs.get(' ') || null);
      if (base === ' ' && !g) { pen += Math.max(2, Math.floor(font.height / 4)); continue; }
      if (!g) continue;
      placed.push([pen, g]);
      for (var m = 1; m < cl.length; m++) if (font.marks.has(cl[m])) marks.push([cl[m], placed.length - 1, font.marks.get(cl[m])]);
      pen += g.adv;
      var nxt = i + 1 < clusters.length ? cps(clusters[i + 1])[0] : '';
      if (o.letterSpacing && !JL.has(nxt)) pen += o.letterSpacing;
    }
    var minx = 0;
    placed.forEach(function (p) { if (p[0] + p[1].xoff < minx) minx = p[0] + p[1].xoff; });
    var shift = -minx, width = 0;
    if (placed.length) {
      width = pen + shift;
      placed.forEach(function (p) { var e = p[0] + p[1].xoff + p[1].width + shift; if (e > width) width = e; });
    }
    var h = font.height, rows = [], y;
    for (y = 0; y < h; y++) rows.push(new Uint8Array(width));
    placed.forEach(function (p) {
      var ox = p[0] + p[1].xoff + shift;
      for (var yy = 0; yy < h; yy++) { var r = p[1].rows[yy]; for (var k = 0; k < r.length; k++) rows[yy][ox + r[k]] = 1; }
    });
    marks.forEach(function (mk) {
      var bx = placed[mk[1]][0], bg = placed[mk[1]][1], mg = mk[2];
      var bcenter = bx + bg.xoff + shift + bg.width / 2;
      var mx = Math.floor(bcenter - mg.width / 2 + 0.5);
      var ys = []; for (var yy = 0; yy < h; yy++) if (mg.rows[yy].length) ys.push(yy);
      if (!ys.length) return;
      var above = (ys[0] + ys[ys.length - 1]) / 2 < font.baseline - font.height * 0.15;
      function collides(dy) {
        for (var a = 0; a < ys.length; a++) {
          var yy = ys[a], ty = yy + dy;
          if (ty < 0 || ty >= h) return true;
          var r = mg.rows[yy];
          for (var b = 0; b < r.length; b++) {
            var tx = mx + r[b];
            if (tx >= 0 && tx < width && rows[ty][tx]) return true;
            if (tx >= 0 && tx < width && (above ? (ty + 1 < h && rows[ty + 1][tx]) : (ty - 1 >= 0 && rows[ty - 1][tx]))) return true;
          }
        }
        return false;
      }
      var dy = 0, step = above ? -1 : 1;
      for (var n = 0; n < 16; n++) { if (!collides(dy)) break; dy += step; }
      ys.forEach(function (yy) {
        var ty = yy + dy;
        if (ty >= 0 && ty < h) mg.rows[yy].forEach(function (b) { if (mx + b >= 0 && mx + b < width) rows[ty][mx + b] = 1; });
      });
    });
    return { rows: rows, width: width, rtl: rtl };
  }
  function anyBit(r) { for (var i = 0; i < r.length; i++) if (r[i]) return true; return false; }
  function renderRasterBitmap(font, text, o) {
    o = defaults(o);
    text = cps(text).slice(0, o.maxInput).join('');
    var blocks = text.replace(/\r\n/g, '\n').split('\n').map(function (ln) { return renderLineBitmap(font, ln, o); });
    var width = 0; blocks.forEach(function (b) { if (b.width > width) width = b.width; });
    var out = [];
    blocks.forEach(function (b, i) {
      var align = o.align === 'auto' ? (b.rtl ? 'right' : 'left') : o.align;
      var pad = align === 'left' ? 0 : align === 'right' ? width - b.width : Math.floor((width - b.width) / 2);
      if (i && o.lineSpacing > 0) for (var k = 0; k < o.lineSpacing; k++) out.push(new Uint8Array(width));
      b.rows.forEach(function (r) { var nr = new Uint8Array(width); nr.set(r, pad); out.push(nr); });
    });
    while (out.length > 1 && !anyBit(out[0])) out.shift();
    while (out.length > 1 && !anyBit(out[out.length - 1])) out.pop();
    if (out.length) {
      var last = 0;
      out.forEach(function (r) { for (var x = r.length - 1; x >= 0; x--) if (r[x]) { if (x + 1 > last) last = x + 1; break; } });
      out = out.map(function (r) { return r.slice(0, last); });
    }
    var s = Math.max(1, Math.min(8, o.scale | 0)), a = Math.max(1, Math.min(4, o.aspect | 0));
    var total = 0; out.forEach(function (r) { total += r.length; });
    if (s * s * a * total > 4000000) throw new Error('raster output too large; reduce text or scale');
    if (s > 1 || a > 1) {
      var scaled = [];
      out.forEach(function (r) {
        var nr = new Uint8Array(r.length * s * a);
        for (var x = 0; x < r.length; x++) for (var k = 0; k < s * a; k++) nr[x * s * a + k] = r[x];
        for (var k2 = 0; k2 < s; k2++) scaled.push(nr.slice());
      });
      out = scaled;
    }
    if (o.invert) out = out.map(function (r) { return r.map(function (b) { return 1 - b; }); });
    return out;
  }
  function bitmapToArt(bits, mode, ch) {
    var h = bits.length, w = 0;
    bits.forEach(function (r) { if (r.length > w) w = r.length; });
    function px(x, y) { return (y >= 0 && y < h && x >= 0 && x < bits[y].length && bits[y][x]) ? 1 : 0; }
    var rows = [], x, y;
    if (mode === 'half') {
      for (y = 0; y < h; y += 2) { var r = []; for (x = 0; x < w; x++) r.push(' ▀▄█'[px(x, y) | (px(x, y + 1) << 1)]); rows.push(r); }
    } else if (mode === 'quarter') {
      for (y = 0; y < h; y += 2) { var rq = []; for (x = 0; x < w; x += 2) rq.push(QUAD[px(x, y) | (px(x + 1, y) << 1) | (px(x, y + 1) << 2) | (px(x + 1, y + 1) << 3)]); rows.push(rq); }
    } else if (mode === 'braille') {
      for (y = 0; y < h; y += 4) {
        var rb = [];
        for (x = 0; x < w; x += 2) {
          var v = px(x, y) | (px(x, y + 1) << 1) | (px(x, y + 2) << 2) | (px(x + 1, y) << 3) | (px(x + 1, y + 1) << 4) |
            (px(x + 1, y + 2) << 5) | (px(x, y + 3) << 6) | (px(x + 1, y + 3) << 7);
          rb.push(v ? String.fromCharCode(0x2800 + v) : ' ');
        }
        rows.push(rb);
      }
    } else {
      var mark = MARK_STYLES[mode] || '█';
      if (mode === 'custom' && ch) { var g = LB.figlet.graphemes(ch); mark = g.length ? g[0] : '@'; }
      for (y = 0; y < h; y++) { var rr = []; for (x = 0; x < w; x++) rr.push(px(x, y) ? mark : ' '); rows.push(rr); }
    }
    if (!rows.length) rows = [[]];
    var art = new LB.Art(rows);
    art.trimRight();
    return art;
  }
  function renderRaster(font, text, o) {
    o = defaults(o);
    return bitmapToArt(renderRasterBitmap(font, text, o), o.mode, o.char);
  }
  LB.raster = { parseRaster: parseRaster, renderRaster: renderRaster, renderRasterBitmap: renderRasterBitmap, bitmapToArt: bitmapToArt,
    findGlyph: findGlyph, MARK_STYLES: MARK_STYLES };
})(LB);
