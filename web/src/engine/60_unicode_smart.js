/* LeerBox — Unicode styles, encoders, text boxes and deterministic smart features
 * (ports of unicode_styles.py and smart.py). */
(function (LB) {
  'use strict';
  var cps = function (s) { return Array.from(s); };
  var fcp = String.fromCodePoint;
  var MATH = {
    bold: [0x1D400, 0x1D41A, 0x1D7CE, {}], italic: [0x1D434, 0x1D44E, null, { h: 0x210E }], bold_italic: [0x1D468, 0x1D482, null, {}],
    script: [0x1D49C, 0x1D4B6, null, { B: 0x212C, E: 0x2130, F: 0x2131, H: 0x210B, I: 0x2110, L: 0x2112, M: 0x2133, R: 0x211B, e: 0x212F, g: 0x210A, o: 0x2134 }],
    bold_script: [0x1D4D0, 0x1D4EA, null, {}], fraktur: [0x1D504, 0x1D51E, null, { C: 0x212D, H: 0x210C, I: 0x2111, R: 0x211C, Z: 0x2128 }],
    bold_fraktur: [0x1D56C, 0x1D586, null, {}],
    double_struck: [0x1D538, 0x1D552, 0x1D7D8, { C: 0x2102, H: 0x210D, N: 0x2115, P: 0x2119, Q: 0x211A, R: 0x211D, Z: 0x2124 }],
    sans: [0x1D5A0, 0x1D5BA, 0x1D7E2, {}], sans_bold: [0x1D5D4, 0x1D5EE, 0x1D7EC, {}], sans_italic: [0x1D608, 0x1D622, null, {}],
    sans_bold_italic: [0x1D63C, 0x1D656, null, {}], monospace: [0x1D670, 0x1D68A, 0x1D7F6, {}]
  };
  function zip(a, b) { var m = {}, A = cps(a), B = cps(b); for (var i = 0; i < A.length; i++) m[A[i]] = B[i]; return m; }
  var SMALL_CAPS = zip('abcdefghijklmnopqrstuvwxyz', 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ');
  var SUPER = zip('0123456789abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW+-=()',
    '⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ⁺⁻⁼⁽⁾');
  var SUB = zip('0123456789aehijklmnoprstuvx+-=()', '₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ₊₋₌₍₎');
  var UPSIDE = zip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?'\"()[]{}<>_&;",
    "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz∀ꓭƆꓷƎℲ⅁HIſꓘ˥WNOԀΌꓤS⊥∩ΛMX⅄Z0ƖᄅƐㄣϛ9ㄥ86˙'¡¿,„)(][}{><‾⅋؛");
  var COMBINING = { strike: '̶', underline: '̲', double_underline: '̳', overline: '̅', slash: '̸', dots_above: '̇', x_above: '̽' };
  var STYLE_NAMES = {
    bold: 'Mathematical bold', italic: 'Mathematical italic', bold_italic: 'Mathematical bold italic', script: 'Script', bold_script: 'Bold script',
    fraktur: 'Fraktur', bold_fraktur: 'Bold Fraktur', double_struck: 'Double-struck', sans: 'Sans-serif', sans_bold: 'Sans-serif bold',
    sans_italic: 'Sans-serif italic', sans_bold_italic: 'Sans-serif bold italic', monospace: 'Monospace', fullwidth: 'Full-width',
    circled: 'Bubble (circled)', negative_circled: 'Negative bubble', squared: 'Squared', negative_squared: 'Negative squared',
    parenthesized: 'Parenthesized', small_caps: 'Small caps', superscript: 'Superscript', subscript: 'Subscript', upside_down: 'Upside down',
    strike: 'Strikethrough', underline: 'Underline', double_underline: 'Double underline', overline: 'Overline', slash: 'Slashed',
    spaced: 'Spaced (aesthetic)', regional: 'Regional indicator letters'
  };
  function isAZ(c) { return c >= 'A' && c <= 'Z'; }
  function isaz(c) { return c >= 'a' && c <= 'z'; }
  function stylize(text, style) {
    var a = cps(text);
    if (MATH[style]) {
      var m = MATH[style];
      return a.map(function (c) {
        if (m[3][c]) return fcp(m[3][c]);
        if (isAZ(c)) return fcp(m[0] + c.charCodeAt(0) - 65);
        if (isaz(c)) return fcp(m[1] + c.charCodeAt(0) - 97);
        if (m[2] && c >= '0' && c <= '9') return fcp(m[2] + c.charCodeAt(0) - 48);
        return c;
      }).join('');
    }
    switch (style) {
      case 'fullwidth': return a.map(function (c) { return c === ' ' ? '　' : (c >= '!' && c <= '~') ? fcp(c.charCodeAt(0) + 0xFEE0) : c; }).join('');
      case 'circled': return a.map(function (c) { if (isAZ(c)) return fcp(0x24B6 + c.charCodeAt(0) - 65); if (isaz(c)) return fcp(0x24D0 + c.charCodeAt(0) - 97); if (c === '0') return '⓪'; if (c >= '1' && c <= '9') return fcp(0x2460 + c.charCodeAt(0) - 49); return c; }).join('');
      case 'negative_circled': return a.map(function (c) { if (isAZ(c) || isaz(c)) return fcp(0x1F150 + c.toUpperCase().charCodeAt(0) - 65); if (c === '0') return '⓿'; if (c >= '1' && c <= '9') return fcp(0x2776 + c.charCodeAt(0) - 49); return c; }).join('');
      case 'squared': case 'negative_squared':
        var base = style === 'squared' ? 0x1F130 : 0x1F170;
        return a.map(function (c) { return (isAZ(c) || isaz(c)) ? fcp(base + c.toUpperCase().charCodeAt(0) - 65) : c; }).join('');
      case 'parenthesized': return a.map(function (c) { if (isaz(c)) return fcp(0x249C + c.charCodeAt(0) - 97); if (isAZ(c)) return fcp(0x1F110 + c.charCodeAt(0) - 65); if (c >= '1' && c <= '9') return fcp(0x2474 + c.charCodeAt(0) - 49); return c; }).join('');
      case 'small_caps': return a.map(function (c) { return (isAZ(c) || isaz(c)) ? (SMALL_CAPS[c.toLowerCase()] || c) : c; }).join('');
      case 'superscript': return a.map(function (c) { return SUPER[c] || SUPER[c.toLowerCase()] || c; }).join('');
      case 'subscript': return a.map(function (c) { return SUB[c] || SUB[c.toLowerCase()] || c; }).join('');
      case 'upside_down': return a.reverse().map(function (c) { return UPSIDE[c] || c; }).join('');
      case 'spaced': return a.join(' ');
      case 'regional': return a.map(function (c) { return (isAZ(c) || isaz(c)) ? fcp(0x1F1E6 + c.toUpperCase().charCodeAt(0) - 65) : c; }).join('​');
    }
    if (COMBINING[style]) return a.map(function (c) { return /\s/.test(c) ? c : c + COMBINING[style]; }).join('');
    throw new Error('unknown style ' + style);
  }
  var MORSE = { A: '.-', B: '-...', C: '-.-.', D: '-..', E: '.', F: '..-.', G: '--.', H: '....', I: '..', J: '.---', K: '-.-', L: '.-..', M: '--',
    N: '-.', O: '---', P: '.--.', Q: '--.-', R: '.-.', S: '...', T: '-', U: '..-', V: '...-', W: '.--', X: '-..-', Y: '-.--', Z: '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.', '!': '-.-.--', '/': '-..-.', '(': '-.--.', ')': '-.--.-', '&': '.-...',
    ':': '---...', ';': '-.-.-.', '=': '-...-', '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.', '$': '...-..-', '@': '.--.-.' };
  var MORSE_REV = {}; Object.keys(MORSE).forEach(function (k) { MORSE_REV[MORSE[k]] = k; });
  var BR = { a: '⠁', b: '⠃', c: '⠉', d: '⠙', e: '⠑', f: '⠋', g: '⠛', h: '⠓', i: '⠊', j: '⠚',
    k: '⠅', l: '⠇', m: '⠍', n: '⠝', o: '⠕', p: '⠏', q: '⠟', r: '⠗', s: '⠎', t: '⠞',
    u: '⠥', v: '⠧', w: '⠺', x: '⠭', y: '⠽', z: '⠵', ',': '⠂', ';': '⠆', ':': '⠒', '.': '⠲',
    '!': '⠖', '?': '⠦', "'": '⠄', '-': '⠤', '(': '⠐⠣', ')': '⠐⠜', '/': '⠸⠌', ' ': ' ' };
  var BRD = zip('1234567890', '⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚');
  function toBraille(text) {
    var out = [], num = false;
    cps(text).forEach(function (c) {
      if (c >= '0' && c <= '9') { if (!num) { out.push('⠼'); num = true; } out.push(BRD[c]); return; }
      num = false;
      if (c !== c.toLowerCase() && c === c.toUpperCase()) { out.push('⠠'); c = c.toLowerCase(); }
      out.push(BR[c] || c);
    });
    return out.join('');
  }
  function utf8(s) { return new TextEncoder().encode(s); }
  function encode(text, kind, sep) {
    sep = sep === undefined ? ' ' : sep;
    var b = Array.from(utf8(text));
    switch (kind) {
      case 'binary': return b.map(function (x) { return ('0000000' + x.toString(2)).slice(-8); }).join(sep);
      case 'hex': return b.map(function (x) { return ('0' + x.toString(16).toUpperCase()).slice(-2); }).join(sep);
      case 'octal': return b.map(function (x) { return ('00' + x.toString(8)).slice(-3); }).join(sep);
      case 'decimal': return cps(text).map(function (c) { return String(c.codePointAt(0)); }).join(sep);
      case 'codepoints': return cps(text).map(function (c) { var h = c.codePointAt(0).toString(16).toUpperCase(); return 'U+' + ('0000' + h).slice(-Math.max(4, h.length)); }).join(sep);
      case 'base64': { var bin = ''; b.forEach(function (x) { bin += String.fromCharCode(x); }); return btoa(bin); }
      case 'morse': return text.toUpperCase().split(/\s+/).filter(Boolean).map(function (w) {
        return cps(w).map(function (c) { return MORSE[c] || '?'; }).join(' ');
      }).join(' / ');
      case 'braille': return toBraille(text);
    }
    throw new Error('unknown encoding ' + kind);
  }
  function decode(text, kind) {
    var t = text.trim();
    if (kind === 'binary') {
      var bits = t.replace(/[^01]/g, '');
      if (bits.length % 8) throw new Error('binary length is not a multiple of 8');
      var arr = []; for (var i = 0; i < bits.length; i += 8) arr.push(parseInt(bits.slice(i, i + 8), 2));
      return new TextDecoder().decode(new Uint8Array(arr));
    }
    if (kind === 'hex') {
      var h = t.replace(/[^0-9a-fA-F]/g, '');
      if (h.length % 2) throw new Error('odd number of hex digits');
      var ar = []; for (var j = 0; j < h.length; j += 2) ar.push(parseInt(h.slice(j, j + 2), 16));
      return new TextDecoder().decode(new Uint8Array(ar));
    }
    if (kind === 'morse') return t.split('/').map(function (w) { return w.trim().split(/\s+/).filter(Boolean).map(function (s) { return MORSE_REV[s] || '?'; }).join(''); }).join(' ');
    if (kind === 'base64') { var bin = atob(t.replace(/\s+/g, '')); var u = new Uint8Array(bin.length); for (var k = 0; k < bin.length; k++) u[k] = bin.charCodeAt(k); return new TextDecoder().decode(u); }
    throw new Error('cannot decode ' + kind);
  }
  var ENCODINGS = { binary: 'Binary', hex: 'Hexadecimal', octal: 'Octal', decimal: 'Decimal code points', codepoints: 'Unicode code points',
    base64: 'Base64', morse: 'Morse code', braille: 'Braille (Grade 1)' };
  var BOX_STYLES = { rounded: ['╭', '─', '╮', '│', '╰', '╯'], single: ['┌', '─', '┐', '│', '└', '┘'],
    double: ['╔', '═', '╗', '║', '╚', '╝'], heavy: ['┏', '━', '┓', '┃', '┗', '┛'],
    ascii: ['+', '-', '+', '|', '+', '+'], stars: ['*', '*', '*', '*', '*', '*'], hash: ['#', '#', '#', '#', '#', '#'],
    block: ['█', '▀', '█', '█', '█', '█'] };
  function dispWidth(s) { return LB.figlet.graphemes(s).reduce(function (n, g) { return n + LB.figlet.charWidth(g); }, 0); }
  function textBox(text, style, padding, align, title) {
    var b = BOX_STYLES[style] || BOX_STYLES.rounded, pad = ' '.repeat(padding === undefined ? 1 : padding);
    padding = pad.length;
    var lines = text.split('\n');
    var inner = Math.max.apply(null, lines.map(dispWidth).concat([title ? dispWidth(title) + 2 : 0]));
    var top = b[0] + b[1].repeat(inner + 2 * padding) + b[2];
    if (title) { var tt = ' ' + title + ' '; top = b[0] + b[1] + tt + b[1].repeat(Math.max(0, inner + 2 * padding - dispWidth(tt) - 1)) + b[2]; }
    var out = [top];
    lines.forEach(function (ln) {
      var gap = inner - dispWidth(ln);
      if (align === 'center') ln = ' '.repeat(Math.floor(gap / 2)) + ln + ' '.repeat(gap - Math.floor(gap / 2));
      else if (align === 'right') ln = ' '.repeat(gap) + ln;
      else ln = ln + ' '.repeat(gap);
      out.push(b[3] + pad + ln + pad + b[3]);
    });
    out.push(b[4] + (style !== 'block' ? b[1] : '▄').repeat(inner + 2 * padding) + b[5]);
    return out.join('\n');
  }

  // ------------------------------------------------------------------ smart features
  var CURATED = [
    ['Neon nights', 'fig:ansi_shadow', [{ type: 'gradient', mode: 'horizontal', stops: ['#00e5ff', '#b14cff', '#ff3ea5'] }, { type: 'glow', color: '#b14cff', radius: 8 }]],
    ['Retro terminal', 'fig:big', [{ type: 'color', fg: '#33ff66' }, { type: 'frame', style: 'terminal', title: 'tty1' }, { type: 'glow', color: '#33ff66', radius: 5 }]],
    ['Sunset slant', 'fig:slant', [{ type: 'gradient', mode: 'vertical', stops: ['#ffcf5c', '#ff7a59', '#e04e8a'] }]],
    ['Matrix rain', 'fig:banner3', [{ type: 'matrix', density: 0.6 }]],
    ['Blueprint', 'fig:doom', [{ type: 'outline', char: '·', color: '#4f7dd1' }, { type: 'color', fg: '#cfe3ff' }, { type: 'frame', style: 'single', color: '#4f7dd1' }]],
    ['Gold 3D', 'fig:colossal', [{ type: 'extrude', depth: 2, direction: 'se', char: '▒', color: '#7a5a12' }, { type: 'gradient', mode: 'vertical', stops: ['#fff1a8', '#e0a526'] }]],
    ['Vaporwave', 'fig:ansi_regular', [{ type: 'double_shadow' }, { type: 'rainbow', mode: 'diagonal', saturation: 0.6, lightness: 0.7 }]],
    ['Gothic manuscript', 'fig:gothic', [{ type: 'color', fg: '#d8c7a0' }, { type: 'frame', style: 'double', color: '#8a6d3b' }]],
    ['Cyber glitch', 'fig:electronic', [{ type: 'glitch', amount: 0.3, shift: 2 }, { type: 'gradient', mode: 'horizontal', stops: ['#00ffd5', '#ff2bd6'] }]],
    ['Bloody horror', 'fig:bloody', [{ type: 'gradient', mode: 'vertical', stops: ['#ff4d4d', '#6e0000'] }]],
    ['Isometric ice', 'fig:isometric1', [{ type: 'gradient', mode: 'diagonal', stops: ['#e0fbff', '#5ac8fa', '#2f6fed'] }]],
    ['Minimal box', 'fig:small', [{ type: 'frame', style: 'rounded', padding: 1 }]],
    ['Pixel block', 'tlf:pagga', [{ type: 'rainbow', mode: 'horizontal', lightness: 0.6 }]],
    ['Shadow pop', 'fig:standard', [{ type: 'shadow', dx: 1, dy: 1, char: '░', color: '#4c566a' }, { type: 'color', fg: '#ffd166' }]]
  ];
  function curatedDesigns(fonts) {
    return CURATED.map(function (c) {
      var id = fonts.entries.has(c[1]) ? c[1] : 'fig:standard';
      return { name: c[0], font: id, effects: c[2].map(function (e) { var p = Object.assign({}, e); delete p.type; return LB.effects.newEffect(e.type, p); }) };
    });
  }
  function randColor(r) { return LB.color.rgbToHex(LB.color.hsl(r.next(), 0.55 + 0.4 * r.next(), 0.5 + 0.2 * r.next())); }
  var MODES3 = ['horizontal', 'vertical', 'diagonal'];
  var RANDOM_EFFECTS = [
    ['gradient', function (r) { return { mode: MODES3[r.int(3)], stops: [randColor(r), randColor(r), randColor(r)].slice(0, 2 + r.int(2)) }; }],
    ['rainbow', function (r) { return { mode: MODES3[r.int(3)], offset: Math.round(r.next() * 100) / 100 }; }],
    ['shadow', function (r) { return { char: '░▒.:'[r.int(4)] }; }],
    ['frame', function (r) { return { style: ['rounded', 'double', 'single', 'heavy', 'ascii'][r.int(5)] }; }],
    ['outline', function (r) { return { char: '·.:+'[r.int(4)] }; }],
    ['extrude', function (r) { return { depth: 1 + r.int(3), direction: ['se', 'sw', 'ne', 'nw'][r.int(4)] }; }]
  ];
  function randomDesign(fonts, seed, pool) {
    var r = new LB.effects.Rng(seed);
    var ids = pool || fonts.order.filter(function (id) { var t = fonts.entries.get(id).type; return t === 'figlet' || t === 'toilet'; });
    var id = ids.length ? ids[r.int(ids.length)] : 'fig:standard', effects = [], colorDone = false;
    var n = 1 + r.int(3);
    for (var i = 0; i < n; i++) {
      var k = RANDOM_EFFECTS[r.int(RANDOM_EFFECTS.length)], kind = k[0], gen = k[1];
      if (kind === 'gradient' || kind === 'rainbow') { if (colorDone) continue; colorDone = true; }
      if (effects.some(function (e) { return e.type === kind; })) continue;
      effects.push(LB.effects.newEffect(kind, gen(r)));
    }
    effects.sort(function (a, b) { return ((a.type === 'gradient' || a.type === 'rainbow') ? 1 : 0) - ((b.type === 'gradient' || b.type === 'rainbow') ? 1 : 0); });
    return { font: id, effects: effects, seed: seed };
  }
  function score(w, h, target, textLen) {
    if (w === 0 || h === 0) return -1000;
    var s;
    if (target === 'terminal') s = 100 - 3 * Math.abs(h - 6) - (w > 80 ? 200 : 0);
    else if (target === 'wide') s = 100 - 2 * Math.abs(h - 8) - (w > 120 ? 200 : 0);
    else if (target === 'compact') s = 100 - 25 * Math.max(0, h - 3) - 0.5 * w - (w > 60 ? 200 : 0);
    else s = 60 + 4 * Math.min(h, 12) - (w > 160 ? 200 : 0);
    if (textLen > 24 && h <= 5) s += 15;
    if (textLen <= 8 && h >= 8) s += 15;
    return s;
  }
  function widthWarning(w) {
    if (w > 200) return 'Output is ' + w + ' columns wide — it will wrap in most terminals. Try a compact font or a wrap width.';
    if (w > 120) return 'Output is ' + w + ' columns — wider than a 120-column terminal.';
    if (w > 80) return 'Output is ' + w + ' columns — wider than a standard 80-column terminal.';
    return null;
  }
  LB.unicode = { stylize: stylize, STYLE_NAMES: STYLE_NAMES, encode: encode, decode: decode, ENCODINGS: ENCODINGS, textBox: textBox, BOX_STYLES: BOX_STYLES, toBraille: toBraille };
  LB.smart = { curatedDesigns: curatedDesigns, randomDesign: randomDesign, score: score, widthWarning: widthWarning };
})(LB);
