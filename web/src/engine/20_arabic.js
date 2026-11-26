/* LeerBox — Arabic shaping and bidirectional reordering (port of src/leerbox/arabic.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };
  var T = null;
  function tables() { if (!T) T = LB.resources.arabicTables; return T; }

  function isTransparent(ch) {
    var o = ch.codePointAt(0);
    return (o >= 0x0610 && o <= 0x061A) || (o >= 0x064B && o <= 0x065F) || o === 0x0670 || (o >= 0x06D6 && o <= 0x06DC) ||
      (o >= 0x06DF && o <= 0x06E4) || (o >= 0x06E7 && o <= 0x06E8) || (o >= 0x06EA && o <= 0x06ED) ||
      (o >= 0x08D3 && o <= 0x08FF) || (o >= 0x0300 && o <= 0x036F);
  }
  function isArabicChar(ch) {
    var o = ch.codePointAt(0);
    return (o >= 0x0600 && o <= 0x06FF) || (o >= 0x0750 && o <= 0x077F) || (o >= 0x08A0 && o <= 0x08FF) ||
      (o >= 0xFB50 && o <= 0xFDFF) || (o >= 0xFE70 && o <= 0xFEFF);
  }
  function containsArabic(text) { return cps(text).some(isArabicChar); }
  var DIGITS = {
    western: '0123456789',
    arabic: '٠١٢٣٤٥٦٧٨٩',
    persian: '۰۱۲۳۴۵۶۷۸۹'
  };
  function convertDigits(text, style) {
    if (!DIGITS[style]) return text;
    var target = DIGITS[style], keys = ['western', 'arabic', 'persian'];
    return cps(text).map(function (c) {
      for (var k = 0; k < keys.length; k++) { var i = DIGITS[keys[k]].indexOf(c); if (i >= 0) return target[i]; }
      return c;
    }).join('');
  }
  function shape(text, ligatures) {
    if (ligatures === undefined) ligatures = true;
    var t = tables(), forms = t.forms, jt = t.jt, lig = t.lig;
    var chars = cps(text), n = chars.length;
    var types = chars.map(function (c) { return isTransparent(c) ? 'T' : (jt[c] || 'U'); });
    function prevType(i) { var j = i - 1; while (j >= 0 && types[j] === 'T') j--; return j >= 0 ? types[j] : 'U'; }
    function nextIndex(i) { var j = i + 1; while (j < n && types[j] === 'T') j++; return j; }
    var out = [], i = 0;
    while (i < n) {
      var c = chars[i], ty = types[i];
      if (ty === 'T' || ty === 'U' || !forms[c]) { out.push(c); i++; continue; }
      var pt = prevType(i);
      var joinsPrev = (pt === 'D' || pt === 'C') && (ty === 'D' || ty === 'R' || ty === 'C');
      var j = nextIndex(i);
      if (ligatures && c === 'ل' && j < n && lig[chars[j]]) {
        var glyph = joinsPrev ? lig[chars[j]][1] : lig[chars[j]][0];
        if (glyph) { out.push(glyph); for (var k = i + 1; k < j; k++) out.push(chars[k]); i = j + 1; continue; }
      }
      var nt = j < n ? types[j] : 'U';
      var joinsNext = (ty === 'D' || ty === 'C') && (nt === 'D' || nt === 'R' || nt === 'C');
      var f = forms[c], g;
      if (joinsPrev && joinsNext) g = f[3] || f[1] || f[0];
      else if (joinsPrev) g = f[1] || f[0];
      else if (joinsNext) g = f[2] || f[0];
      else g = f[0];
      out.push(g || c);
      i++;
    }
    return out.join('');
  }

  var MIRROR = { '(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{', '<': '>', '>': '<', '«': '»', '»': '«',
    '‹': '›', '›': '‹', '⁅': '⁆', '⁆': '⁅', '﴾': '﴿', '﴿': '﴾' };
  var ET = new Set(Array.from('#$%°¢£¤¥‰‱′″‴₠₡₢₣₤₥₦₧₨₩₪₫€₭₮₯₰₱₲₳₴₵₸₹₺₼₽+-'));
  var ES = new Set(['+', '-']);
  var CS = new Set([',', '.', ':', '/', ' ', '،', ' ']);
  var WS = new Set(Array.from('            　\x0c'));
  function bidiClass(ch) {
    var o = ch.codePointAt(0);
    if (ch === '\n' || ch === ' ') return 'B';
    if (ch === '\t' || ch === '\x0b' || ch === '\x1f') return 'S';
    if (WS.has(ch)) return 'WS';
    if (o === 0x200E) return 'L';
    if (o === 0x200F) return 'R';
    if (o === 0x061C) return 'AL';
    if ((o >= 0x200B && o <= 0x200D) || o === 0xFEFF || (o >= 0x202A && o <= 0x202E) || (o >= 0x2066 && o <= 0x2069) || o < 0x20 || (o >= 0x7F && o < 0xA0)) return 'BN';
    if ((o >= 0x30 && o <= 0x39) || o === 0xB2 || o === 0xB3 || o === 0xB9 || (o >= 0x6F0 && o <= 0x6F9) || (o >= 0xFF10 && o <= 0xFF19) || (o >= 0x2070 && o <= 0x2079) || (o >= 0x2080 && o <= 0x2089)) return 'EN';
    if ((o >= 0x660 && o <= 0x669) || o === 0x66B || o === 0x66C || (o >= 0x600 && o <= 0x605) || o === 0x6DD) return 'AN';
    if (ES.has(ch)) return 'ES';
    if (ET.has(ch) || o === 0x66A) return 'ET';
    if (CS.has(ch)) return 'CS';
    if (isTransparent(ch) || (o >= 0x0300 && o <= 0x036F) || (o >= 0x0591 && o <= 0x05BD) || [0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7].indexOf(o) >= 0 || (o >= 0x20D0 && o <= 0x20FF) || (o >= 0xFE20 && o <= 0xFE2F)) return 'NSM';
    if ((o >= 0x0590 && o <= 0x05FF) || (o >= 0x07C0 && o <= 0x085F) || (o >= 0xFB1D && o <= 0xFB4F) || (o >= 0x10800 && o <= 0x10FFF) || (o >= 0x1E800 && o <= 0x1EFFF)) return 'R';
    if ((o >= 0x0600 && o <= 0x07BF) || (o >= 0x0860 && o <= 0x08FF) || (o >= 0xFB50 && o <= 0xFDFF) || (o >= 0xFE70 && o <= 0xFEFF)) return 'AL';
    if (o < 0x80) return /[A-Za-z]/.test(ch) ? 'L' : 'ON';
    if ((o >= 0x2000 && o <= 0x2BFF) || (o >= 0x3001 && o <= 0x3003) || (o >= 0xFE50 && o <= 0xFE6F) || (o >= 0xA1 && o <= 0xBF) || o === 0xD7 || o === 0xF7) return 'ON';
    return 'L';
  }
  function strong(t) { return (t === 'R' || t === 'AL' || t === 'EN' || t === 'AN') ? 'R' : t; }
  function resolveLevels(types, base) {
    var n = types.length, t = types.slice(), sos = base % 2 ? 'R' : 'L', i, j, k;
    var prev = sos;
    for (i = 0; i < n; i++) { if (t[i] === 'NSM') t[i] = prev; else if (t[i] !== 'BN') prev = t[i]; }
    var last = sos;
    for (i = 0; i < n; i++) { if (t[i] === 'L' || t[i] === 'R' || t[i] === 'AL') last = t[i]; else if (t[i] === 'EN' && last === 'AL') t[i] = 'AN'; }
    t = t.map(function (x) { return x === 'AL' ? 'R' : x; });
    for (i = 1; i < n - 1; i++) {
      if (t[i] === 'ES' && t[i - 1] === 'EN' && t[i + 1] === 'EN') t[i] = 'EN';
      else if (t[i] === 'CS' && t[i - 1] === t[i + 1] && (t[i - 1] === 'EN' || t[i - 1] === 'AN')) t[i] = t[i - 1];
    }
    i = 0;
    while (i < n) {
      if (t[i] === 'ET') {
        j = i; while (j < n && t[j] === 'ET') j++;
        if ((i > 0 && t[i - 1] === 'EN') || (j < n && t[j] === 'EN')) for (k = i; k < j; k++) t[k] = 'EN';
        i = j;
      } else i++;
    }
    t = t.map(function (x) { return (x === 'ES' || x === 'ET' || x === 'CS') ? 'ON' : x; });
    last = sos;
    for (i = 0; i < n; i++) { if (t[i] === 'L' || t[i] === 'R') last = t[i]; else if (t[i] === 'EN' && last === 'L') t[i] = 'L'; }
    var eor = sos, neutral = { B: 1, S: 1, WS: 1, ON: 1, BN: 1 };
    i = 0;
    while (i < n) {
      if (neutral[t[i]]) {
        j = i; while (j < n && neutral[t[j]]) j++;
        var before = i > 0 ? strong(t[i - 1]) : sos, after = j < n ? strong(t[j]) : eor;
        var d = before === after ? before : (base % 2 ? 'R' : 'L');
        for (k = i; k < j; k++) t[k] = d;
        i = j;
      } else i++;
    }
    var levels = t.map(function (x) {
      if (base % 2 === 0) return base + (x === 'R' ? 1 : (x === 'AN' || x === 'EN') ? 2 : 0);
      return base + ((x === 'L' || x === 'EN' || x === 'AN') ? 1 : 0);
    });
    for (i = n - 1; i >= 0; i--) { if (['WS', 'S', 'B', 'BN'].indexOf(types[i]) >= 0) levels[i] = base; else break; }
    for (i = 0; i < n; i++) {
      if (types[i] === 'S' || types[i] === 'B') {
        levels[i] = base;
        j = i - 1; while (j >= 0 && (types[j] === 'WS' || types[j] === 'BN')) { levels[j] = base; j--; }
      }
    }
    return levels;
  }
  function paragraphLevel(text, direction) {
    if (direction === 'rtl') return 1;
    if (direction === 'ltr') return 0;
    var a = cps(text);
    for (var i = 0; i < a.length; i++) { var bc = bidiClass(a[i]); if (bc === 'L') return 0; if (bc === 'R' || bc === 'AL') return 1; }
    return 0;
  }
  function visualClusters(line, direction) {
    var clusters = LB.figlet.graphemes(line);
    if (!clusters.length) return [];
    var base = paragraphLevel(line, direction || 'auto');
    var types = clusters.map(function (c) { return bidiClass(cps(c)[0]); });
    if (base === 0 && !types.some(function (x) { return x === 'R' || x === 'AL' || x === 'AN'; })) return clusters;
    var levels = resolveLevels(types, base);
    var idx = clusters.map(function (_, i) { return i; });
    var top = Math.max.apply(null, levels);
    var odd = levels.filter(function (l) { return l % 2; });
    var lowOdd = odd.length ? Math.min.apply(null, odd) : top + 1;
    for (var lv = top; lv >= lowOdd; lv--) {
      var i = 0;
      while (i < idx.length) {
        if (levels[idx[i]] >= lv) {
          var j = i; while (j < idx.length && levels[idx[j]] >= lv) j++;
          var seg = idx.slice(i, j).reverse();
          for (var k = 0; k < seg.length; k++) idx[i + k] = seg[k];
          i = j;
        } else i++;
      }
    }
    return idx.map(function (k) {
      var c = clusters[k], first = cps(c)[0];
      if (levels[k] % 2 && MIRROR[first]) c = MIRROR[first] + cps(c).slice(1).join('');
      return c;
    });
  }
  function visualText(text, direction, shapeText, ligatures, digits) {
    text = convertDigits(text, digits || 'keep');
    return text.split('\n').map(function (line) {
      var s = shapeText === false ? line : shape(line, ligatures !== false);
      return visualClusters(s, direction || 'auto').join('');
    }).join('\n');
  }
  function stripDiacritics(text) { return cps(text).filter(function (c) { return !isTransparent(c); }).join(''); }

  LB.arabic = { shape: shape, visualClusters: visualClusters, visualText: visualText, bidiClass: bidiClass,
    resolveLevels: resolveLevels, paragraphLevel: paragraphLevel, containsArabic: containsArabic, isArabicChar: isArabicChar,
    convertDigits: convertDigits, stripDiacritics: stripDiacritics, isTransparent: isTransparent };
})(LB);
