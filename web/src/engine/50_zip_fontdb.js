/* LeerBox — safe ZIP reader/writer, font manager and rendering facade (ports of fontdb.py / textart.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };

  // ------------------------------------------------------------------ ZIP
  var CRC_TABLE = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) { var c = n; for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(bytes) { var c = 0xFFFFFFFF; for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
  function u16(b, o) { return b[o] | (b[o + 1] << 8); }
  function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }

  /** Read a ZIP archive. Rejects encrypted/unsupported entries, zip bombs and unsafe paths (reported per entry). */
  function zipRead(bytes, lim) {
    lim = Object.assign({ maxEntries: 2000, maxEntry: 6 * 1024 * 1024, maxTotal: 256 * 1024 * 1024, maxRatio: 200 }, lim || {});
    var eocd = -1;
    for (var i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (u32(bytes, i) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('invalid ZIP: end of central directory not found');
    var count = u16(bytes, eocd + 10), cdOff = u32(bytes, eocd + 16);
    if (count > lim.maxEntries) throw new Error('too many ZIP entries');
    var out = [], p = cdOff, total = 0;
    for (var n = 0; n < count; n++) {
      if (p + 46 > bytes.length || u32(bytes, p) !== 0x02014b50) throw new Error('corrupt ZIP central directory');
      var flags = u16(bytes, p + 8), method = u16(bytes, p + 10), csize = u32(bytes, p + 20), usize = u32(bytes, p + 24);
      var nlen = u16(bytes, p + 28), xlen = u16(bytes, p + 30), clen = u16(bytes, p + 32), lho = u32(bytes, p + 42);
      var name = new TextDecoder(flags & 0x800 ? 'utf-8' : 'latin1').decode(bytes.subarray(p + 46, p + 46 + nlen));
      p += 46 + nlen + xlen + clen;
      var entry = { name: name, dir: /\/$/.test(name), size: usize, data: null, error: null };
      out.push(entry);
      if (entry.dir) continue;
      var norm = name.replace(/\\/g, '/');
      if (/^\//.test(norm) || /^[A-Za-z]:/.test(norm) || norm.split('/').indexOf('..') >= 0) { entry.error = 'unsafe path rejected'; continue; }
      if (flags & 1) { entry.error = 'encrypted entry'; continue; }
      if (usize > lim.maxEntry) { entry.error = 'entry too large'; continue; }
      if (csize && usize / csize > lim.maxRatio) { entry.error = 'suspicious compression ratio (zip bomb?)'; continue; }
      total += usize;
      if (total > lim.maxTotal) { entry.error = 'archive exceeds total size limit'; break; }
      if (u32(bytes, lho) !== 0x04034b50) { entry.error = 'bad local header'; continue; }
      var start = lho + 30 + u16(bytes, lho + 26) + u16(bytes, lho + 28);
      var raw = bytes.subarray(start, start + csize);
      try {
        if (method === 0) entry.data = raw.slice();
        else if (method === 8) entry.data = LB.inflateRaw(raw, lim.maxEntry);
        else { entry.error = 'unsupported compression method ' + method; continue; }
        if (entry.data.length !== usize) { entry.error = 'size mismatch'; entry.data = null; }
      } catch (e) { entry.error = e.message; entry.data = null; }
    }
    return out;
  }
  /** Write an uncompressed (stored) ZIP archive. files: [{name, data(Uint8Array)}] */
  function zipWrite(files) {
    var enc = new TextEncoder(), parts = [], central = [], offset = 0;
    files.forEach(function (f) {
      var nameB = enc.encode(f.name), crc = crc32(f.data), h = new Uint8Array(30), v = new DataView(h.buffer);
      v.setUint32(0, 0x04034b50, true); v.setUint16(4, 20, true); v.setUint16(6, 0x800, true); v.setUint16(8, 0, true);
      v.setUint32(14, crc, true); v.setUint32(18, f.data.length, true); v.setUint32(22, f.data.length, true); v.setUint16(26, nameB.length, true);
      parts.push(h, nameB, f.data);
      var c = new Uint8Array(46), cv = new DataView(c.buffer);
      cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0x800, true);
      cv.setUint32(16, crc, true); cv.setUint32(20, f.data.length, true); cv.setUint32(24, f.data.length, true);
      cv.setUint16(28, nameB.length, true); cv.setUint32(42, offset, true);
      central.push(c, nameB);
      offset += 30 + nameB.length + f.data.length;
    });
    var cdSize = central.reduce(function (s, b) { return s + b.length; }, 0);
    var e = new Uint8Array(22), ev = new DataView(e.buffer);
    ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true);
    ev.setUint32(12, cdSize, true); ev.setUint32(16, offset, true);
    return new Blob(parts.concat(central, [e]), { type: 'application/zip' });
  }

  // ------------------------------------------------------------------ fuzzy search
  function isAlnum(c) { return /[\p{L}\p{N}]/u.test(c); }
  function fuzzyScore(query, text) {
    var q = query.toLowerCase().trim(), t = text.toLowerCase();
    if (!q) return 1;
    if (t === q) return 1000;
    var tl = cps(t).length, ql = cps(q).length;
    if (t.startsWith(q)) return 800 - Math.min(tl, 100);
    var i = t.indexOf(q);
    if (i >= 0) { i = cps(t.slice(0, i)).length; return 600 - Math.min(i, 100) - Math.floor(Math.min(tl, 100) / 4); }
    var T = cps(t), score = 0, ti = 0, streak = 0;
    var Q = cps(q);
    for (var k = 0; k < Q.length; k++) {
      var found = -1;
      for (var j = ti; j < T.length; j++) if (T[j] === Q[k]) { found = j; break; }
      if (found < 0) return 0;
      if (found === ti) { streak++; score += 10 + streak * 5; } else { streak = 0; score += 4; }
      if (found === 0 || !isAlnum(T[found - 1])) score += 8;
      ti = found + 1;
    }
    return Math.max(1, Math.min(399, score - Math.floor((tl - ql) / 3)));
  }

  // ------------------------------------------------------------------ font manager
  function FontManager() {
    this.entries = new Map(); this.order = []; this.pack = null; this.base = 0; this.cache = new Map(); this.hashes = null;
  }
  FontManager.prototype.loadPack = function (raw) {
    var head = new TextDecoder().decode(raw.subarray(0, 32));
    if (head.slice(0, 6) !== 'LBFP1\n') throw new Error('corrupt font pack');
    var nl = head.indexOf('\n', 6), n = parseInt(head.slice(6, nl), 10);
    var index = JSON.parse(new TextDecoder().decode(raw.subarray(nl + 1, nl + 1 + n)));
    this.pack = raw; this.base = nl + 1 + n;
    var self = this;
    index.forEach(function (meta) {
      var prefix = { figlet: 'fig', toilet: 'tlf', raster: 'ras' }[meta.type];
      var id = prefix + ':' + meta.name;
      self.entries.set(id, { id: id, name: meta.name, type: meta.type, meta: meta, builtin: true, payload: null,
        offset: meta.offset, length: meta.length,
        blob: [meta.name, meta.category || '', (meta.tags || []).join(' '), meta.author || '', meta.source || ''].join(' ') });
      self.order.push(id);
    });
  };
  FontManager.prototype.payload = function (e) { return e.payload || this.pack.subarray(this.base + e.offset, this.base + e.offset + e.length); };
  FontManager.prototype.font = function (id) {
    var c = this.cache.get(id);
    if (c) { this.cache.delete(id); this.cache.set(id, c); return c; }
    var e = this.entries.get(id);
    if (!e) throw new Error('unknown font ' + id);
    var data = this.payload(e), f;
    if (e.type === 'raster') f = LB.raster.parseRaster(JSON.parse(new TextDecoder().decode(data)), e.name);
    else f = LB.figlet.parseFont(new TextDecoder().decode(data), e.name);
    this.cache.set(id, f);
    if (this.cache.size > 160) this.cache.delete(this.cache.keys().next().value);
    return f;
  };
  FontManager.prototype.search = function (query, f) {
    f = Object.assign({ category: 'All', source: 'All', kind: 'All', minHeight: 0, maxHeight: 999, ids: null, unicodeOnly: false, licenseClear: false }, f || {});
    var pool = f.ids || this.order, scored = [], self = this;
    pool.forEach(function (id) {
      var e = self.entries.get(id);
      if (!e) return;
      var m = e.meta;
      if (f.category && f.category !== 'All' && f.category !== m.category && (m.tags || []).indexOf(f.category) < 0) return;
      if (f.source && f.source !== 'All' && m.source !== f.source && !(f.source === 'imported' && !e.builtin)) return;
      if (f.kind && f.kind !== 'All' && e.type !== f.kind && !(f.kind === 'genuine' && (e.type === 'figlet' || e.type === 'toilet'))) return;
      var h = m.height | 0;
      if (h < f.minHeight || h > f.maxHeight) return;
      if (f.unicodeOnly && (m.tags || []).indexOf('Unicode') < 0) return;
      if (f.licenseClear && m.licenseTier !== 'clear') return;
      var s = 0;
      if (query) { s = Math.max(fuzzyScore(query, e.name) * 2, fuzzyScore(query, e.blob)); if (s <= 0) return; }
      scored.push([-s, e.name.toLowerCase(), id]);
    });
    scored.sort(function (a, b) { return a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0); });
    return scored.map(function (s) { return s[2]; });
  };
  FontManager.prototype.categories = function () {
    var c = {};
    this.entries.forEach(function (e) { c[e.meta.category] = (c[e.meta.category] || 0) + 1; });
    return Object.keys(c).map(function (k) { return [k, c[k]]; }).sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
  };
  FontManager.prototype.sources = function () {
    var s = new Set(); this.entries.forEach(function (e) { s.add(e.meta.source); }); return Array.from(s).sort();
  };
  FontManager.prototype.stats = function () {
    var st = { total: this.entries.size, genuine: 0, raster: 0, imported: 0 };
    this.entries.forEach(function (e) {
      if ((e.type === 'figlet' || e.type === 'toilet') && e.builtin) st.genuine++;
      if (e.type === 'raster') st.raster++;
      if (!e.builtin) st.imported++;
    });
    return st;
  };
  async function sha256Hex(bytes) {
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      var d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
      return Array.from(d).map(function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    }
    return ('00000000' + crc32(bytes).toString(16)).slice(-8) + bytes.length.toString(16);
  }
  function asciiKey(font) {
    var parts = [String(font.height)];
    Array.from(font.glyphs.keys()).filter(function (c) { return c >= 32 && c <= 126; }).sort(function (a, b) { return a - b; }).forEach(function (c) {
      parts.push(c + ':' + font.glyphs.get(c).map(function (r) { return r.map(function (x) { return x === font.hardblank ? '\x00' : x; }).join('').replace(/ +$/, ''); }).join('\x01'));
    });
    return parts.join('\x02');
  }
  FontManager.prototype.builtinHashes = function () {
    if (!this.hashes) {
      var self = this; this.hashes = new Map();
      this.order.forEach(function (id) {
        var e = self.entries.get(id);
        if ((e.type === 'figlet' || e.type === 'toilet') && e.builtin) { try { self.hashes.set(asciiKey(self.font(id)), id); } catch (x) { /* skip */ } }
      });
    }
    return this.hashes;
  };
  /** Validate and register an imported FLF/TLF font. Never executes content; only parses text. */
  FontManager.prototype.importBytes = async function (bytes, filename) {
    var name = filename.replace(/^.*[\\/]/, '').replace(/\.(flf|tlf)$/i, '').slice(0, 80).replace(/[\x00-\x1f<>:"/\\|?*]/g, '_') || 'font';
    var text, kind, font;
    try { var d = LB.figlet.decodeFontBytes(bytes); text = d.text; kind = d.kind; font = LB.figlet.parseFont(text, name); }
    catch (e) { return { ok: false, file: filename, error: e.message }; }
    var key = asciiKey(font), dup = this.builtinHashes().get(key);
    if (dup) return { ok: false, file: filename, duplicate: dup, error: 'duplicate of built-in font ' + this.entries.get(dup).name };
    var payload = new TextEncoder().encode(text), digest = await sha256Hex(payload);
    var id = 'usr:' + digest.slice(0, 10) + ':' + name;
    if (this.entries.has(id)) return { ok: false, file: filename, duplicate: id, error: 'already imported' };
    var rows = LB.figlet.renderFigletRows(font, 'Ab', {});
    var meta = { name: name, type: kind === 'flf' ? 'figlet' : 'toilet', format: kind.toUpperCase(), source: 'imported', licenseTier: 'user',
      license: 'Imported by user', author: null, height: font.height, category: 'Imported', tags: ['Imported', kind === 'tlf' ? 'Unicode' : 'ASCII'],
      file: filename, sampleWidth: Math.max.apply(null, rows.map(function (r) { return cps(r).length; }).concat([0])), sha256: digest,
      coverage: { glyphs: font.glyphs.size }, layout: font.fullLayout };
    this.entries.set(id, { id: id, name: name + ' [import]', type: meta.type, meta: meta, builtin: false, payload: payload, blob: name + ' imported ' + kind });
    this.order.push(id);
    this.cache.set(id, font);
    this.hashes.set(key, id);
    return { ok: true, file: filename, id: id, text: text };
  };
  FontManager.prototype.importZip = async function (bytes) {
    if (bytes.length > 64 * 1024 * 1024) return [{ ok: false, file: 'archive', error: 'ZIP archive too large' }];
    var entries;
    try { entries = zipRead(bytes); } catch (e) { return [{ ok: false, file: 'archive', error: e.message }]; }
    var res = [];
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (e.dir || !/\.(flf|tlf)$/i.test(e.name)) continue;
      if (e.error || !e.data) { res.push({ ok: false, file: e.name, error: e.error || 'unreadable' }); continue; }
      res.push(await this.importBytes(e.data, e.name.replace(/^.*\//, '')));
    }
    if (!res.length) res.push({ ok: false, file: 'archive', error: 'no .flf/.tlf fonts found in archive' });
    return res;
  };
  FontManager.prototype.removeUser = function (id) {
    var e = this.entries.get(id);
    if (!e || e.builtin) return false;
    this.entries.delete(id); this.order.splice(this.order.indexOf(id), 1); this.cache.delete(id);
    if (this.hashes) this.hashes.forEach(function (v, k, m) { if (v === id) m.delete(k); });
    return true;
  };
  FontManager.prototype.exportCollection = function (ids) {
    var files = [], manifest = [], used = new Set(), self = this, enc = new TextEncoder();
    ids.forEach(function (id) {
      var e = self.entries.get(id);
      if (!e || e.type === 'raster') return;
      var ext = e.type === 'toilet' ? 'tlf' : 'flf', base = (e.meta.name || e.name).replace(/[^A-Za-z0-9_.-]/g, '_'), fn = base + '.' + ext, k = 2;
      while (used.has(fn)) fn = base + '_' + (k++) + '.' + ext;
      used.add(fn);
      files.push({ name: fn, data: self.payload(e) });
      manifest.push({ name: e.meta.name, source: e.meta.source, license: e.meta.license, licenseTier: e.meta.licenseTier, author: e.meta.author, repo: e.meta.repo, file: fn });
    });
    files.push({ name: 'MANIFEST.json', data: enc.encode(JSON.stringify(manifest, null, 1)) });
    return { blob: zipWrite(files), count: files.length - 1 };
  };

  // ------------------------------------------------------------------ rendering facade
  var TEXT_DEFAULTS = { h_layout: 'default', v_layout: 'default', width: 0, align: 'left', direction: 'auto', letter_spacing: 0,
    line_spacing: 0, fallback: true, missing: 'skip', raster_mode: 'block', raster_char: '@', raster_scale: 1, raster_aspect: 1,
    raster_invert: false, arabic_shaping: true, ligatures: true, diacritics: true, digits: 'keep' };
  function textOptions(d) {
    var o = Object.assign({}, TEXT_DEFAULTS);
    Object.keys(TEXT_DEFAULTS).forEach(function (k) {
      if (!d || d[k] === undefined) return;
      var t = typeof TEXT_DEFAULTS[k], v = d[k];
      if (t === 'boolean') o[k] = !!v;
      else if (t === 'number') { var n = parseInt(v, 10); if (!isNaN(n)) o[k] = Math.max(-50, Math.min(10000, n)); }
      else o[k] = String(v).slice(0, 64);
    });
    return o;
  }
  function hasRtl(text) { return cps(text).some(function (c) { var b = LB.arabic.bidiClass(c); return b === 'R' || b === 'AL'; }); }
  function renderFont(font, text, o) {
    text = cps(text).slice(0, 5000).join('');
    if (font.raster) {
      return LB.raster.renderRaster(font, text, {
        mode: o.raster_mode, char: o.raster_char, scale: o.raster_scale, aspect: o.raster_aspect, letterSpacing: Math.max(0, o.letter_spacing),
        lineSpacing: 2 + Math.max(0, o.line_spacing), align: (o.align === 'left' && hasRtl(text)) ? 'auto' : o.align,
        direction: o.direction, arabicShaping: o.arabic_shaping, ligatures: o.ligatures, diacritics: o.diacritics, digits: o.digits, invert: o.raster_invert
      });
    }
    if (hasRtl(text) && o.direction !== 'ltr') text = text.split('\n').map(function (ln) { return LB.arabic.visualClusters(ln, o.direction).join(''); }).join('\n');
    var rows = LB.figlet.renderFigletRows(font, text, { hLayout: o.h_layout, vLayout: o.v_layout, width: Math.max(0, o.width), align: o.align,
      direction: o.direction, letterSpacing: Math.max(0, o.letter_spacing), lineSpacing: Math.max(0, o.line_spacing), fallback: o.fallback, missing: o.missing });
    return LB.Art.fromText(rows.join('\n'));
  }
  function Engine(fonts) { this.fonts = fonts; this.cache = new Map(); }
  Engine.prototype.render = function (id, text, o, effects) {
    o = textOptions(o);
    var key = id + '\u0000' + text + '\u0000' + JSON.stringify(o) + '\u0000' + JSON.stringify(effects || []);
    var hit = this.cache.get(key);
    if (hit) return hit;
    var art = renderFont(this.fonts.font(id), text, o);
    if (effects && effects.length) art = LB.effects.applyEffects(art, effects);
    this.cache.set(key, art);
    if (this.cache.size > 256) this.cache.delete(this.cache.keys().next().value);
    return art;
  };
  Engine.prototype.unsupportedChars = function (id, text) {
    var font = this.fonts.font(id), bad = [];
    LB.figlet.graphemes(text).forEach(function (cl) {
      if (cl === '\n' || cl === ' ' || cl === '\t' || LB.figlet.charWidth(cl) === 0) return;
      var first = cps(cl)[0];
      if (font.raster) {
        if (LB.arabic.isArabicChar(first) && font.script === 'arabic') return;
        if (!font.glyphs.has(first)) { var g = LB.raster.findGlyph(font, first); if (!g || g === font.glyphs.get('?')) bad.push(cl); }
      } else if (LB.figlet.fallbackCodepoint(font.has, cl) === null) bad.push(cl);
    });
    return bad.filter(function (b, i) { return bad.indexOf(b) === i; });
  };

  LB.zipRead = zipRead; LB.zipWrite = zipWrite; LB.crc32 = crc32;
  LB.FontManager = FontManager; LB.Engine = Engine; LB.textOptions = textOptions; LB.TEXT_DEFAULTS = TEXT_DEFAULTS;
  LB.fuzzyScore = fuzzyScore; LB.renderFont = renderFont;
})(LB);
