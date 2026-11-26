/* LeerBox — cell grid (Art) and effects pipeline (ports of art.py and effects.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };

  function hexToRgb(s) {
    s = String(s).trim().replace(/^#/, '');
    if (s.length === 3) s = s.split('').map(function (c) { return c + c; }).join('');
    if (!/^[0-9a-fA-F]{6}$/.test(s)) throw new Error('invalid colour ' + s);
    return parseInt(s, 16);
  }
  function rgbToHex(c) { return '#' + ('000000' + c.toString(16)).slice(-6); }
  function splitRgb(c) { return [(c >> 16) & 255, (c >> 8) & 255, c & 255]; }
  function clamp255(v) { v = v >= 0 ? Math.floor(v + 0.5) : 0; return v > 255 ? 255 : v; }
  function joinRgb(r, g, b) { return (clamp255(r) << 16) | (clamp255(g) << 8) | clamp255(b); }

  function Art(chars, fg, bg, meta) {
    this.chars = chars || [[]]; this.fg = fg || []; this.bg = bg || []; this.meta = meta || {};
    this.normalize();
  }
  Art.fromText = function (text) {
    text = cps(text).map(function (c) {
      var o = c.codePointAt(0);
      if (c === '\n' || (o >= 32 && !(o >= 0x7F && o < 0xA0))) return c;
      return c === '\t' ? ' ' : '';
    }).join('');
    var rows = text.split('\n').map(function (line) {
      var cells = [];
      LB.figlet.graphemes(line).forEach(function (g) {
        var w = LB.figlet.charWidth(g);
        if (w === 0 && cells.length && g !== ' ') { cells[cells.length - 1] += g; return; }
        cells.push(g);
        if (w === 2) cells.push('');
      });
      return cells;
    });
    return new Art(rows);
  };
  Art.blank = function (w, h) {
    var rows = []; for (var y = 0; y < h; y++) { var r = []; for (var x = 0; x < w; x++) r.push(' '); rows.push(r); }
    return new Art(rows);
  };
  Art.prototype.normalize = function () {
    var w = 0, self = this;
    this.chars.forEach(function (r) { if (r.length > w) w = r.length; });
    this.chars.forEach(function (r) { while (r.length < w) r.push(' '); });
    var h = this.chars.length;
    ['fg', 'bg'].forEach(function (k) {
      var old = self[k];
      var ok = old.length === h && old.every(function (r) { return r.length === w; });
      if (!ok) {
        var nw = [];
        for (var y = 0; y < h; y++) { var r = []; for (var x = 0; x < w; x++) r.push(old[y] && old[y][x] !== undefined ? old[y][x] : null); nw.push(r); }
        self[k] = nw;
      }
    });
  };
  Object.defineProperty(Art.prototype, 'width', { get: function () { return this.chars.length ? this.chars[0].length : 0; } });
  Object.defineProperty(Art.prototype, 'height', { get: function () { return this.chars.length; } });
  Art.prototype.copy = function () {
    var cp2 = function (a) { return a.map(function (r) { return r.slice(); }); };
    return new Art(cp2(this.chars), cp2(this.fg), cp2(this.bg), Object.assign({}, this.meta));
  };
  Art.prototype.isInk = function (x, y) { var c = this.chars[y][x]; return c !== ' ' && c !== ''; };
  Art.prototype.toText = function (strip) {
    return this.chars.map(function (r) { var s = r.join(''); return strip === false ? s : s.replace(/\s+$/, ''); }).join('\n');
  };
  Art.prototype.hasColor = function () {
    return this.fg.some(function (r) { return r.some(function (c) { return c !== null; }); }) ||
      this.bg.some(function (r) { return r.some(function (c) { return c !== null; }); });
  };
  Art.prototype.trimRight = function () {
    var w = 0, self = this;
    this.chars.forEach(function (r, y) {
      for (var x = r.length - 1; x >= 0; x--) { if ((r[x] !== ' ' && r[x] !== '') || self.bg[y][x] !== null) { if (x + 1 > w) w = x + 1; break; } }
    });
    [this.chars, this.fg, this.bg].forEach(function (rows) { rows.forEach(function (r) { r.length = Math.min(r.length, w); }); });
  };

  // ------------------------------------------------------------------ RNG
  function Rng(seed) { this.a = seed >>> 0; }
  Rng.prototype.next = function () {
    this.a = (this.a + 0x6D2B79F5) >>> 0;
    var t = this.a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  Rng.prototype.int = function (n) { return Math.floor(this.next() * n); };

  function zipMap(a, b) { var m = {}; var A = cps(a), B = cps(b); for (var i = 0; i < A.length; i++) m[A[i]] = B[i]; return m; }
  var MIRROR_H = zipMap('/\\()[]{}<>⌐¬└┘┌┐├┤╔╗╚╝╠╣▌▐◀▶«»‹›╭╮╰╯◤◥◣◢▖▗▘▝',
    '\\/)(][}{><¬⌐┘└┐┌┤├╗╔╝╚╣╠▐▌▶◀»«›‹╮╭╯╰◥◤◢◣▗▖▝▘');
  var FLIP_V = zipMap("/\\^v'.,`_‾┌┐└┘╔╗╚╝┬┴╦╩▀▄╭╮╰╯◤◥◣◢▖▗▘▝MWmw",
    "\\/v^.''.‾_└┘┌┐╚╝╔╗┴┬╩╦▄▀╰╯╭╮◣◢◤◥▘▝▖▗WMwm");
  var ROT_90 = zipMap('|-/\\─│═║┌┐┘└╔╗╝╚┬┤┴├▀▐▄▌<>^v()⌒⌣',
    '-|\\/│─║═┐┘└┌╗╝╚╔┤┴├┬▐▄▌▀^v><⌒⌣)(');  // every mapping is a 2- or 4-cycle
  var INVERT_MAP = zipMap('█▓▒░▀▄▌▐', ' ░▒▓▄▀▐▌');
  var FRAMES = {
    single: '┌─┐│└┘│─', double: '╔═╗║╚╝║═',
    rounded: '╭─╮│╰╯│─', heavy: '┏━┓┃┗┛┃━',
    ascii: '+-+|++|-', dashed: '┌╌┐╎└┘╎╌', stars: '*********',
    block: '█▀█████▄', shade: '▓▓▓▓▓▓▓▓',
    dots: '·······  ', terminal: '┌─┐│└┘│─'
  };
  var EFFECT_INFO = {
    color: ['color', 'Solid colours'], gradient: ['color', 'Gradient'], rainbow: ['color', 'Rainbow'], shadow: ['text', 'Shadow'],
    double_shadow: ['text', 'Double shadow'], outline: ['text', 'Outline'], extrude: ['text', '3D extrusion'],
    mirror: ['text', 'Mirror (horizontal flip)'], flip_v: ['text', 'Vertical flip'], rotate: ['text', 'Rotate'],
    invert: ['text', 'Invert'], fill: ['text', 'Fill character'], background: ['text', 'Background character'],
    noise: ['text', 'Noise'], glitch: ['text', 'Glitch'], matrix: ['color', 'Matrix'], zalgo: ['text', 'Zalgo'],
    frame: ['text', 'Frame / box'], padding: ['text', 'Padding'], glow: ['graphic', 'Glow']
  };
  var DEFAULTS = {
    color: { fg: '#7aa2ff', bg: '' },
    gradient: { mode: 'horizontal', stops: ['#7aa2ff', '#b18cff'], target: 'fg' },
    rainbow: { mode: 'horizontal', saturation: 0.75, lightness: 0.62, offset: 0.0, cycles: 1.0 },
    shadow: { dx: 1, dy: 1, char: '░', color: '#3b4252' },
    double_shadow: { dx: 1, dy: 1, char1: '▒', char2: '░', color1: '#4c566a', color2: '#2e3440' },
    outline: { char: '·', diagonal: true, color: '' },
    extrude: { depth: 3, direction: 'se', char: '▒', color: '#4c566a' },
    mirror: {}, flip_v: {}, rotate: { angle: 90 },
    invert: { char: '█', margin: 1 }, fill: { char: '█' }, background: { char: '·', color: '' },
    noise: { amount: 0.05, chars: '░▒▓·:', seed: 7 },
    glitch: { amount: 0.25, shift: 3, seed: 13 }, matrix: { density: 0.5, seed: 21, color: '#33ff66' },
    zalgo: { intensity: 2, seed: 3 }, frame: { style: 'rounded', padding: 1, title: '', color: '' },
    padding: { top: 1, right: 2, bottom: 1, left: 2 }, glow: { color: '#7aa2ff', radius: 6, strength: 0.8 }
  };
  function newEffect(kind, params) {
    if (!DEFAULTS[kind]) throw new Error('unknown effect ' + kind);
    var e = { type: kind, enabled: true };
    var d = JSON.parse(JSON.stringify(DEFAULTS[kind]));
    Object.assign(e, d, params || {});
    return e;
  }
  function col(v) { if (v === null || v === undefined || v === '' || v === 'none') return null; if (typeof v === 'number') return v; return hexToRgb(String(v)); }
  function chr(v, d) { var s = (v === null || v === undefined || v === '') ? d : String(v); var g = LB.figlet.graphemes(s); return g.length ? g[0] : d; }
  function int(v, lo, hi, d) { var n = parseInt(v, 10); if (isNaN(n)) return d; return Math.max(lo, Math.min(hi, n)); }
  function flt(v, lo, hi, d) { var n = parseFloat(v); if (isNaN(n)) return d; return Math.max(lo, Math.min(hi, n)); }

  function grow(art, left, top, right, bottom) {
    var out = Art.blank(art.width + left + right, art.height + top + bottom);
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {
      out.chars[y + top][x + left] = art.chars[y][x]; out.fg[y + top][x + left] = art.fg[y][x]; out.bg[y + top][x + left] = art.bg[y][x];
    }
    out.meta = Object.assign({}, art.meta);
    return out;
  }
  function offsetLayer(art, dx, dy, ch, color) {
    var left = Math.max(0, -dx), top = Math.max(0, -dy);
    var out = grow(art, left, top, Math.max(0, dx), Math.max(0, dy));
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {
      if (!art.isInk(x, y)) continue;
      var ty = y + top + dy, tx = x + left + dx, oy = ty - top, ox = tx - left;
      if (oy >= 0 && oy < art.height && ox >= 0 && ox < art.width && art.isInk(ox, oy)) continue;
      if (out.chars[ty][tx] === ' ' || out.chars[ty][tx] === '') { out.chars[ty][tx] = ch; out.fg[ty][tx] = color; }
    }
    return out;
  }
  function gradientColor(stops, t) {
    if (!stops.length) return 0xFFFFFF;
    if (stops.length === 1) return stops[0];
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    var pos = t * (stops.length - 1), i = Math.floor(pos);
    if (i >= stops.length - 1) return stops[stops.length - 1];
    var f = pos - i, a = splitRgb(stops[i]), b = splitRgb(stops[i + 1]);
    return joinRgb(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f);
  }
  function tFor(mode, x, y, w, h) {
    var mw = Math.max(1, w - 1), mh = Math.max(1, h - 1);
    if (mode === 'vertical') return y / mh;
    if (mode === 'diagonal') return (x / mw + y / mh) / 2;
    if (mode === 'diagonal_up') return (x / mw + (h - 1 - y) / mh) / 2;
    if (mode === 'radial') {
      var cx = (w - 1) / 2, cy = (h - 1) / 2;
      var d = Math.sqrt(Math.pow((x - cx) / Math.max(1, cx), 2) + Math.pow((y - cy) / Math.max(1, cy), 2));
      return Math.min(1, d / Math.SQRT2);
    }
    return x / mw;
  }
  function pmod(a, b) { var r = a % b; return r < 0 ? r + b : r; }
  function hlsV(m1, m2, hue) {
    hue = pmod(hue, 1.0);
    if (hue < 1 / 6) return m1 + (m2 - m1) * hue * 6.0;
    if (hue < 0.5) return m2;
    if (hue < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - hue) * 6.0;
    return m1;
  }
  function hsl(h, s, l) {
    h = pmod(h, 1.0);
    var r, g, b;
    if (s === 0) { r = g = b = l; }
    else {
      var m2 = l <= 0.5 ? l * (1.0 + s) : l + s - (l * s), m1 = 2.0 * l - m2;
      r = hlsV(m1, m2, h + 1 / 3); g = hlsV(m1, m2, h); b = hlsV(m1, m2, h - 1 / 3);
    }
    return joinRgb(r * 255, g * 255, b * 255);
  }

  var FX = {};
  FX.color = function (art, p) {
    var fg = col(p.fg), bg = col(p.bg);
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {
      if (fg !== null && art.isInk(x, y)) art.fg[y][x] = fg;
      if (bg !== null) art.bg[y][x] = bg;
    }
    return art;
  };
  FX.gradient = function (art, p) {
    var stops = (p.stops || []).slice(0, 16).map(col).filter(function (c) { return c !== null; });
    if (!stops.length) stops = [0x7AA2FF, 0xB18CFF];
    var mode = p.mode || 'horizontal', target = p.target || 'fg', w = art.width, h = art.height;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var c = gradientColor(stops, tFor(mode, x, y, w, h));
      if (target === 'bg') art.bg[y][x] = c; else if (art.isInk(x, y)) art.fg[y][x] = c;
    }
    return art;
  };
  FX.rainbow = function (art, p) {
    var s = flt(p.saturation, 0, 1, 0.75), l = flt(p.lightness, 0, 1, 0.62), off = flt(p.offset, -10, 10, 0), cyc = flt(p.cycles, 0.1, 20, 1);
    var mode = p.mode || 'horizontal', w = art.width, h = art.height;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) if (art.isInk(x, y)) art.fg[y][x] = hsl(off + tFor(mode, x, y, w, h) * cyc * 0.83, s, l);
    return art;
  };
  FX.shadow = function (art, p) { return offsetLayer(art, int(p.dx, -8, 8, 1), int(p.dy, -8, 8, 1), chr(p.char, '░'), col(p.color)); };
  FX.double_shadow = function (art, p) {
    var dx = int(p.dx, -8, 8, 1), dy = int(p.dy, -8, 8, 1);
    var a = offsetLayer(art, dx, dy, chr(p.char1, '▒'), col(p.color1));
    return offsetLayer(a, dx, dy, chr(p.char2, '░'), col(p.color2));
  };
  FX.outline = function (art, p) {
    var ch = chr(p.char, '·'), diag = p.diagonal !== false, color = col(p.color);
    var out = grow(art, 1, 1, 1, 1), y, x;
    var src = []; for (y = 0; y < out.height; y++) { var r = []; for (x = 0; x < out.width; x++) r.push(out.isInk(x, y)); src.push(r); }
    var nb = [[-1, 0], [1, 0], [0, -1], [0, 1]].concat(diag ? [[-1, -1], [1, -1], [-1, 1], [1, 1]] : []);
    for (y = 0; y < out.height; y++) for (x = 0; x < out.width; x++) {
      if (src[y][x]) continue;
      for (var k = 0; k < nb.length; k++) {
        var xx = x + nb[k][0], yy = y + nb[k][1];
        if (xx >= 0 && xx < out.width && yy >= 0 && yy < out.height && src[yy][xx]) { out.chars[y][x] = ch; out.fg[y][x] = color; break; }
      }
    }
    return out;
  };
  FX.extrude = function (art, p) {
    var depth = int(p.depth, 1, 12, 3), d = p.direction || 'se';
    var dx = d.indexOf('e') >= 0 ? 1 : d.indexOf('w') >= 0 ? -1 : 0, dy = d.indexOf('s') >= 0 ? 1 : d.indexOf('n') >= 0 ? -1 : 0;
    var ch = chr(p.char, '▒'), color = col(p.color);
    var left = Math.max(0, -dx * depth), top = Math.max(0, -dy * depth);
    var out = grow(art, left, top, Math.max(0, dx * depth), Math.max(0, dy * depth));
    var ink = []; for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) if (art.isInk(x, y)) ink.push([x, y]);
    for (var k = depth; k > 0; k--) ink.forEach(function (pt) {
      var tx = pt[0] + left + dx * k, ty = pt[1] + top + dy * k, ox = tx - left, oy = ty - top;
      if (ox >= 0 && ox < art.width && oy >= 0 && oy < art.height && art.isInk(ox, oy)) return;
      out.chars[ty][tx] = ch; out.fg[ty][tx] = color;
    });
    return out;
  };
  function mapChars(art, table) { art.chars.forEach(function (r) { for (var i = 0; i < r.length; i++) if (table[r[i]] !== undefined) r[i] = table[r[i]]; }); }
  FX.mirror = function (art) { [art.chars, art.fg, art.bg].forEach(function (rows) { rows.forEach(function (r) { r.reverse(); }); }); mapChars(art, MIRROR_H); return art; };
  FX.flip_v = function (art) { art.chars.reverse(); art.fg.reverse(); art.bg.reverse(); mapChars(art, FLIP_V); return art; };
  FX.rotate = function (art, p) {
    var angle = (Math.floor(int(p.angle, 0, 360, 90) / 90) * 90) % 360;
    for (var n = 0; n < angle / 90; n++) {
      var h = art.height, w = art.width;
      var mk = function (src) { var o = []; for (var x = 0; x < w; x++) { var r = []; for (var y = 0; y < h; y++) r.push(src[h - 1 - y][x]); o.push(r); } return o; };
      art = new Art(mk(art.chars), mk(art.fg), mk(art.bg), art.meta);
      mapChars(art, ROT_90);
    }
    return art;
  };
  FX.invert = function (art, p) {
    var ch = chr(p.char, '█'), m = int(p.margin, 0, 10, 1), out = grow(art, m, m, m, m);
    for (var y = 0; y < out.height; y++) for (var x = 0; x < out.width; x++) {
      var c = out.chars[y][x];
      if (c === '') continue;
      if (INVERT_MAP[c] !== undefined) out.chars[y][x] = INVERT_MAP[c];
      else if (c === ' ') out.chars[y][x] = ch;
      else out.chars[y][x] = ' ';
    }
    return out;
  };
  FX.fill = function (art, p) { var ch = chr(p.char, '█'); for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) if (art.isInk(x, y)) art.chars[y][x] = ch; return art; };
  FX.background = function (art, p) {
    var ch = chr(p.char, '·'), color = col(p.color);
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) if (art.chars[y][x] === ' ') { art.chars[y][x] = ch; art.fg[y][x] = color; }
    return art;
  };
  FX.noise = function (art, p) {
    var rng = new Rng(int(p.seed, 0, 2147483648, 7)), amount = flt(p.amount, 0, 1, 0.05);
    var chars = cps(String(p.chars || '░▒▓·:')).slice(0, 64); if (!chars.length) chars = ['·'];
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {
      var r = rng.next(), k = rng.int(chars.length);
      if (r < amount && art.chars[y][x] === ' ') art.chars[y][x] = chars[k];
    }
    return art;
  };
  var GLITCH = cps('▓▒░█▌▐▀▄#%&@$?!/\\|<>');
  FX.glitch = function (art, p) {
    var rng = new Rng(int(p.seed, 0, 2147483648, 13)), amount = flt(p.amount, 0, 1, 0.25), shift = int(p.shift, 0, 20, 3);
    var out = grow(art, shift, 0, shift, 0);
    for (var y = 0; y < out.height; y++) {
      if (rng.next() < amount && shift) {
        var s = rng.int(2 * shift + 1) - shift;
        [['chars', ' '], ['fg', null], ['bg', null]].forEach(function (kv) {
          var r = out[kv[0]][y], fill = [], i;
          for (i = 0; i < Math.abs(s); i++) fill.push(kv[1]);
          if (s > 0) out[kv[0]][y] = fill.concat(r.slice(0, r.length - s));
          else if (s < 0) out[kv[0]][y] = r.slice(-s).concat(fill);
        });
      }
      for (var x = 0; x < out.width; x++) {
        var r2 = rng.next(), k = rng.int(GLITCH.length);
        if (out.isInk(x, y) && r2 < amount * 0.15) out.chars[y][x] = GLITCH[k];
      }
    }
    return out;
  };
  var MATRIX = cps('ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789');
  FX.matrix = function (art, p) {
    var rng = new Rng(int(p.seed, 0, 2147483648, 21)), density = flt(p.density, 0, 1, 0.5);
    var base = col(p.color) || 0x33FF66, c0 = splitRgb(base), h = art.height;
    for (var x = 0; x < art.width; x++) {
      var head = rng.int(Math.max(1, h));
      for (var y = 0; y < h; y++) {
        var k = rng.int(MATRIX.length), rr = rng.next();
        if (art.isInk(x, y)) {
          art.chars[y][x] = MATRIX[k];
          var f = y === head ? 1.0 : 0.55 + 0.45 * rr;
          art.fg[y][x] = y !== head ? joinRgb(c0[0] * f, c0[1] * f, c0[2] * f) : 0xE8FFE8;
        } else if (rr < density * 0.08) {
          art.chars[y][x] = MATRIX[k]; art.fg[y][x] = joinRgb(c0[0] * 0.3, c0[1] * 0.3, c0[2] * 0.3);
        }
      }
    }
    return art;
  };
  var ZU = [], ZD = [];
  (function () {
    var i, up = [0x033D, 0x033E, 0x033F, 0x0340, 0x0341, 0x0342, 0x0343, 0x0344, 0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369, 0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F];
    for (i = 0x0300; i < 0x0316; i++) ZU.push(String.fromCharCode(i));
    up.forEach(function (c) { ZU.push(String.fromCharCode(c)); });
    [0x0316, 0x0317, 0x0318, 0x0319, 0x031C, 0x031D, 0x031E, 0x031F, 0x0320, 0x0324, 0x0325, 0x0326, 0x0329, 0x032A, 0x032B, 0x032C, 0x032D, 0x032E, 0x032F, 0x0330, 0x0331, 0x0332, 0x0333, 0x0339, 0x033A, 0x033B, 0x033C, 0x0345, 0x0347, 0x0348, 0x0349, 0x034D, 0x034E, 0x0353, 0x0354, 0x0355, 0x0356, 0x0359, 0x035A].forEach(function (c) { ZD.push(String.fromCharCode(c)); });
  })();
  function zalgoText(text, intensity, seed) {
    var rng = new Rng(seed === undefined ? 3 : seed), out = [];
    cps(text).forEach(function (c) {
      out.push(c);
      if (/\s/.test(c)) return;
      for (var i = 0; i < (intensity || 2); i++) { out.push(ZU[rng.int(ZU.length)]); out.push(ZD[rng.int(ZD.length)]); }
    });
    return out.join('');
  }
  FX.zalgo = function (art, p) {
    var rng = new Rng(int(p.seed, 0, 2147483648, 3)), n = int(p.intensity, 1, 8, 2);
    for (var y = 0; y < art.height; y++) for (var x = 0; x < art.width; x++) {
      if (!art.isInk(x, y)) continue;
      var marks = '';
      for (var i = 0; i < n; i++) marks += ZU[rng.int(ZU.length)] + ZD[rng.int(ZD.length)];
      art.chars[y][x] += marks;
    }
    return art;
  };
  FX.frame = function (art, p) {
    var style = p.style || 'rounded', pad = int(p.padding, 0, 10, 1), f = cps(FRAMES[style] || FRAMES.rounded);
    var color = col(p.color), title = String(p.title || '').slice(0, 200);
    var out = grow(art, pad + 1, style !== 'terminal' ? pad + 1 : pad + 2, pad + 1, pad + 1);
    var w = out.width, h = out.height, x, y;
    for (x = 0; x < w; x++) { out.chars[0][x] = f[1]; out.chars[h - 1][x] = f[7]; out.fg[0][x] = color; out.fg[h - 1][x] = color; }
    for (y = 0; y < h; y++) { out.chars[y][0] = f[6]; out.chars[y][w - 1] = f[3]; out.fg[y][0] = color; out.fg[y][w - 1] = color; }
    out.chars[0][0] = f[0]; out.chars[0][w - 1] = f[2]; out.chars[h - 1][0] = f[4]; out.chars[h - 1][w - 1] = f[5];
    if (style === 'terminal') {
      for (x = 1; x < w - 1; x++) { out.chars[2][x] = '─'; out.fg[2][x] = color; }
      out.chars[2][0] = '├'; out.chars[2][w - 1] = '┤';
      cps('● ● ●').forEach(function (c, i) { if (2 + i < w - 1) out.chars[1][2 + i] = c; });
      if (title) {
        var tl = cps(title), start = Math.max(8, Math.floor((w - tl.length) / 2));
        tl.slice(0, Math.max(0, w - start - 2)).forEach(function (c, i) { out.chars[1][start + i] = c; });
      }
    } else if (title) {
      cps(' ' + title + ' ').slice(0, Math.max(0, w - 4)).forEach(function (c, i) { out.chars[0][2 + i] = c; });
    }
    return out;
  };
  FX.padding = function (art, p) { return grow(art, int(p.left, 0, 50, 2), int(p.top, 0, 50, 1), int(p.right, 0, 50, 2), int(p.bottom, 0, 50, 1)); };
  FX.glow = function (art, p) { art.meta.glow = { color: p.color || '#7aa2ff', radius: int(p.radius, 1, 40, 6), strength: flt(p.strength, 0, 1, 0.8) }; return art; };

  function applyEffects(art, pipeline) {
    var out = art.copy();
    (pipeline || []).forEach(function (eff) {
      if (!eff || eff.enabled === false) return;
      var fn = FX[eff.type];
      if (!fn) return;
      out = fn(out, eff);
      out.normalize();
      if (out.width * out.height > 2000000) throw new Error('effect output too large; reduce text, depth or padding');
    });
    return out;
  }
  function pipelineRepresentation(pipeline) {
    var kinds = new Set(), lossy = [];
    (pipeline || []).forEach(function (e) {
      if (e.enabled === false) return;
      var info = EFFECT_INFO[e.type] || ['text']; kinds.add(info[0]);
      if (info[0] !== 'text') lossy.push(info[1]);
    });
    return { plainText: !kinds.has('color') && !kinds.has('graphic'), ansi: !kinds.has('graphic'), lossyInText: lossy.sort() };
  }

  LB.Art = Art;
  LB.color = { hexToRgb: hexToRgb, rgbToHex: rgbToHex, splitRgb: splitRgb, joinRgb: joinRgb, hsl: hsl };
  LB.effects = { Rng: Rng, DEFAULTS: DEFAULTS, EFFECT_INFO: EFFECT_INFO, FRAMES: FRAMES, newEffect: newEffect, applyEffects: applyEffects,
    pipelineRepresentation: pipelineRepresentation, zalgoText: zalgoText, gradientColor: gradientColor };
})(LB);
