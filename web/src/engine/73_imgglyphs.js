/* LeerBox — palettes, measured glyph density and glyph shape matching (port of src/leerbox/imgglyphs.py). */
(function (LB) {
  'use strict';
  var MASK_W = 8, MASK_H = 16, CELL_QUANT = 64, atlas = null, runtime = {};
  function graphemes(s) { return LB.figlet.graphemes(String(s)).filter(function (g) { return g && g !== '\n' && g !== '\r' && g !== '\t'; }); }
  function glyphAtlas() {
    if (!atlas) {
      var d = LB.resources.glyphMasks, raw = LB.b64ToBytes(d.masks), n = d.w * d.h, chars = Array.from(d.chars);
      atlas = new Map();
      chars.forEach(function (ch, i) { atlas.set(ch, raw.subarray(i * n, (i + 1) * n)); });
    }
    return atlas;
  }
  function runtimeMask(ch) {
    if (ch in runtime) return runtime[ch];
    var m = null;
    try {
      var cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(32, 64) : (typeof document !== 'undefined' ? document.createElement('canvas') : null);
      if (cv) {
        cv.width = 32; cv.height = 64;
        var cx = cv.getContext('2d');
        cx.fillStyle = '#000'; cx.fillRect(0, 0, 32, 64); cx.fillStyle = '#fff';
        cx.font = "53px 'LeerBox Mono','DejaVu Sans Mono',monospace"; cx.textBaseline = 'alphabetic';
        cx.fillText(ch, 0, 50);
        var d = cx.getImageData(0, 0, 32, 64).data, out = new Uint8Array(128), any = false;
        for (var y = 0; y < 16; y++) for (var x = 0; x < 8; x++) {
          var s = 0; for (var sy = 0; sy < 4; sy++) for (var sx = 0; sx < 4; sx++) s += d[((y * 4 + sy) * 32 + x * 4 + sx) * 4];
          out[y * 8 + x] = Math.floor(s / 16 + 0.5); if (out[y * 8 + x]) any = true;
        }
        m = any || !ch.trim() ? out : null;
      }
    } catch (e) { m = null; }
    runtime[ch] = m;
    return m;
  }
  function glyphMask(ch) {
    if (ch === ' ' || ch === '') return new Uint8Array(128);
    return glyphAtlas().get(ch) || runtimeMask(ch);
  }
  function coverageSum(ch) {
    var m = glyphMask(ch);
    if (!m) return Math.floor(0.2 * 255 * 128);
    var s = 0; for (var i = 0; i < m.length; i++) s += m[i];
    return s;
  }
  function cpKey(c) { return Array.from(c).map(function (x) { return x.codePointAt(0); }); }
  function cmpCp(a, b) { var x = cpKey(a), y = cpKey(b); for (var i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i]; return x.length - y.length; }
  function sortByDensity(chars, reverse) {
    var uniq = Array.from(new Set(chars)), d = new Map();
    uniq.forEach(function (c) { d.set(c, coverageSum(c)); });
    uniq.sort(function (a, b) { return d.get(a) - d.get(b) || cmpCp(a, b); });
    return reverse ? uniq.reverse() : uniq;
  }
  var range = function (a, b) { var s = ''; for (var c = a; c < b; c++) s += String.fromCodePoint(c); return s; };
  var PALETTES = {
    ascii_basic: { label: 'Basic ASCII', chars: ' .:-=+*#%@', kind: 'ramp' },
    ascii_basic_rev: { label: 'Basic ASCII (reversed)', chars: '@%#*+=-:. ', kind: 'ramp', keep_order: true },
    ascii_extended: { label: 'Extended ASCII', kind: 'set', chars: " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$" },
    ascii_high: { label: 'High-density ASCII', kind: 'set', chars: " .`'-,:;!|/\\()[]{}<>?+=*%#&$@0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" },
    ascii_low: { label: 'Low-density ASCII', chars: " .,'`:-;~\"^", kind: 'ramp' },
    cp437: { label: 'Extended (CP437/Latin-1)', kind: 'set', chars: ' .·∙:-=+±÷≈≡░▒▓█▀▄▌▐■│─┼┤├┬┴┌┐└┘║═╬╔╗╚╝⌐¬ºª°¹²³«»¶§¤¦ßæÆøØ¥£¢©®αΓπΣσµτΦΘΩδ∞φε∩√ⁿ' },
    blocks: { label: 'Unicode shade blocks', chars: ' ░▒▓█', kind: 'ramp', keep_order: true },
    braille: { label: 'Braille patterns', chars: range(0x2800, 0x2900), kind: 'set' },
    geometric: { label: 'Geometric symbols', chars: ' ·∙•◦○◘◙●◌◊◇◆□■▪▫▲△▼▽◀▶◢◣◤◥', kind: 'set' },
    math: { label: 'Mathematical symbols', kind: 'set', chars: ' ·∘∙−+×÷=≠≈∼≤≥±∓∑∏∫∂∇√∞∝∈∉∋⊂⊃⊆⊇∩∪∧∨¬∀∃∅⊕⊗⊥∠∴∵≡≅' },
    binary: { label: 'Binary digits', chars: ' 01', kind: 'ramp' },
    alpha: { label: 'Alphabetic', chars: ' ABCDEFGHIJKLMNOPQRSTUVWXYZ', kind: 'ramp' },
    numeric: { label: 'Numeric', chars: ' 0123456789', kind: 'ramp' },
    dots: { label: 'Dots (halftone)', chars: ' ·∙•●', kind: 'ramp', keep_order: true },
    lines: { label: 'Line glyphs', chars: " -_|/\\()<>^v.,'`=+", kind: 'set' },
    symbols: { label: 'Custom Unicode symbols', chars: ' ·✦✧★☆♠♣♥♦♪♫☼', kind: 'ramp' },
    katakana: { label: 'Half-width katakana', kind: 'set', chars: range(0xFF66, 0xFF9E) },
    emoji: { label: 'Emoji (colour squares & hearts)', chars: '⬛🟫🟥🟧🟨🟩🟦🟪⬜', kind: 'emoji', keep_order: true }
  };
  var EMOJI_COLORS = [
    ['⬛', 0x1E1E1E], ['⬜', 0xF0F0F0], ['🟥', 0xDD2E44], ['🟧', 0xF4900C], ['🟨', 0xFDCB58], ['🟩', 0x78B159],
    ['🟦', 0x55ACEE], ['🟪', 0xAA8ED6], ['🟫', 0xC1694F], ['❤️', 0xDD2E44], ['🧡', 0xF4900C], ['💛', 0xFDCB58],
    ['💚', 0x78B159], ['💙', 0x5DADEC], ['💜', 0xAA8ED6], ['🤎', 0xA0522D], ['🖤', 0x31373D], ['🤍', 0xFFFFFF],
    ['🌑', 0x3D3D3D], ['🌕', 0xFFD983], ['🔴', 0xDD2E44], ['🟠', 0xF4900C], ['🟡', 0xFDCB58], ['🟢', 0x78B159],
    ['🔵', 0x55ACEE], ['🟣', 0xAA8ED6], ['🟤', 0xC1694F], ['⚫', 0x31373D], ['⚪', 0xE6E7E8]];
  var MAX_PALETTE_GLYPHS = 512;
  function cleanPalette(s) {
    s = Array.from(String(s)).filter(function (c) { var o = c.codePointAt(0); return o >= 32 && !(o >= 0x7F && o < 0xA0); }).join('');
    return graphemes(s).slice(0, MAX_PALETTE_GLYPHS).join('');
  }
  function resolvePalette(spec, def, reverse, sort) {
    def = def || 'ascii_basic'; spec = spec || def; if (sort === undefined) sort = true;
    var ordered, chars;
    if (PALETTES[spec]) {
      var p = PALETTES[spec]; chars = graphemes(p.chars);
      if (p.kind === 'emoji') return reverse ? chars.reverse() : chars;
      ordered = (p.keep_order || !sort) ? chars : sortByDensity(chars);
    } else {
      chars = graphemes(cleanPalette(spec));
      if (!chars.length) chars = graphemes(PALETTES[def].chars);
      ordered = sort ? sortByDensity(chars) : Array.from(new Set(chars));
    }
    if (ordered.length === 1) ordered = [' '].concat(ordered);
    return reverse ? ordered.slice().reverse() : ordered;
  }
  function paletteFromFiglet(font) {
    var seen = new Set([' ']), hb = font.hardblank || '$';
    var src = font.glyphs || font.chars || {}, chars = src instanceof Map ? Array.from(src.values()) : Object.keys(src).map(function (k) { return src[k]; });
    chars.forEach(function (rows) { rows.forEach(function (row) { Array.from(row).forEach(function (c) { if (c !== hb && c.codePointAt(0) >= 32) seen.add(c); }); }); });
    return sortByDensity(Array.from(seen)).join('');
  }
  function exportPalettes(items) {
    return JSON.stringify({ leerbox_palettes: 1, palettes: items.map(function (i) { return { name: String(i.name).slice(0, 80), chars: cleanPalette(i.chars) }; }) }, null, 1);
  }
  function importPalettes(text) {
    var d; try { d = JSON.parse(text); } catch (e) { throw new Error('not a palette file: ' + e.message); }
    if (!d || typeof d !== 'object' || !Array.isArray(d.palettes)) throw new Error('not a LeerBox palette file');
    var out = [];
    d.palettes.slice(0, 200).forEach(function (p) {
      if (p && typeof p === 'object' && typeof p.chars === 'string') {
        var c = cleanPalette(p.chars);
        if (c) out.push({ name: String(p.name || 'Imported').replace(/[\x00-\x1f]/g, '').slice(0, 80) || 'Imported', chars: c });
      }
    });
    return out;
  }

  // ---------------------------------------------------------------- shape matching (exact integer features)
  function GlyphMatcher(chars, fw, fh, k) {
    var bx = MASK_W / fw, by = MASK_H / fh, F = fw * fh, self = this;
    this.fw = fw; this.fh = fh; this.block = bx * by; this.F = F;
    var feats = chars.map(function (ch) {
      var m = glyphMask(ch), f = new Float64Array(F);
      for (var y = 0; y < MASK_H; y++) for (var x = 0; x < MASK_W; x++) f[((y / by) | 0) * fw + ((x / bx) | 0)] += m ? m[y * MASK_W + x] : 51;
      for (var i = 0; i < F; i++) f[i] *= CELL_QUANT;
      return f;
    });
    var dens = feats.map(function (f) { var s = 0; for (var i = 0; i < F; i++) s += f[i]; return s; });
    var order = chars.map(function (_, i) { return i; }).sort(function (a, b) { return dens[a] - dens[b] || cmpCp(chars[a], chars[b]); });
    this.chars = order.map(function (i) { return chars[i]; });
    this.G = order.map(function (i) { return feats[i]; });
    this.dens = order.map(function (i) { return dens[i]; });
    var mx = 0; this.dens.forEach(function (d) { if (d > mx) mx = d; });
    this.maxMean = chars.length ? mx / (F * 255 * this.block * CELL_QUANT) : 1;
    this.k = Math.max(1, Math.min(k || 24, chars.length));
    this.cache = new Map();
    void self;
  }
  /* ink: Float64Array of n*F values (cells in reading order). Returns Int32Array of indices into this.chars. */
  GlyphMatcher.prototype.match = function (ink, n) {
    var F = this.F, K = this.k, N = this.chars.length, out = new Int32Array(n), scale = 255 * this.block, q = new Float64Array(F);
    for (var c = 0; c < n; c++) {
      var m = 0, key = '';
      for (var i = 0; i < F; i++) {
        var v = ink[c * F + i]; v = v < 0 ? 0 : v > 1 ? 1 : v;
        q[i] = Math.floor(v * this.maxMean * CELL_QUANT + 0.5) * scale; m += q[i]; key += q[i] / scale + ',';
      }
      var hit = this.cache.get(key);
      if (hit !== undefined) { out[c] = hit; continue; }
      var lo = 0, hi = N;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (this.dens[mid] < m) lo = mid + 1; else hi = mid; }
      var start = Math.min(Math.max(lo - (K >> 1), 0), N - K), best = Infinity, bi = start;
      for (var g = start; g < start + K; g++) {
        var G = this.G[g], d = 0;
        for (i = 0; i < F; i++) { var e = q[i] - G[i]; d += e * e; }
        if (d < best) { best = d; bi = g; }
      }
      if (this.cache.size < 200000) this.cache.set(key, bi);
      out[c] = bi;
    }
    return out;
  };
  function masksFloat(chars, fw, fh) {
    var bx = MASK_W / fw, by = MASK_H / fh, F = fw * fh;
    return chars.map(function (ch) {
      var m = glyphMask(ch), f = new Float64Array(F);
      for (var y = 0; y < MASK_H; y++) for (var x = 0; x < MASK_W; x++) f[((y / by) | 0) * fw + ((x / bx) | 0)] += m ? m[y * MASK_W + x] / 255 : 0.2;
      for (var i = 0; i < F; i++) f[i] /= bx * by;
      return f;
    });
  }
  function sextantChar(bits) {
    if (bits === 0) return ' ';
    if (bits === 63) return '█';
    if (bits === 21) return '▌';
    if (bits === 42) return '▐';
    var n = bits - 1; if (bits > 21) n--; if (bits > 42) n--;
    return String.fromCodePoint(0x1FB00 + n);
  }
  var QUADRANT_CHARS = Array.from(' ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█');
  var BRAILLE_DOTS = [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [0, 3], [1, 3]];
  LB.imgglyphs = { glyphAtlas: glyphAtlas, glyphMask: glyphMask, coverageSum: coverageSum, sortByDensity: sortByDensity, PALETTES: PALETTES,
    EMOJI_COLORS: EMOJI_COLORS, cleanPalette: cleanPalette, resolvePalette: resolvePalette, paletteFromFiglet: paletteFromFiglet,
    exportPalettes: exportPalettes, importPalettes: importPalettes, GlyphMatcher: GlyphMatcher, masksFloat: masksFloat,
    sextantChar: sextantChar, QUADRANT_CHARS: QUADRANT_CHARS, BRAILLE_DOTS: BRAILLE_DOTS, graphemes: graphemes, cmpCp: cmpCp };
})(LB);
