/* LeerBox — FIGfont / TOIlet parser and layout engine.
 * Line-by-line port of src/leerbox/figlet.py; verified against the same golden fixtures.
 * Glyph rows are arrays of code points so astral characters behave like Python strings. */
(function (LB) {
  'use strict';
  var SM_EQUAL = 1, SM_LOWLINE = 2, SM_HIERARCHY = 4, SM_PAIR = 8, SM_BIGX = 16, SM_HARDBLANK = 32, SM_KERN = 64, SM_SMUSH = 128;
  var VSM_EQUAL = 256, VSM_LOWLINE = 512, VSM_HIERARCHY = 1024, VSM_HLINE = 2048, VSM_VLINE = 4096, VSM_KERN = 8192, VSM_SMUSH = 16384;
  var DEUTSCH = [196, 214, 220, 228, 246, 252, 223];
  var MAX_FONT_BYTES = 6 * 1024 * 1024, MAX_FONT_HEIGHT = 256, MAX_LINE_LENGTH = 4000, MAX_GLYPHS = 70000;
  var CODETAG_RE = /^\s*(-?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)(?:\s|$)/;
  var PY_SPACE = new Set(['\t', '\n', '\x0b', '\x0c', '\r', '\x1c', '\x1d', '\x1e', '\x1f', ' ', '\x85', '\xa0', ' ',
    ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
    ' ', ' ', ' ', ' ', '　']);
  var MARK_RE = /^\p{M}$/u;

  function FontError(msg) { var e = new Error(msg); e.name = 'FontError'; return e; }
  function cps(s) { return Array.from(s); }
  function isMark(ch) { return MARK_RE.test(ch); }

  function decodeFontBytes(bytes) {
    if (bytes.length > MAX_FONT_BYTES) throw FontError('font file exceeds size limit');
    if (bytes[0] === 0x50 && bytes[1] === 0x4b) {
      var entries = LB.zipRead(bytes, { maxEntry: MAX_FONT_BYTES, maxEntries: 50 });
      var first = entries.filter(function (e) { return !e.dir; })[0];
      if (!first) throw FontError('empty zipped font');
      bytes = first.data;
    }
    if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) bytes = bytes.subarray(3);
    var head = String.fromCharCode.apply(null, Array.from(bytes.subarray(0, 5)));
    var kind;
    if (head === 'tlf2a') kind = 'tlf'; else if (head === 'flf2a') kind = 'flf';
    else throw FontError('not a FIGlet (flf2a) or TOIlet (tlf2a) font');
    var text;
    try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch (e) {
      if (kind === 'tlf') text = new TextDecoder('utf-8').decode(bytes);
      else { text = ''; for (var i = 0; i < bytes.length; i += 8192) text += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 8192))); }
    }
    return { text: text, kind: kind };
  }

  function hdrInt(tok, dflt) {
    if (tok !== undefined && /^[+-]?\d+$/.test(tok)) return parseInt(tok, 10);
    if (dflt === undefined) throw FontError('invalid header number: ' + tok);
    return dflt;
  }

  function parseFont(data, name) {
    var text, kind;
    if (typeof data !== 'string') { var d = decodeFontBytes(data); text = d.text; kind = d.kind; }
    else {
      if (data.length > MAX_FONT_BYTES) throw FontError('font text exceeds size limit');
      text = data.replace(/^﻿/, '');
      kind = text.startsWith('tlf2a') ? 'tlf' : 'flf';
      if (!text.startsWith('flf2a') && !text.startsWith('tlf2a')) throw FontError('not a FIGlet (flf2a) or TOIlet (tlf2a) font');
    }
    var lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    var header = lines[0].split(/\s+/).filter(Boolean);
    var magic = header[0] || '';
    var mcp = cps(magic);
    if (mcp.length < 6 || (magic.slice(0, 5) !== 'flf2a' && magic.slice(0, 5) !== 'tlf2a')) throw FontError('invalid signature');
    var hardblank = mcp[5];
    if (header.length < 6) throw FontError('header has too few fields');
    var height = hdrInt(header[1]), baseline = hdrInt(header[2]), maxLength = hdrInt(header[3]);
    var oldLayout = hdrInt(header[4]), commentLines = hdrInt(header[5]);
    var printDirection = header.length > 6 ? hdrInt(header[6], 0) : 0;
    var fullLayout = header.length > 7 ? hdrInt(header[7], -1) : -1;
    var codetagCount = header.length > 8 ? hdrInt(header[8], 0) : 0;
    if (!(height >= 1 && height <= MAX_FONT_HEIGHT)) throw FontError('invalid font height ' + height);
    if (commentLines < 0 || commentLines > lines.length) throw FontError('invalid comment line count');
    if (oldLayout < -1 || oldLayout > 63) oldLayout = Math.max(-1, Math.min(63, oldLayout));
    if (fullLayout < 0) {
      if (oldLayout === 0) fullLayout = SM_KERN;
      else if (oldLayout < 0) fullLayout = 0;
      else fullLayout = (oldLayout & 31) | SM_SMUSH;
    }
    fullLayout &= 32767;
    if (printDirection !== 0 && printDirection !== 1) printDirection = 0;
    var comment = lines.slice(1, 1 + commentLines).join('\n');
    var pos = 1 + commentLines;
    var glyphs = new Map();
    var nLines = lines.length;

    function readGlyph() {
      if (pos + height > nLines) return null;
      var rows = [];
      for (var i = 0; i < height; i++) {
        var line = cps(lines[pos + i]);
        if (line.length > MAX_LINE_LENGTH) throw FontError('glyph line too long');
        var k = line.length - 1;
        while (k >= 0 && PY_SPACE.has(line[k])) k--;
        if (k >= 0) { var end = line[k]; while (k >= 0 && line[k] === end) k--; }
        rows.push(line.slice(0, k + 1));
      }
      pos += height;
      var width = 0;
      rows.forEach(function (r) { if (r.length > width) width = r.length; });
      return rows.map(function (r) { while (r.length < width) r.push(' '); return r; });
    }
    function lastNonSpace(s) { var a = cps(s.replace(/\s+$/, '')); return a.length ? a[a.length - 1] : ''; }
    function looksLikeCodetag(idx) {
      if (idx >= nLines) return false;
      if (!CODETAG_RE.test(lines[idx])) return false;
      var nxt = lines.slice(idx + 1, idx + 1 + height);
      if (nxt.length < height) return false;
      var ends = new Set(nxt.map(lastNonSpace));
      if (ends.size !== 1) return false;
      var e = ends.values().next().value;
      if (!e) return false;
      return lastNonSpace(lines[idx]) !== e;
    }
    for (var cp = 32; cp < 127; cp++) {
      var g = readGlyph();
      if (g === null) { if (cp === 32) throw FontError('truncated font: no glyphs'); break; }
      glyphs.set(cp, g);
    }
    if (glyphs.size === 95) {
      for (var di = 0; di < DEUTSCH.length; di++) {
        if (pos >= nLines || (!lines[pos].trim() && pos + 1 >= nLines)) break;
        if (looksLikeCodetag(pos)) break;
        var gd = readGlyph();
        if (gd === null) break;
        glyphs.set(DEUTSCH[di], gd);
      }
      while (pos < nLines) {
        var line = lines[pos];
        if (!line.trim()) { pos++; continue; }
        var m = CODETAG_RE.exec(line);
        if (!m) break;
        var neg = m[1], tok = m[2], c;
        if (/^0x/i.test(tok)) c = parseInt(tok, 16);
        else if (tok[0] === '0' && tok.length > 1) c = parseInt(tok, 8);
        else c = parseInt(tok, 10);
        pos++;
        var gt = readGlyph();
        if (gt === null) break;
        if (neg || c > 0x10ffff) continue;
        glyphs.set(c, gt);
        if (glyphs.size > MAX_GLYPHS) throw FontError('too many glyphs');
      }
    }
    if (!glyphs.has(32)) throw FontError('font has no space glyph');
    return {
      kind: kind, name: name || 'font', hardblank: hardblank, height: height, baseline: baseline, maxLength: maxLength,
      oldLayout: oldLayout, commentLines: commentLines, printDirection: printDirection, fullLayout: fullLayout,
      codetagCount: codetagCount, comment: comment, glyphs: glyphs,
      hMode: fullLayout & (63 | SM_KERN | SM_SMUSH),
      vMode: fullLayout & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE | VSM_VLINE | VSM_KERN | VSM_SMUSH),
      has: function (c) { return glyphs.has(c); }
    };
  }

  // ---------------------------------------------------------------- Unicode helpers
  function graphemes(text) {
    var a = cps(text), out = [], i = 0, n = a.length;
    while (i < n) {
      var j = i + 1, ch = a[i];
      if (ch === '\r' && j < n && a[j] === '\n') { out.push('\n'); i = j + 1; continue; }
      var o = ch.codePointAt(0);
      if (o >= 0x1F1E6 && o <= 0x1F1FF && j < n) { var o2 = a[j].codePointAt(0); if (o2 >= 0x1F1E6 && o2 <= 0x1F1FF) j++; }
      while (j < n) {
        var c = a[j], oc = c.codePointAt(0);
        if (isMark(c) || (oc >= 0xFE00 && oc <= 0xFE0F) || (oc >= 0xE0100 && oc <= 0xE01EF) || (oc >= 0x1F3FB && oc <= 0x1F3FF)) j++;
        else if (oc === 0x200D && j + 1 < n) j += 2;
        else break;
      }
      out.push(a.slice(i, j).join(''));
      i = j;
    }
    return out;
  }
  var WIDE = [[0x1100, 0x115F], [0x2E80, 0x303E], [0x3041, 0x33FF], [0x3400, 0x4DBF], [0x4E00, 0x9FFF], [0xA000, 0xA4CF],
    [0xAC00, 0xD7A3], [0xF900, 0xFAFF], [0xFE30, 0xFE4F], [0xFF00, 0xFF60], [0xFFE0, 0xFFE6], [0x1F300, 0x1F64F],
    [0x1F900, 0x1F9FF], [0x20000, 0x2FFFD], [0x30000, 0x3FFFD]];
  function charWidth(ch) {
    if (!ch) return 0;
    var first = cps(ch)[0], o = first.codePointAt(0);
    if (o < 32 || (o >= 0x7F && o < 0xA0)) return 0;
    if (isMark(first) || o === 0x200B) return 0;
    for (var i = 0; i < WIDE.length; i++) if (o >= WIDE[i][0] && o <= WIDE[i][1]) return 2;
    return 1;
  }
  function stripMarks(s) { return cps(s).filter(function (c) { return !isMark(c); }).join(''); }
  function single(s) { return cps(s).length === 1; }
  function fallbackCodepoint(has, cluster) {
    var cl = cps(cluster);
    if (cl.length === 1 && has(cl[0].codePointAt(0))) return cl[0].codePointAt(0);
    var nfc = cluster.normalize('NFC');
    if (single(nfc) && has(nfc.codePointAt(0))) return nfc.codePointAt(0);
    var base = cl[0];
    if (has(base.codePointAt(0))) return base.codePointAt(0);
    var stripped = stripMarks(base.normalize('NFKD'));
    if (single(stripped) && has(stripped.codePointAt(0))) return stripped.codePointAt(0);
    var alts = [base.toUpperCase(), base.toLowerCase(), stripped.toUpperCase(), stripped.toLowerCase()];
    for (var i = 0; i < alts.length; i++) if (single(alts[i]) && has(alts[i].codePointAt(0))) return alts[i].codePointAt(0);
    return null;
  }

  // ---------------------------------------------------------------- horizontal layout
  var HIER = ['|', '/\\', '[]', '{}', '()', '<>'];
  function hierClass(ch) { for (var i = 0; i < HIER.length; i++) if (ch.length === 1 && HIER[i].indexOf(ch) >= 0) return i; return -1; }
  var LOW_SET = '|/\\[]{}()<>';
  function inSet(ch, set) { return ch.length === 1 && set.indexOf(ch) >= 0; }

  function LineBuilder(font, mode, rtl, spacing) {
    this.font = font; this.mode = mode; this.rtl = rtl; this.spacing = spacing;
    this.rows = []; for (var i = 0; i < font.height; i++) this.rows.push([]);
    this.prevW = 0; this.curW = 0;
  }
  LineBuilder.prototype.smushChars = function (left, right) {
    if (left === ' ') return right;
    if (right === ' ') return left;
    if (this.prevW < 2 || this.curW < 2) return null;
    var mode = this.mode;
    if (!(mode & SM_SMUSH)) return null;
    var hb = this.font.hardblank;
    if (!(mode & 63)) {
      if (left === hb) return right;
      if (right === hb) return left;
      return this.rtl ? left : right;
    }
    if ((mode & SM_HARDBLANK) && left === hb && right === hb) return left;
    if (left === hb || right === hb) return null;
    if ((mode & SM_EQUAL) && left === right) return left;
    if (mode & SM_LOWLINE) {
      if (left === '_' && inSet(right, LOW_SET)) return right;
      if (right === '_' && inSet(left, LOW_SET)) return left;
    }
    if (mode & SM_HIERARCHY) {
      var cl = hierClass(left), cr = hierClass(right);
      if (cl >= 0 && cr >= 0 && cl !== cr) return cr > cl ? right : left;
    }
    if (mode & SM_PAIR) {
      var pr = left + right;
      if (pr === '[]' || pr === '][' || pr === '{}' || pr === '}{' || pr === '()' || pr === ')(') return '|';
    }
    if (mode & SM_BIGX) {
      if (left === '/' && right === '\\') return '|';
      if (left === '\\' && right === '/') return 'Y';
      if (left === '>' && right === '<') return 'X';
    }
    return null;
  };
  function rstripSpaces(a) { var k = a.length; while (k > 0 && a[k - 1] === ' ') k--; return k; }
  function lstripCount(a) { var k = 0; while (k < a.length && a[k] === ' ') k++; return k; }
  LineBuilder.prototype.smushAmount = function (glyph) {
    if (!(this.mode & (SM_SMUSH | SM_KERN))) return 0;
    var maxSmush = this.curW;
    for (var row = 0; row < this.font.height; row++) {
      var L = this.rows[row], R = glyph[row];
      if (this.rtl) { var t = L; L = R; R = t; }
      var linebd = rstripSpaces(L) - 1, ch1, ch2;
      if (linebd < 0) linebd = 0;
      if (linebd < L.length) ch1 = L[linebd]; else { linebd = 0; ch1 = ''; }
      var charbd = lstripCount(R);
      if (charbd < R.length) ch2 = R[charbd]; else { charbd = R.length; ch2 = ''; }
      var amt = charbd + L.length - 1 - linebd;
      if (ch1 === '' || ch1 === ' ') amt += 1;
      else if (ch2 !== '' && this.smushChars(ch1, ch2) !== null) amt += 1;
      if (amt < maxSmush) maxSmush = amt;
    }
    return maxSmush;
  };
  LineBuilder.prototype.add = function (glyph) {
    this.prevW = this.curW;
    this.curW = glyph.length ? glyph[0].length : 0;
    var amount = this.smushAmount(glyph);
    var empty = this.rows.every(function (r) { return r.length === 0; });
    if (this.spacing && !empty) amount -= this.spacing;
    if (amount < 0) {
      var pad = []; for (var p = 0; p < -amount; p++) pad.push(' ');
      var rtl = this.rtl;
      glyph = glyph.map(function (r) { return rtl ? r.concat(pad) : pad.concat(r); });
      amount = 0;
    }
    for (var row = 0; row < this.font.height; row++) {
      var left = this.rows[row], right = glyph[row];
      if (this.rtl) { var t = left; left = right; right = t; }
      left = left.slice();
      if (amount) {
        var ll = left.length;
        for (var i = 0; i < amount; i++) {
          var idx = ll - amount + i;
          var rc = i < right.length ? right[i] : '';
          if (idx >= 0 && idx < ll) {
            var sm = this.smushChars(left[idx], rc);
            left[idx] = sm !== null ? sm : rc;
          }
        }
      }
      this.rows[row] = left.concat(right.slice(amount));
    }
  };

  function resolveHMode(font, layout) {
    var base = font.hMode;
    if (!layout || layout === 'default') return base;
    if (layout === 'full') return 0;
    if (layout === 'fitted') return SM_KERN;
    if (layout === 'smush') return (base & 63) | SM_SMUSH;
    if (layout === 'universal') return SM_SMUSH;
    throw new Error('unknown horizontal layout ' + layout);
  }
  function resolveVMode(font, layout) {
    var base = font.vMode;
    if (!layout || layout === 'default') return base;
    if (layout === 'full') return 0;
    if (layout === 'fitted') return VSM_KERN;
    if (layout === 'smush') return (base & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE | VSM_VLINE)) | VSM_SMUSH;
    if (layout === 'universal') return VSM_SMUSH;
    throw new Error('unknown vertical layout ' + layout);
  }
  function glyphFor(font, cluster, fallback, missing) {
    if (cluster === '\t') cluster = ' ';
    var cp;
    if (fallback) cp = fallbackCodepoint(font.has, cluster);
    else { var c0 = cps(cluster)[0]; cp = (c0 && font.has(c0.codePointAt(0))) ? c0.codePointAt(0) : null; }
    if (cp !== null && cp !== undefined) return font.glyphs.get(cp);
    if (charWidth(cluster) === 0 && cluster !== ' ') return null;
    if (missing === 'skip') return null;
    if (missing === 'zero' && font.glyphs.has(0)) return font.glyphs.get(0);
    if (missing === 'question' && font.glyphs.has(63)) return font.glyphs.get(63);
    if (font.glyphs.has(0)) return font.glyphs.get(0);
    return null;
  }
  function renderLineRows(font, clusters, hMode, rtl, spacing, fallback, missing) {
    var b = new LineBuilder(font, hMode, rtl, spacing || 0);
    for (var i = 0; i < clusters.length; i++) {
      var g = glyphFor(font, clusters[i], fallback !== false, missing || 'skip');
      if (g) b.add(g);
    }
    return b.rows;
  }

  // ---------------------------------------------------------------- vertical layout
  function vSmushChar(top, bot, mode, hb) {
    if (top === ' ') return bot;
    if (bot === ' ') return top;
    if (!(mode & 0x7F00 & ~VSM_KERN)) return null;
    var rules = mode & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE | VSM_VLINE);
    if ((mode & VSM_SMUSH) && !rules) {
      if (top === hb) return bot;
      if (bot === hb) return top;
      return bot;
    }
    if ((mode & VSM_EQUAL) && top === bot) return top;
    if (mode & VSM_LOWLINE) {
      if (top === '_' && inSet(bot, LOW_SET)) return bot;
      if (bot === '_' && inSet(top, LOW_SET)) return top;
    }
    if (mode & VSM_HIERARCHY) {
      var ct = hierClass(top), cb = hierClass(bot);
      if (ct >= 0 && cb >= 0 && ct !== cb) return cb > ct ? bot : top;
    }
    if (mode & VSM_HLINE) { if ((top === '-' && bot === '_') || (top === '_' && bot === '-')) return '='; }
    if ((mode & VSM_VLINE) && top === '|' && bot === '|') return '|';
    return null;
  }
  function vOverlap(upper, lower, mode, hb) {
    if (!(mode & (VSM_KERN | VSM_SMUSH)) || !upper.length || !lower.length) return 0;
    var smush = !!(mode & VSM_SMUSH), best = 0;
    for (var d = 1; d <= Math.min(upper.length, lower.length); d++) {
      var collided = false, ok = true;
      for (var i = 0; i < d && ok; i++) {
        var a = upper[upper.length - d + i], b = lower[i];
        for (var x = 0; x < Math.min(a.length, b.length); x++) {
          var ca = a[x], cb = b[x];
          if (ca === ' ' || cb === ' ') continue;
          if (!smush) { ok = false; break; }
          if (vSmushChar(ca, cb, mode, hb) === null) { ok = false; break; }
          if (!((mode & VSM_VLINE) && ca === '|' && cb === '|')) collided = true;
        }
      }
      if (!ok) break;
      best = d;
      if (collided) break;
    }
    return best;
  }
  function vMerge(upper, lower, d, mode, hb) {
    if (d <= 0) return upper.concat(lower);
    var head = upper.slice(0, upper.length - d), mid = [];
    for (var i = 0; i < d; i++) {
      var a = upper[upper.length - d + i].slice(), b = lower[i].slice();
      var w = Math.max(a.length, b.length);
      while (a.length < w) a.push(' ');
      while (b.length < w) b.push(' ');
      var row = [];
      for (var x = 0; x < w; x++) { var sm = vSmushChar(a[x], b[x], mode, hb); row.push(sm !== null ? sm : b[x]); }
      mid.push(row);
    }
    return head.concat(mid, lower.slice(d));
  }

  // ---------------------------------------------------------------- public API
  function RenderOptions(o) {
    o = o || {};
    this.hLayout = o.hLayout || 'default'; this.vLayout = o.vLayout || 'default';
    this.width = o.width || 0; this.align = o.align || 'left'; this.direction = o.direction || 'auto';
    this.letterSpacing = o.letterSpacing || 0; this.lineSpacing = o.lineSpacing || 0;
    this.fallback = o.fallback !== false; this.missing = o.missing || 'skip'; this.maxInput = o.maxInput || 5000;
  }
  function wrapLine(font, clusters, opts, hMode, rtl) {
    var width = opts.width;
    if (width <= 0) return [clusters];
    function wOf(cl) {
      var rows = renderLineRows(font, cl, hMode, rtl, opts.letterSpacing, opts.fallback, opts.missing);
      var m = 0; rows.forEach(function (r) { var k = rstripSpaces(r); if (k > m) m = k; }); return m;
    }
    var words = [], cur = [];
    clusters.forEach(function (c) { if (c === ' ') { if (cur.length) words.push(cur); cur = []; } else cur.push(c); });
    if (cur.length) words.push(cur);
    var out = [], line = [];
    words.forEach(function (word) {
      var cand = line.length ? line.concat([' '], word) : word;
      if (wOf(cand) <= width) { line = cand; return; }
      if (line.length) { out.push(line); line = []; }
      if (wOf(word) <= width) { line = word; return; }
      var piece = [];
      word.forEach(function (c) { if (piece.length && wOf(piece.concat([c])) > width) { out.push(piece); piece = []; } piece.push(c); });
      line = piece;
    });
    if (line.length || !out.length) out.push(line);
    return out;
  }
  function renderFigletRows(font, text, opts) {
    opts = opts instanceof RenderOptions ? opts : new RenderOptions(opts);
    var t = cps(text);
    if (t.length > opts.maxInput) text = t.slice(0, opts.maxInput).join('');
    var hMode = resolveHMode(font, opts.hLayout), vMode = resolveVMode(font, opts.vLayout);
    var rtl = opts.direction === 'auto' ? font.printDirection === 1 : opts.direction === 'rtl';
    var hb = font.hardblank, blocks = [];
    text.replace(/\r\n/g, '\n').split('\n').forEach(function (rawLine) {
      var clusters = graphemes(rawLine);
      wrapLine(font, clusters, opts, hMode, rtl).forEach(function (piece) {
        var rows = renderLineRows(font, piece, hMode, rtl, opts.letterSpacing, opts.fallback, opts.missing);
        var w = 0; rows.forEach(function (r) { if (r.length > w) w = r.length; });
        blocks.push(rows.map(function (r) { r = r.slice(); while (r.length < w) r.push(' '); return r; }));
      });
    });
    var out = [];
    blocks.forEach(function (blk, i) {
      if (i === 0) { out = blk.slice(); return; }
      if (opts.lineSpacing > 0) { for (var k = 0; k < opts.lineSpacing; k++) out.push([]); out = out.concat(blk); }
      else { var d = vOverlap(out, blk, vMode, hb); out = vMerge(out, blk, d, vMode, hb); }
    });
    var strs = out.map(function (r) {
      var s = (hb !== ' ' ? r.map(function (c) { return c === hb ? ' ' : c; }) : r).join('');
      return s.replace(/ +$/, '');
    });
    // Python's rstrip() strips all whitespace; glyph rows only contain spaces after hardblank conversion
    strs = strs.map(function (s) { var a = cps(s), k = a.length; while (k > 0 && PY_SPACE.has(a[k - 1])) k--; return a.slice(0, k).join(''); });
    var width = 0; strs.forEach(function (s) { var l = cps(s).length; if (l > width) width = l; });
    if (opts.align === 'center' || opts.align === 'right') {
      var target = opts.width ? Math.max(width, opts.width) : width;
      strs = strs.map(function (s) {
        var l = cps(s).length;
        return opts.align === 'center' ? ' '.repeat(Math.floor((target - l) / 2)) + s : ' '.repeat(target - l) + s;
      });
    }
    return strs;
  }

  LB.figlet = {
    FontError: FontError, parseFont: parseFont, decodeFontBytes: decodeFontBytes, renderFigletRows: renderFigletRows,
    render: function (font, text, opts) { return renderFigletRows(font, text, opts).join('\n'); },
    RenderOptions: RenderOptions, graphemes: graphemes, charWidth: charWidth, fallbackCodepoint: fallbackCodepoint,
    isMark: isMark, cps: cps, PY_SPACE: PY_SPACE
  };
})(LB);
