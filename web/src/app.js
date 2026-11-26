/* LeerBox Text Art Studio 3.0 — HTML edition application logic.
 * Local-first: no network requests, no analytics. Settings in localStorage, imported fonts in IndexedDB. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var cps = function (s) { return Array.from(s); };
  var E = LB.effects, X = LB.exporter;
  var LS_KEY = 'leerbox-v3-settings';
  var S = {
    fid: 'fig:standard', mode: 'text', view: 'preview', opts: LB.textOptions({}), effects: [], exp: X.settings({}), zoom: 1,
    autofit: true, graphic: true, scope: 'All', filtered: [], compare: [], favorites: [], recents: [], presets: {},
    art: null, image: null, fxSel: -1, tool: {}, galleryGen: 0, recGen: 0
  };
  var fonts, engine, worker = null, workerReady = false, workerCallbacks = {}, IS = null;

  // ------------------------------------------------------------------ utilities
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else if (k === 'className') e.className = attrs[k];
      else if (attrs[k] !== false && attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (children || []).forEach(function (c) { if (c !== null && c !== undefined) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function status(msg, level) { var s = $('status'); s.textContent = msg; s.className = level || ''; }
  var timers = {};
  function debounce(key, fn, ms) { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); }
  function saveSettings() {
    try {
      var e = fonts.entries.get(S.fid);
      localStorage.setItem(LS_KEY, JSON.stringify({ favorites: S.favorites, recents: S.recents, presets: S.presets, zoom: S.zoom,
        autofit: S.autofit, graphic: S.graphic, last: LB.project.makeProject(getText(), S.fid, e ? e.name : '', S.opts, S.effects, S.exp) }));
    } catch (err) { /* storage may be blocked (private mode); the app keeps working */ }
  }
  function loadSettings() {
    try { var o = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); if (o && typeof o === 'object') return o; } catch (err) { /* ignore */ }
    return null;
  }
  function getText() { return $('text').value.slice(0, 5000); }
  function download(blob, name) {
    var url = URL.createObjectURL(blob), a = el('a', { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  async function copyText(text, what) {
    try { await navigator.clipboard.writeText(text); status('Copied ' + what + ' to clipboard', 'ok'); return; } catch (err) { /* fall back */ }
    var t = el('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0'; document.body.appendChild(t); t.select();
    var ok = false; try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    t.remove();
    status(ok ? 'Copied ' + what + ' to clipboard' : 'Clipboard unavailable — select the preview and copy manually', ok ? 'ok' : 'warn');
  }
  async function copyHtml(html, plain) {
    if (navigator.clipboard && window.ClipboardItem) {
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }), 'text/plain': new Blob([plain], { type: 'text/plain' }) })]);
        status('Copied as rich HTML', 'ok'); return;
      } catch (err) { /* fall through */ }
    }
    copyText(html, 'HTML source');
  }
  function dialog(nodes) {
    var b = $('dlgBody'); b.replaceChildren.apply(b, nodes);
    if ($('dlg').showModal) $('dlg').showModal(); else $('dlg').setAttribute('open', '');
  }

  // ------------------------------------------------------------------ IndexedDB for imported fonts
  var DB = null;
  function dbOpen() {
    return new Promise(function (res) {
      if (!window.indexedDB) return res(null);
      try {
        var r = indexedDB.open('leerbox-v3', 1);
        r.onupgradeneeded = function () { r.result.createObjectStore('fonts', { keyPath: 'id' }); };
        r.onsuccess = function () { res(r.result); };
        r.onerror = function () { res(null); };
      } catch (err) { res(null); }
    });
  }
  function dbTx(mode, fn) {
    return new Promise(function (res) {
      if (!DB) return res(null);
      try { var tx = DB.transaction('fonts', mode), st = tx.objectStore('fonts'), out = fn(st); tx.oncomplete = function () { res(out && out.result !== undefined ? out.result : null); }; tx.onerror = function () { res(null); }; }
      catch (err) { res(null); }
    });
  }

  // ------------------------------------------------------------------ worker
  function startWorker(packBytes) {
    try {
      var src = $('lb-engine').textContent + '\n' + $('lb-worker-src').textContent;
      var url = URL.createObjectURL(new Blob([src], { type: 'text/javascript' }));
      worker = new Worker(url);
      worker.onmessage = function (e) {
        var m = e.data;
        if (m.type === 'ready') { workerReady = true; return; }
        if (m.type === 'rendered') { var cb = workerCallbacks[m.id]; delete workerCallbacks[m.id]; if (cb) cb(m); return; }
        if (m.type === 'recommended') showRecommendations(m.gen, m.results);
      };
      worker.onerror = function () { worker = null; workerReady = false; };
      worker.postMessage({ type: 'init', pack: packBytes.slice().buffer, arabic: LB.resources.arabicTables });
    } catch (err) { worker = null; /* file:// restrictions: main-thread fallback */ }
  }
  var renderSeq = 0;
  function renderAsync(fid, text, opts, effects, gen) {
    return new Promise(function (res) {
      if (worker && workerReady && fonts.entries.get(fid).builtin) {
        var id = ++renderSeq;
        workerCallbacks[id] = res;
        worker.postMessage({ type: 'render', id: id, gen: gen, fid: fid, text: text, opts: opts, effects: effects });
      } else {
        setTimeout(function () {
          try { var a = engine.render(fid, text, opts, effects); res({ text: a.toText(), w: a.width, h: a.height }); }
          catch (err) { res({ error: err.message }); }
        }, 0);
      }
    });
  }

  // ------------------------------------------------------------------ font list (virtualized)
  var ROW_H = 26;
  function refreshFonts() {
    var ids = null;
    if (S.scope === 'Favorites') ids = S.favorites.filter(function (f) { return fonts.entries.has(f); });
    else if (S.scope === 'Recent') ids = S.recents.filter(function (f) { return fonts.entries.has(f); });
    else if (S.scope === 'Imported') ids = fonts.order.filter(function (f) { return !fonts.entries.get(f).builtin; });
    var hmax = +$('fHmax').value || 99;
    var res = fonts.search($('search').value, { category: $('fCat').value, source: $('fSrc').value, kind: $('fKind').value,
      minHeight: +$('fHmin').value || 0, maxHeight: hmax >= 99 ? 999 : hmax, ids: ids, licenseClear: $('fClear').checked });
    if (S.scope === 'Recent' && !$('search').value) res.sort(function (a, b) { return ids.indexOf(a) - ids.indexOf(b); });
    S.filtered = res;
    $('fontCount').textContent = res.length + ' of ' + fonts.entries.size + ' fonts';
    $('fontSpacer').style.height = (res.length * ROW_H) + 'px';
    paintFontList(true);
    if (S.mode === 'text' && S.view === 'gallery') buildGallery();
  }
  function paintFontList(scrollToSel) {
    var list = $('fontList'), spacer = $('fontSpacer');
    if (scrollToSel) {
      var i = S.filtered.indexOf(S.fid);
      if (i >= 0 && (i * ROW_H < list.scrollTop || (i + 1) * ROW_H > list.scrollTop + list.clientHeight)) list.scrollTop = Math.max(0, i * ROW_H - list.clientHeight / 2);
    }
    var first = Math.max(0, Math.floor(list.scrollTop / ROW_H) - 5), last = Math.min(S.filtered.length, first + Math.ceil(list.clientHeight / ROW_H) + 12);
    var fav = new Set(S.favorites), frag = document.createDocumentFragment();
    for (var k = first; k < last; k++) {
      var id = S.filtered[k], e = fonts.entries.get(id);
      var row = el('div', { className: 'item' + (id === S.fid ? ' sel' : ''), role: 'option', 'aria-selected': id === S.fid ? 'true' : 'false', 'data-id': id },
        [(fav.has(id) ? '★ ' : '') + e.name, el('span', { className: 'badge', text: e.type === 'toilet' ? 'TLF' : e.type === 'raster' ? (e.meta.category === 'Arabic' ? 'Arabic' : 'raster') : '' })]);
      row.style.top = (k * ROW_H) + 'px';
      frag.appendChild(row);
    }
    list.replaceChildren(spacer, frag);
  }
  function selectFont(id, keepView) {
    if (!fonts.entries.has(id)) return;
    S.fid = id;
    S.recents = [id].concat(S.recents.filter(function (r) { return r !== id; })).slice(0, 30);
    if (S.mode !== 'text') setMode('text');
    if (!keepView && S.view !== 'preview') setView('preview');
    paintFontList(true);
    requestRender();
    saveSettings();
  }

  // ------------------------------------------------------------------ rendering & preview
  function requestRender(ms) { debounce('render', doRender, ms === undefined ? 90 : ms); }
  function doRender() {
    var t0 = performance.now(), text = getText();
    try {
      if (S.mode === 'text') {
        if (S.view === 'gallery') { buildGallery(); return; }
        if (S.view === 'compare') { renderCompare(); return; }
        showArt(engine.render(S.fid, text, S.opts, S.effects), t0);
      } else if (S.mode === 'image' || S.mode === 'animation') {
        return;  // rendered by the Image / Animation Studio workspaces (imagestudio.js)
      } else if (S.mode === 'unicode') renderUnicode(text);
      else if (S.mode === 'encode') renderEncode(text);
      else if (S.mode === 'boxes') showArt(makeBox(text), t0);
    } catch (err) {
      status('Render error: ' + err.message, 'err');
    }
  }
  function cellMetrics() { var fs = 14 * S.zoomEff; return { cw: fs * 0.6021, ch: fs * 1.18 }; }
  function showArt(art, t0) {
    S.art = art;
    var stage = $('stage'), avail = stage.clientWidth - 40;
    S.zoomEff = S.zoom;
    if (S.autofit) S.zoomEff = Math.min(S.zoom, Math.max(0.35, avail / Math.max(1, art.width * 14 * 0.6021)));
    $('zoomLabel').textContent = Math.round(S.zoomEff * 100) + '%';
    var useGraphic = S.graphic && art.width * art.height <= 40000;
    if (useGraphic) {
      var canvas = el('canvas', { className: 'art', 'aria-label': 'Rendered text art' });
      try {
        X.renderCanvas(art, { font_size: Math.max(5, Math.round(14 * S.zoomEff)), padding: 18, background: '#0b0d12', foreground: '#e6e9ef', line_height: 1.2 }, canvas);
        canvas.title = art.toText().slice(0, 4000);
        stage.replaceChildren(canvas);
      } catch (err) { useGraphic = false; }
    }
    if (!useGraphic) stage.replaceChildren(artPre(art, Math.round(14 * S.zoomEff)));
    var e = fonts.entries.get(S.fid);
    $('sizeInfo').textContent = art.width + ' × ' + art.height + '  ·  ' + Math.round(performance.now() - (t0 || performance.now())) + ' ms' + (art.meta.glow ? '  ·  glow' : '');
    if (S.mode === 'text') {
      var bad = engine.unsupportedChars(S.fid, getText()), w = LB.smart.widthWarning(art.width);
      if (bad.length) status(e.name + ': cannot draw ' + bad.slice(0, 12).join(' ') + ' — see Info › Recommendations for compatible fonts.', 'warn');
      else if (w) status(e.name + ': ' + w, 'warn');
      else status(e.name + ' · ' + S.filtered.length + ' fonts in view');
      renderInfo();
    }
  }
  function artPre(art, size) {
    var pre = el('pre', { className: 'art' });
    if (size) pre.style.fontSize = size + 'px';
    if (art.meta.glow) pre.style.textShadow = '0 0 ' + art.meta.glow.radius + 'px ' + art.meta.glow.color;
    var frag = document.createDocumentFragment();
    for (var y = 0; y < art.height; y++) {
      var x = 0, w = art.width;
      while (x < w) {
        var fg = art.fg[y][x], bg = art.bg[y][x], start = x;
        while (x < w && art.fg[y][x] === fg && art.bg[y][x] === bg) x++;
        var seg = art.chars[y].slice(start, x).join('');
        if (fg === null && bg === null) frag.appendChild(document.createTextNode(seg));
        else { var sp = el('span', { text: seg }); if (fg !== null) sp.style.color = LB.color.rgbToHex(fg); if (bg !== null) sp.style.background = LB.color.rgbToHex(bg); frag.appendChild(sp); }
      }
      frag.appendChild(document.createTextNode('\n'));
    }
    pre.appendChild(frag);
    return pre;
  }

  // ------------------------------------------------------------------ gallery (lazy + content-visibility virtualization)
  var galleryObserver = null;
  function buildGallery() {
    var gen = ++S.galleryGen, stage = $('stage');
    if (galleryObserver) galleryObserver.disconnect();
    var grid = el('div', { className: 'gallery' }), text = getText().slice(0, 200) || 'LeerBox';
    var effects = S.effects.filter(function (e) { return (E.EFFECT_INFO[e.type] || ['text'])[0] === 'text'; });
    var opts = Object.assign({}, S.opts);
    galleryObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var card = en.target; galleryObserver.unobserve(card);
        var id = card.dataset.id;
        renderAsync(id, text, opts, effects, gen).then(function (m) {
          if (gen !== S.galleryGen) return;
          var pre = card.querySelector('pre');
          if (m.error) { pre.textContent = 'error: ' + m.error; pre.style.color = 'var(--err)'; }
          else { pre.textContent = m.text; card.querySelector('.dim').textContent = m.w + '×' + m.h; }
        });
      });
    }, { root: stage, rootMargin: '600px' });
    S.filtered.forEach(function (id) {
      var e = fonts.entries.get(id);
      var card = el('div', { className: 'gcard' + (id === S.fid ? ' sel' : ''), 'data-id': id, onclick: function () { selectFont(id); } }, [
        el('div', { className: 'meta' }, [el('span', { text: e.name + '  ·  ' + e.meta.category }), el('span', { className: 'dim', text: 'h' + e.meta.height })]),
        el('pre', { text: 'rendering…' })]);
      grid.appendChild(card);
      galleryObserver.observe(card);
    });
    stage.replaceChildren(grid);
    status('Gallery: ' + S.filtered.length + ' fonts · lazy background rendering' + (worker && workerReady ? ' (Web Worker)' : ' (main thread)'));
  }
  function renderCompare() {
    var stage = $('stage'), text = getText() || 'LeerBox', box = el('div', { className: 'gallery compare' });
    box.style.gridTemplateColumns = '1fr';
    if (!S.compare.length) { stage.replaceChildren(el('p', { className: 'note', style: 'padding:16px', text: 'No fonts in the compare set. Select a font and press “+ Compare” (up to 6).' })); return; }
    S.compare.forEach(function (id) {
      var e = fonts.entries.get(id); if (!e) return;
      var art, msg;
      try { art = engine.render(id, text, S.opts, S.effects); msg = art.width + ' cols × ' + art.height + ' rows'; } catch (err) { msg = 'error: ' + err.message; }
      box.appendChild(el('div', { className: 'gcard', onclick: function () { selectFont(id); } }, [
        el('div', { className: 'meta' }, [el('span', { text: e.name + ' (' + e.meta.category + ', ' + e.meta.source + ')' }), el('span', { text: msg })]),
        art ? artPre(art, 12) : null]));
    });
    box.appendChild(el('button', { text: 'Clear compare set', onclick: function () { S.compare = []; renderCompare(); } }));
    stage.replaceChildren(box);
  }

  // ------------------------------------------------------------------ modes & views
  function setMode(mode) {
    S.mode = mode;
    document.querySelectorAll('#modes button').forEach(function (b) { b.classList.toggle('on', b.dataset.mode === mode); });
    if (IS) IS.show(mode === 'image' || mode === 'animation' ? mode : 'text');
    if (mode === 'image' || mode === 'animation') { $('sizeInfo').textContent = ''; status(mode === 'image' ? 'Image-to-Art Studio' : 'Animation-to-Art Studio'); return; }
    document.querySelectorAll('#views button').forEach(function (b) { b.disabled = mode !== 'text'; });
    $('inputLabel').textContent = { text: 'YOUR TEXT', unicode: 'TEXT TO STYLE', image: 'IMAGE ART — open an image in the Tool tab', encode: 'TEXT TO ENCODE / DECODE', boxes: 'BOX / BANNER TEXT' }[mode];
    buildToolPanel();
    if (mode !== 'text') showTab('tool');
    requestRender(0);
  }
  function setView(view) {
    S.view = view;
    document.querySelectorAll('#views button').forEach(function (b) { b.classList.toggle('on', b.dataset.view === view); });
    requestRender(0);
  }
  function showTab(t) {
    document.querySelectorAll('#tabs button').forEach(function (b) { b.classList.toggle('on', b.dataset.tab === t); });
    ['layout', 'effects', 'export', 'info', 'tool'].forEach(function (k) { $('panel-' + k).hidden = k !== t; });
  }

  // ------------------------------------------------------------------ layout panel
  function field(label, input) { return [el('label', { text: label }), input]; }
  function sel(values, value, onchange) {
    var s = el('select', { onchange: function () { onchange(s.value); } });
    values.forEach(function (v) { var o = el('option', { value: v, text: v }); if (String(v) === String(value)) o.selected = true; s.appendChild(o); });
    return s;
  }
  function num(value, lo, hi, onchange, step) {
    var i = el('input', { type: 'number', value: value, min: lo, max: hi, step: step || 1 });
    i.addEventListener('input', function () { onchange(i.value); });
    return i;
  }
  function chk(label, value, onchange) {
    var i = el('input', { type: 'checkbox' }); i.checked = !!value;
    i.addEventListener('change', function () { onchange(i.checked); });
    return el('label', { style: 'grid-column:1/-1;display:flex;gap:6px;align-items:center' }, [i, label]);
  }
  var optInputs = {};
  function buildLayoutPanel() {
    var p = $('panel-layout'); p.replaceChildren();
    function setOpt(k) { return function (v) { var o = {}; o[k] = v; S.opts = LB.textOptions(Object.assign({}, S.opts, o)); requestRender(); saveSettings(); }; }
    function grid(nodes) { var g = el('div', { className: 'grid2' }); nodes.forEach(function (n) { (Array.isArray(n) ? n : [n]).forEach(function (x) { g.appendChild(x); }); }); return g; }
    var L = ['default', 'full', 'fitted', 'smush', 'universal'];
    optInputs = {
      h_layout: sel(L, S.opts.h_layout, setOpt('h_layout')), v_layout: sel(L, S.opts.v_layout, setOpt('v_layout')),
      align: sel(['left', 'center', 'right'], S.opts.align, setOpt('align')), direction: sel(['auto', 'ltr', 'rtl'], S.opts.direction, setOpt('direction')),
      width: num(S.opts.width, 0, 1000, setOpt('width')), letter_spacing: num(S.opts.letter_spacing, 0, 20, setOpt('letter_spacing')),
      line_spacing: num(S.opts.line_spacing, 0, 20, setOpt('line_spacing')), missing: sel(['skip', 'question', 'zero'], S.opts.missing, setOpt('missing')),
      raster_mode: sel(['block', 'half', 'quarter', 'braille', 'ascii', 'shade', 'dots', 'money', 'binary', 'at', 'star', 'custom'], S.opts.raster_mode, setOpt('raster_mode')),
      raster_scale: num(S.opts.raster_scale, 1, 6, setOpt('raster_scale')), raster_aspect: num(S.opts.raster_aspect, 1, 3, setOpt('raster_aspect')),
      digits: sel(['keep', 'western', 'arabic', 'persian'], S.opts.digits, setOpt('digits'))
    };
    var rc = el('input', { type: 'text', value: S.opts.raster_char, maxlength: 4, style: 'width:60px' });
    rc.addEventListener('input', function () { setOpt('raster_char')(rc.value); });
    p.append(el('h4', { text: 'FIGlet layout' }), grid([field('Horizontal', optInputs.h_layout), field('Vertical', optInputs.v_layout),
      field('Alignment', optInputs.align), field('Direction', optInputs.direction), field('Wrap width (0 = off)', optInputs.width),
      field('Letter spacing', optInputs.letter_spacing), field('Line spacing', optInputs.line_spacing), field('Missing chars', optInputs.missing),
      chk('Unicode fallback (é→e, case swap)', S.opts.fallback, setOpt('fallback'))]),
    el('h4', { text: 'Raster / Arabic fonts' }), grid([field('Pixel mapping', optInputs.raster_mode), field('Custom character', rc),
      field('Pixel scale', optInputs.raster_scale), field('Horizontal stretch', optInputs.raster_aspect), chk('Invert pixels', S.opts.raster_invert, setOpt('raster_invert'))]),
    el('h4', { text: 'Arabic engine' }), grid([chk('Contextual shaping', S.opts.arabic_shaping, setOpt('arabic_shaping')), chk('Lam-alef ligatures', S.opts.ligatures, setOpt('ligatures')),
      chk('Keep diacritics (harakat)', S.opts.diacritics, setOpt('diacritics')), field('Digits', optInputs.digits)]),
    el('p', { className: 'note', text: 'Raster Arabic fonts preserve visual appearance. The Unicode tab’s “visual text” keeps presentation forms for terminals that cannot shape Arabic (appearance preserved, semantics lost).' }));
    var cur = LB.smart.curatedDesigns(fonts);
    var curSel = sel(['— choose —'].concat(cur.map(function (d) { return d.name; })), '', function (v) {
      var d = cur.filter(function (x) { return x.name === v; })[0];
      if (d) { applyDesign(d.font, d.effects); status('Applied curated design “' + d.name + '”', 'ok'); }
    });
    var presetSel = sel(['— choose —'].concat(Object.keys(S.presets).sort()), '', function (v) {
      var pr = S.presets[v]; if (!pr) return;
      S.opts = LB.textOptions(pr.options); applyDesign(pr.font, LB.project.sanitizeEffects(pr.effects)); buildLayoutPanel(); status('Loaded preset “' + v + '”', 'ok');
    });
    p.append(el('h4', { text: 'Design presets' }), grid([field('Curated', curSel), field('My presets', presetSel)]),
      el('div', { className: 'row', style: 'margin-top:6px' }, [
        el('button', { text: 'Random design', onclick: randomDesign }),
        el('button', { text: 'Save preset…', onclick: function () {
          var n = prompt('Preset name:'); if (!n) return;
          S.presets[n.slice(0, 60)] = { font: S.fid, options: S.opts, effects: S.effects, export: S.exp }; saveSettings(); buildLayoutPanel(); status('Saved preset “' + n + '”', 'ok');
        } }),
        el('button', { text: 'Delete', onclick: function () { if (S.presets[presetSel.value]) { delete S.presets[presetSel.value]; saveSettings(); buildLayoutPanel(); } } })]));
  }
  function applyDesign(fid, effects) {
    S.effects = JSON.parse(JSON.stringify(effects)); S.fxSel = S.effects.length ? 0 : -1;
    buildEffectsPanel();
    selectFont(fonts.entries.has(fid) ? fid : S.fid);
  }
  function randomDesign() {
    var seed = Math.floor(Math.random() * 2147483647) + 1, d = LB.smart.randomDesign(fonts, seed);
    applyDesign(d.font, d.effects);
    status('Random design (seed ' + seed + '): ' + fonts.entries.get(d.font).name, 'ok');
  }

  // ------------------------------------------------------------------ effects panel
  var CHOICES = { mode: ['horizontal', 'vertical', 'diagonal', 'diagonal_up', 'radial'], target: ['fg', 'bg'], direction: ['se', 'sw', 'ne', 'nw', 's', 'e', 'n', 'w'],
    style: Object.keys(E.FRAMES), angle: [90, 180, 270] };
  var COLOR_KEYS = { fg: 1, bg: 1, color: 1, color1: 1, color2: 1 };
  var FLOAT_KEYS = { amount: 1, density: 1, saturation: 1, lightness: 1, offset: 1, cycles: 1, strength: 1 };
  function buildEffectsPanel() {
    var p = $('panel-effects'); p.replaceChildren();
    var addSel = el('select', { 'aria-label': 'Add effect' }), groups = { color: 'Colour', text: 'Text (plain-text safe)', graphic: 'Graphic only (HTML/SVG/PNG)' };
    addSel.appendChild(el('option', { value: '', text: '＋ Add effect…' }));
    Object.keys(groups).forEach(function (g) {
      var og = el('optgroup', { label: groups[g] });
      Object.keys(E.EFFECT_INFO).forEach(function (k) { if (E.EFFECT_INFO[k][0] === g) og.appendChild(el('option', { value: k, text: E.EFFECT_INFO[k][1] })); });
      addSel.appendChild(og);
    });
    addSel.addEventListener('change', function () { if (addSel.value) { S.effects.push(E.newEffect(addSel.value)); S.fxSel = S.effects.length - 1; buildEffectsPanel(); requestRender(); saveSettings(); } });
    var list = el('div', { className: 'fxlist', role: 'listbox' });
    S.effects.forEach(function (e, i) {
      var info = E.EFFECT_INFO[e.type];
      list.appendChild(el('div', { className: 'fx' + (i === S.fxSel ? ' sel' : '') + (e.enabled === false ? ' off' : ''), onclick: function () { S.fxSel = i; buildEffectsPanel(); },
        ondblclick: function () { e.enabled = e.enabled === false; buildEffectsPanel(); requestRender(); } },
        [el('span', { text: e.enabled === false ? '○' : '●' }), el('span', { text: info[1] }), el('span', { className: 'k', text: { color: 'colour', text: 'text', graphic: 'graphic' }[info[0]] })]));
    });
    if (!S.effects.length) list.appendChild(el('div', { className: 'note', style: 'padding:8px', text: 'No effects yet. Add one above.' }));
    function mv(d) { var i = S.fxSel; if (i < 0 || i + d < 0 || i + d >= S.effects.length) return; var t = S.effects[i]; S.effects[i] = S.effects[i + d]; S.effects[i + d] = t; S.fxSel = i + d; buildEffectsPanel(); requestRender(); }
    var rep = E.pipelineRepresentation(S.effects);
    p.append(el('h4', { text: 'Effects pipeline (top → bottom)' }), addSel, list,
      el('div', { className: 'row' }, [el('button', { text: '▲', onclick: function () { mv(-1); } }), el('button', { text: '▼', onclick: function () { mv(1); } }),
        el('button', { text: 'On/Off', onclick: function () { var e = S.effects[S.fxSel]; if (e) { e.enabled = e.enabled === false; buildEffectsPanel(); requestRender(); } } }),
        el('button', { text: 'Remove', onclick: function () { if (S.fxSel >= 0) { S.effects.splice(S.fxSel, 1); S.fxSel = Math.min(S.fxSel, S.effects.length - 1); buildEffectsPanel(); requestRender(); saveSettings(); } } })]),
      el('p', { className: 'note', text: rep.lossyInText.length ? 'Not representable in plain text: ' + rep.lossyInText.join(', ') + '. These survive in ANSI/HTML/SVG/PNG exports.' : (S.effects.length ? 'All enabled effects are plain-text safe.' : '') }));
    var e = S.effects[S.fxSel];
    if (!e) return;
    var g = el('div', { className: 'grid2' });
    Object.keys(E.DEFAULTS[e.type]).forEach(function (k) {
      var dv = E.DEFAULTS[e.type][k], v = e[k], input;
      var set = function (val) { e[k] = val; requestRender(); saveSettings(); };
      if (COLOR_KEYS[k]) {
        var txt = el('input', { type: 'text', value: v || '', style: 'width:90px' }), pick = el('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(v) ? v : '#7c8cff' });
        txt.addEventListener('input', function () { var s = txt.value.trim(); if (!s) return set(''); try { LB.color.hexToRgb(s); pick.value = s.charAt(0) === '#' ? s : '#' + s; set(s); } catch (err) { /* wait for valid input */ } });
        pick.addEventListener('input', function () { txt.value = pick.value; set(pick.value); });
        input = el('div', { className: 'row' }, [txt, pick]);
      } else if (k === 'stops') {
        input = el('input', { type: 'text', value: v.join(', ') });
        input.addEventListener('input', function () {
          var parts = input.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
          try { parts.forEach(LB.color.hexToRgb); if (parts.length) set(parts); } catch (err) { /* incomplete */ }
        });
      } else if (CHOICES[k]) input = sel(CHOICES[k], v, function (val) { set(k === 'angle' ? +val : val); });
      else if (typeof dv === 'boolean') { input = el('input', { type: 'checkbox' }); input.checked = !!v; input.addEventListener('change', function () { set(input.checked); }); }
      else if (typeof dv === 'number') {
        var isFloat = FLOAT_KEYS[k] === 1;
        input = num(v, -50, 500, function (val) { var n = parseFloat(val); if (!isNaN(n)) set(isFloat ? n : Math.round(n)); }, isFloat ? 0.05 : 1);
      }
      else { input = el('input', { type: 'text', value: v }); input.addEventListener('input', function () { set(input.value); }); }
      g.append(el('label', { text: k.replace(/_/g, ' ') }), input);
    });
    var kind = E.EFFECT_INFO[e.type][0];
    p.append(el('h4', { text: 'Parameters — ' + E.EFFECT_INFO[e.type][1] }), g,
      el('p', { className: 'note', text: { text: 'Plain-text effect: preserved in every export.', color: 'Colour effect: preserved in ANSI, HTML, SVG and image exports.', graphic: 'Graphical effect: only HTML, SVG and image exports.' }[kind] }));
  }

  // ------------------------------------------------------------------ export panel
  function buildExportPanel() {
    var p = $('panel-export'); p.replaceChildren();
    var fmtSel = el('select');
    Object.keys(X.FORMATS).forEach(function (k) { var o = el('option', { value: k, text: k + ' — ' + X.FORMATS[k][0] }); if (k === 'png') o.selected = true; fmtSel.appendChild(o); });
    function sf(k, w) { var i = el('input', { type: 'text', value: S.exp[k], style: 'width:' + (w || 90) + 'px' }); i.addEventListener('input', function () { var o = {}; o[k] = i.value; S.exp = X.settings(Object.assign({}, S.exp, o)); saveSettings(); }); return i; }
    function sc(k, label) { return chk(label, S.exp[k], function (v) { var o = {}; o[k] = v; S.exp = X.settings(Object.assign({}, S.exp, o)); saveSettings(); }); }
    var ansiSel = sel(['truecolor', '256', '16', 'none'], S.exp.ansi_mode, function (v) { S.exp = X.settings(Object.assign({}, S.exp, { ansi_mode: v })); saveSettings(); });
    var codeSel = sel(Object.keys(X.CODE_LANGS), 'python', function () { });
    var g = el('div', { className: 'grid2' });
    [['Font size (px)', sf('font_size')], ['Scale (resolution ×)', sf('scale')], ['Padding (px)', sf('padding')], ['Line height', sf('line_height')],
      ['Background', sf('background')], ['Default text colour', sf('foreground')], ['JPEG/WebP quality', sf('jpeg_quality')], ['ANSI colours', ansiSel]].forEach(function (f) { g.append(el('label', { text: f[0] }), f[1]); });
    g.append(sc('transparent', 'Transparent background (PNG, WebP, SVG, HTML)'), sc('embed_font', 'Embed DejaVu Sans Mono in HTML/SVG'));
    var scope = sel(['Favorites', 'Compare set', 'Current filter'], 'Favorites', function () { });
    var bfmt = el('input', { type: 'text', value: 'txt,png' });
    p.append(el('h4', { text: 'Format' }), fmtSel, el('div', { className: 'row', style: 'margin:6px 0' }, [el('button', { className: 'primary', text: 'Export / download', onclick: function () { exportCurrent(fmtSel.value); } })]),
      el('h4', { text: 'Graphics settings' }), g,
      el('h4', { text: 'Clipboard' }), el('div', { className: 'actions', style: 'grid-template-columns:1fr 1fr' }, [
        el('button', { text: 'Copy text', onclick: function () { if (S.art) copyText(X.toTxt(S.art), 'text'); } }),
        el('button', { text: 'Copy ANSI', onclick: function () { if (S.art) copyText(X.toAnsi(S.art, S.exp.ansi_mode), 'ANSI text'); } }),
        el('button', { text: 'Copy HTML', onclick: function () { if (S.art) copyHtml(X.toHtmlFragment(S.art, S.exp), X.toTxt(S.art)); } }),
        el('button', { text: 'Copy Markdown', onclick: function () { if (S.art) copyText(X.toMarkdown(S.art), 'Markdown'); } })]),
      el('div', { className: 'grid2', style: 'margin-top:6px' }, [el('label', { text: 'Source code' }), codeSel]),
      el('button', { text: 'Copy as escaped source code', style: 'width:100%;margin-top:4px', onclick: function () { if (S.art) copyText(X.toCode(S.art, codeSel.value), X.CODE_LANGS[codeSel.value] + ' source'); } }),
      el('h4', { text: 'Batch export (downloads one ZIP)' }), el('div', { className: 'grid2' }, [el('label', { text: 'Fonts' }), scope, el('label', { text: 'Formats' }), bfmt]),
      el('button', { text: 'Batch export…', style: 'width:100%;margin-top:6px', onclick: function () { batchExport(scope.value, bfmt.value); } }));
  }
  function projectNow() { var e = fonts.entries.get(S.fid); return LB.project.makeProject(getText(), S.fid, e ? e.name : '', S.opts, S.effects, S.exp, { mode: S.mode }); }
  async function exportCurrent(fmt) {
    if (!S.art && fmt !== 'json') return status('Nothing to export yet', 'warn');
    try {
      var blob = await X.exportBlob(S.art, fmt, S.exp, projectNow());
      var base = S.mode === 'text' ? (fonts.entries.get(S.fid).meta.name || 'art') : S.mode;
      download(blob, 'LeerBox_' + base.replace(/[^A-Za-z0-9_-]/g, '_') + X.FORMATS[fmt][1]);
      status('Exported ' + X.FORMATS[fmt][0] + ' (' + blob.size.toLocaleString() + ' bytes)', 'ok');
    } catch (err) { status('Export failed: ' + err.message, 'err'); }
  }
  async function batchExport(scope, fmts) {
    var ids = scope === 'Favorites' ? S.favorites.filter(function (f) { return fonts.entries.has(f); }) : scope === 'Compare set' ? S.compare.slice() : S.filtered.slice();
    var list = fmts.split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
    var bad = list.filter(function (f) { return !X.FORMATS[f] || f === 'json'; });
    if (bad.length || !list.length) return status('Unknown formats: ' + (bad.join(', ') || '(none)'), 'err');
    if (!ids.length) return status('No fonts in “' + scope + '”', 'warn');
    if (ids.length * list.length > 2000) return status('Too many files (limit 2000) — narrow the filter', 'err');
    var files = [], errors = [], text = getText() || 'LeerBox', enc = new TextEncoder();
    for (var i = 0; i < ids.length; i++) {
      var e = fonts.entries.get(ids[i]), safe = (e.meta.name || e.name).replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 60), art;
      status('Batch export ' + (i + 1) + '/' + ids.length + '…');
      try { art = engine.render(ids[i], text, S.opts, S.effects); } catch (err) { errors.push(e.name + ': ' + err.message); continue; }
      for (var j = 0; j < list.length; j++) {
        try { var b = await X.exportBlob(art, list[j], S.exp); files.push({ name: ('00' + (i + 1)).slice(-3) + '_' + safe + X.FORMATS[list[j]][1], data: new Uint8Array(await b.arrayBuffer()) }); }
        catch (err) { errors.push(e.name + ' [' + list[j] + ']: ' + err.message); }
      }
      if (i % 10 === 9) await new Promise(function (r) { setTimeout(r, 0); });
    }
    files.push({ name: 'batch_manifest.json', data: enc.encode(JSON.stringify({ text: text, files: files.map(function (f) { return f.name; }), errors: errors }, null, 1)) });
    download(LB.zipWrite(files), 'LeerBox_batch.zip');
    status('Batch export: ' + (files.length - 1) + ' files' + (errors.length ? ', ' + errors.length + ' errors (see batch_manifest.json)' : ''), errors.length ? 'warn' : 'ok');
  }

  // ------------------------------------------------------------------ info panel & recommendations
  function renderInfo() {
    var e = fonts.entries.get(S.fid); if (!e) return;
    var m = e.meta, cov = m.coverage || {}, p = $('panel-info');
    var rows = [['Font', e.name], ['Type', m.format + (e.type === 'raster' ? ' — raster typography (bitmap rasterized from a TTF)' : ' — genuine FIGlet/TOIlet font')],
      ['Category', m.category], ['Tags', (m.tags || []).join(', ')], ['Height', m.height + ' rows'], ['Layout bits', String(m.layout)],
      ['Direction', m.direction ? 'RTL' : 'LTR'], ['Source', m.source + ' ' + (m.repo || '')], ['Author', m.author || 'not stated in font file'],
      ['License', m.license + ' [' + m.licenseTier + ']'], ['Glyphs', String(cov.glyphs || '?') + (cov.upper !== undefined ? '  (A–Z ' + cov.upper + '/26, a–z ' + cov.lower + '/26, digits ' + cov.digits + '/10)' : '')]];
    if (m.aliases && m.aliases.length) rows.push(['Duplicates merged', String(m.aliases.length)]);
    if (S.art && S.mode === 'text') { rows.push(['Output', S.art.width + ' cols × ' + S.art.height + ' rows']); var bad = engine.unsupportedChars(S.fid, getText()); if (bad.length) rows.push(['Unsupported', bad.slice(0, 30).join(' ')]); }
    var tbl = el('div', { className: 'grid2', style: 'align-items:start' });
    rows.forEach(function (r) { tbl.append(el('label', { text: r[0] }), el('div', { text: r[1], style: 'word-break:break-word' })); });
    var target = sel(['terminal', 'wide', 'compact', 'banner'], S.recTarget || 'terminal', function (v) { S.recTarget = v; });
    p.replaceChildren(el('h4', { text: 'Font information' }), tbl, el('h4', { text: 'Smart recommendations' }),
      el('div', { className: 'row' }, [target, el('button', { text: 'Recommend fonts', onclick: function () { recommend(target.value); } })]),
      el('div', { id: 'recList' }), el('p', { className: 'note', text: 'Deterministic scoring of rendered width/height against the target (see README › Smart features). Fonts that cannot draw every character are excluded.' }));
  }
  function recommend(target) {
    S.recTarget = target;
    var text = getText() || 'LeerBox', gen = ++S.recGen;
    var ids = LB.arabic.containsArabic(text) ? fonts.order.filter(function (i) { return fonts.entries.get(i).meta.category === 'Arabic'; })
      : fonts.order.filter(function (i) { var t = fonts.entries.get(i).type; return t === 'figlet' || t === 'toilet'; });
    status('Scoring ' + ids.length + ' fonts for “' + target + '”…');
    var builtin = ids.filter(function (i) { return fonts.entries.get(i).builtin; });
    if (worker && workerReady) { S.recTarget = target; worker.postMessage({ type: 'recommend', gen: gen, ids: builtin, text: text, target: target }); return; }
    var out = [], k = 0;
    (function chunk() {
      if (gen !== S.recGen) return;
      var end = Math.min(ids.length, k + 40);
      for (; k < end; k++) {
        try { if (engine.unsupportedChars(ids[k], text).length) continue; var a = engine.render(ids[k], text, {}, []); out.push({ id: ids[k], width: a.width, height: a.height, score: LB.smart.score(a.width, a.height, target, cps(text).length) }); } catch (err) { /* skip */ }
      }
      if (k < ids.length) setTimeout(chunk, 0); else showRecommendations(gen, out);
    })();
  }
  function showRecommendations(gen, results) {
    if (gen !== S.recGen) return;
    results.sort(function (a, b) { var na = fonts.entries.get(a.id).name.toLowerCase(), nb = fonts.entries.get(b.id).name.toLowerCase(); return b.score - a.score || (na < nb ? -1 : na > nb ? 1 : 0); });
    var box = $('recList'); if (!box) return;
    box.replaceChildren.apply(box, results.slice(0, 25).map(function (r) {
      return el('div', { className: 'rec', onclick: function () { selectFont(r.id); } }, [el('span', { text: fonts.entries.get(r.id).name }), el('span', { className: 'muted', text: r.width + ' × ' + r.height })]);
    }));
    status(Math.min(25, results.length) + ' recommendations (deterministic)', 'ok');
  }

  // ------------------------------------------------------------------ tool panel (per mode)
  function buildToolPanel() {
    var p = $('panel-tool'); p.replaceChildren();
    var T = S.tool;
    function tsel(k, vals, dv) { if (T[k] === undefined) T[k] = dv; return sel(vals, T[k], function (v) { T[k] = v; requestRender(); }); }
    function tnum(k, dv, lo, hi, step) { if (T[k] === undefined) T[k] = dv; return num(T[k], lo, hi, function (v) { T[k] = v; requestRender(); }, step); }
    function ttxt(k, dv) { if (T[k] === undefined) T[k] = dv; var i = el('input', { type: 'text', value: T[k] }); i.addEventListener('input', function () { T[k] = i.value; requestRender(); }); return i; }
    var g = el('div', { className: 'grid2' });
    if (S.mode === 'image') {
      [['Width (columns)', tnum('cols', 100, 4, 1000)], ['Mode', tsel('imode', ['ascii', 'blocks', 'half', 'quarter', 'braille'], 'ascii')],
        ['Character ramp', tsel('ramp', Object.keys(LB.imageart.RAMPS), 'standard')], ['Custom ramp', ttxt('customRamp', '')],
        ['Brightness (−1…1)', tnum('brightness', 0, -1, 1, 0.05)], ['Contrast (0…3)', tnum('contrast', 1, 0, 3, 0.05)], ['Gamma', tnum('gamma', 1, 0.2, 5, 0.05)],
        ['Dithering', tsel('dither', ['none', 'floyd', 'atkinson', 'ordered'], 'none')], ['Colour', tsel('color', ['none', 'truecolor'], 'none')],
        ['Threshold (1-bit)', tnum('threshold', 0.5, 0, 1, 0.05)], ['Cell aspect', tnum('aspect', 0.5, 0.2, 2, 0.05)]].forEach(function (f) { g.append(el('label', { text: f[0] }), f[1]); });
      g.append(chk('Invert', T.invert, function (v) { T.invert = v; requestRender(); }));
      p.append(el('h4', { text: 'Image → ASCII / Unicode / ANSI' }), el('button', { className: 'primary', text: 'Open image…', style: 'width:100%', onclick: function () { $('fileImage').click(); } }), g,
        el('p', { className: 'note', text: 'Images are decoded and converted locally in your browser; nothing is uploaded. Use the Export tab for TXT/ANSI/HTML/PNG output.' }));
    } else if (S.mode === 'encode') {
      g.append(el('label', { text: 'Encoding' }), tsel('enc', Object.keys(LB.unicode.ENCODINGS), 'binary'));
      g.append(chk('Decode instead of encode (binary, hex, morse, base64)', T.decode, function (v) { T.decode = v; requestRender(); }));
      p.append(el('h4', { text: 'Encoders' }), g);
    } else if (S.mode === 'boxes') {
      [['Generator', tsel('kind', ['Decorative text box', 'Terminal banner', 'GitHub README banner', 'CLI application header'], 'Decorative text box')],
        ['Box style', tsel('style', Object.keys(LB.unicode.BOX_STYLES), 'rounded')], ['Alignment', tsel('align', ['left', 'center', 'right'], 'center')],
        ['Padding', tnum('padding', 1, 0, 10)], ['Title', ttxt('title', '')], ['Header language', tsel('lang', Object.keys(X.CODE_LANGS), 'python')]].forEach(function (f) { g.append(el('label', { text: f[0] }), f[1]); });
      p.append(el('h4', { text: 'Boxes, banners & headers' }), g, el('p', { className: 'note', text: 'Banners and headers use the font, layout and effects selected for Text Art.' }));
    } else if (S.mode === 'unicode') {
      p.append(el('h4', { text: 'Unicode styles' }), el('p', { className: 'note', text: 'Algorithmic styles substitute Unicode characters (Mathematical Alphanumeric Symbols, enclosed and full-width forms). They are not fonts and are counted separately. Click a row to copy it. For Arabic input an extra row shows visual-order presentation forms for terminals that cannot shape Arabic.' }));
    } else p.append(el('p', { className: 'note', text: 'Tools for the current mode appear here.' }));
  }
  function imageOpts() {
    var T = S.tool;
    return { cols: +T.cols || 100, mode: T.imode || 'ascii', ramp: T.customRamp || T.ramp || 'standard', brightness: +T.brightness || 0,
      contrast: T.contrast === undefined ? 1 : +T.contrast, gamma: Math.max(0.2, Math.min(5, +T.gamma || 1)), invert: !!T.invert, dither: T.dither || 'none',
      color: T.color || 'none', threshold: T.threshold === undefined ? 0.5 : +T.threshold, aspect: +T.aspect || 0.5 };
  }
  function renderUnicode(text) {
    var line = text.replace(/\n/g, ' ').slice(0, 500), tbl = el('table', { className: 'uni' }), U = LB.unicode;
    if (LB.arabic.containsArabic(line)) tbl.appendChild(uniRow('Arabic visual text (terminals)', LB.arabic.visualText(line)));
    Object.keys(U.STYLE_NAMES).forEach(function (k) { try { tbl.appendChild(uniRow(U.STYLE_NAMES[k], U.stylize(line, k))); } catch (err) { /* skip */ } });
    $('stage').replaceChildren(tbl);
    S.art = LB.Art.fromText(Object.keys(U.STYLE_NAMES).map(function (k) { return U.STYLE_NAMES[k] + ': ' + U.stylize(line, k); }).join('\n'));
    status('Click a row to copy it.');
  }
  function uniRow(name, val) { return el('tr', { onclick: function () { copyText(val, name); } }, [el('td', { text: name }), el('td', { text: val })]); }
  function renderEncode(text) {
    var T = S.tool, kind = T.enc || 'binary', out;
    try { out = T.decode ? LB.unicode.decode(text, kind) : LB.unicode.encode(text, kind); status(LB.unicode.ENCODINGS[kind] + (T.decode ? ' decoded' : ' encoded')); }
    catch (err) { out = ''; status('Cannot ' + (T.decode ? 'decode' : 'encode') + ': ' + err.message, 'err'); }
    var wrapped = out.split('\n').map(function (l) { var a = cps(l), r = []; for (var i = 0; i < a.length; i += 100) r.push(a.slice(i, i + 100).join('')); return r.join('\n'); }).join('\n');
    S.art = LB.Art.fromText(wrapped);
    $('stage').replaceChildren(artPre(S.art));
  }
  function makeBox(text) {
    var T = S.tool, kind = T.kind || 'Decorative text box', pad = Math.max(0, Math.min(10, parseInt(T.padding === undefined ? 1 : T.padding, 10) || 0));
    if (kind === 'Decorative text box') return LB.Art.fromText(LB.unicode.textBox(text, T.style || 'rounded', pad, T.align || 'center', T.title || ''));
    var art = engine.render(S.fid, text, S.opts, S.effects);
    if (kind === 'Terminal banner') return LB.Art.fromText(LB.unicode.textBox(art.toText(), T.style || 'rounded', pad, T.align || 'center', T.title || ''));
    if (kind === 'GitHub README banner') return LB.Art.fromText(X.toMarkdown(art, T.title || ''));
    return LB.Art.fromText(X.toCode(art, T.lang || 'python', 'BANNER'));
  }

  // ------------------------------------------------------------------ files: fonts, zip, images, projects
  async function importFontFiles(files) {
    var results = [];
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      if (f.size > 6 * 1024 * 1024) { results.push({ ok: false, file: f.name, error: 'file too large' }); continue; }
      results.push(await fonts.importBytes(new Uint8Array(await f.arrayBuffer()), f.name));
    }
    afterImport(results);
  }
  async function importZipFile(f) {
    if (f.size > 64 * 1024 * 1024) return afterImport([{ ok: false, file: f.name, error: 'archive larger than 64 MB' }]);
    afterImport(await fonts.importZip(new Uint8Array(await f.arrayBuffer())));
  }
  function afterImport(results) {
    var ok = results.filter(function (r) { return r.ok; }), bad = results.filter(function (r) { return !r.ok; });
    ok.forEach(function (r) {
      dbTx('readwrite', function (st) { return st.put({ id: r.id, name: r.file, text: r.text }); });
      if (worker) worker.postMessage({ type: 'addFont', name: r.file, text: r.text });
    });
    var msg = 'Imported ' + ok.length + ' font(s).' + (bad.length ? ' ' + bad.length + ' skipped.' : '');
    if (bad.length) dialog([el('h3', { text: 'Font import' }), el('p', { text: msg }), el('ul', {}, bad.slice(0, 40).map(function (r) { return el('li', { text: r.file + ': ' + r.error }); }))]);
    if (ok.length) { setScope('Imported'); selectFont(ok[ok.length - 1].id); }
    status(msg, ok.length ? 'ok' : 'warn');
  }
  function manageFonts() {
    var ids = fonts.order.filter(function (f) { return !fonts.entries.get(f).builtin; });
    var list = el('div', { style: 'max-height:260px;overflow:auto' }, ids.map(function (id) {
      return el('div', { className: 'rec' }, [el('span', { text: fonts.entries.get(id).name }), el('button', { text: 'Remove', onclick: function () { removeFont(id); manageFonts(); } })]);
    }));
    function exportColl(scope) {
      var sel2 = scope === 'favorites' ? S.favorites : scope === 'filter' ? S.filtered : ids, r = fonts.exportCollection(sel2);
      download(r.blob, 'leerbox_fonts_' + scope + '.zip'); status('Exported ' + r.count + ' fonts', 'ok');
    }
    dialog([el('h3', { text: 'Font management' }), el('p', { className: 'note', text: ids.length + ' imported font(s), stored locally in this browser (IndexedDB).' }), list,
      el('div', { className: 'row', style: 'flex-wrap:wrap;margin-top:10px' }, [
        el('button', { text: 'Reset imports', onclick: function () { if (confirm('Remove ALL imported fonts from this browser?')) { ids.forEach(removeFont); manageFonts(); } } }),
        el('button', { text: 'Export favorites (ZIP)', onclick: function () { exportColl('favorites'); } }),
        el('button', { text: 'Export current filter (ZIP)', onclick: function () { exportColl('filter'); } }),
        el('button', { text: 'Export imported (ZIP)', onclick: function () { exportColl('imported'); } })])]);
  }
  function removeFont(id) {
    fonts.removeUser(id); dbTx('readwrite', function (st) { return st.delete(id); });
    if (worker) worker.postMessage({ type: 'removeFont', id: id });
    if (S.fid === id) S.fid = 'fig:standard';
    refreshFonts();
  }
  function loadImageFile(f) {
    if (f.size > 60 * 1024 * 1024) return status('Image larger than 60 MB', 'err');
    var url = URL.createObjectURL(f), img = new Image();
    img.onload = function () {
      var w = img.naturalWidth, h = img.naturalHeight, k = Math.min(1, 1600 / Math.max(w, h));
      var c = el('canvas'); c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(h * k));
      var ctx = c.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(img, 0, 0, c.width, c.height);
      var d = ctx.getImageData(0, 0, c.width, c.height).data, px = new Int32Array(c.width * c.height);
      for (var i = 0; i < px.length; i++) px[i] = (d[i * 4] << 16) | (d[i * 4 + 1] << 8) | d[i * 4 + 2];
      S.image = { width: c.width, height: c.height, pixels: px };
      URL.revokeObjectURL(url);
      if (S.mode !== 'image') setMode('image'); else requestRender(0);
      status('Loaded ' + f.name + ' (' + w + '×' + h + ') — processed locally', 'ok');
    };
    img.onerror = function () { URL.revokeObjectURL(url); status('Could not decode image ' + f.name, 'err'); };
    img.src = url;
  }
  async function loadProjectFile(f) {
    try {
      if (f.size > 40 * 1024 * 1024) throw new Error('project file too large');
      var txt = await f.text();
      if (IS && /"leerbox-image-project"/.test(txt.slice(0, 200))) { setMode('image'); IS.openProject(f); return; }
      if (f.size > 8 * 1024 * 1024) throw new Error('project file too large');
      applyProject(LB.project.parseProject(txt));
      status('Opened project ' + f.name, 'ok');
    } catch (err) { status('Open project failed: ' + err.message, 'err'); }
  }
  function applyProject(pr) {
    $('text').value = pr.text; S.opts = pr.options; S.exp = X.settings(Object.assign({}, S.exp, pr.export));
    var fid = pr.font.id;
    if (!fonts.entries.has(fid)) {
      var m = fonts.order.filter(function (i) { return fonts.entries.get(i).name === pr.font.name; });
      fid = m.length ? m[0] : S.fid;
      if (!m.length) status('Font “' + pr.font.name + '” not available; kept current font.', 'warn');
    }
    buildLayoutPanel(); buildExportPanel();
    applyDesign(fid, pr.effects);
  }
  function setScope(s) {
    S.scope = s;
    document.querySelectorAll('#scopes button').forEach(function (b) { b.classList.toggle('on', b.dataset.scope === s); });
    refreshFonts();
  }

  // ------------------------------------------------------------------ fullscreen, zoom, about
  function setZoom(z, manual) { if (manual) { S.autofit = false; $('optAutofit').checked = false; } S.zoom = Math.max(0.3, Math.min(4, z)); requestRender(0); saveSettings(); }
  function fullscreen() {
    if (!S.art) return;
    var host = $('fullHost'), art = S.art, cwf = window.innerWidth - 80, chf = window.innerHeight - 80;
    var fs = Math.max(4, Math.min(48, Math.floor(Math.min(cwf / Math.max(1, art.width * 0.6021), chf / Math.max(1, art.height * 1.2)))));
    var c = el('canvas', { className: 'art' });
    try { X.renderCanvas(art, { font_size: fs, padding: 40, background: '#0b0d12', foreground: '#e6e9ef' }, c); host.replaceChildren(c); }
    catch (err) { host.replaceChildren(artPre(art, fs)); }
    $('fullscreen').classList.add('on');
  }
  function about() {
    var st = fonts.stats(), clear = 0, arabic = 0;
    fonts.entries.forEach(function (e) { if ((e.type === 'figlet' || e.type === 'toilet') && e.meta.licenseTier === 'clear') clear++; if (e.meta.category === 'Arabic') arabic++; });
    dialog([el('h3', { text: 'LeerBox Text Art Studio 3.0 — Ultimate Edition' }), el('p', { text: 'Local-first and offline: no network requests, no analytics, no tracking (enforced by a Content-Security-Policy).' }),
      el('ul', {}, ['Genuine FIGlet/TOIlet fonts: ' + st.genuine + ' (' + clear + ' with explicit license terms)', 'Arabic raster fonts (OFL): ' + arabic,
        'Raster typography designs: ' + (st.raster - arabic), 'Algorithmic Unicode styles: ' + Object.keys(LB.unicode.STYLE_NAMES).length, 'Imported fonts: ' + st.imported,
        'Background rendering: ' + (worker && workerReady ? 'Web Worker' : 'main thread (worker unavailable)'),
        'Decompression: ' + (typeof DecompressionStream !== 'undefined' ? 'native DecompressionStream' : 'built-in JS inflate')].map(function (t) { return el('li', { text: t }); })),
      el('p', { className: 'note', text: 'Per-font source, author and license are in Info and in FONT_MANIFEST.json; third-party notices in THIRD_PARTY_LICENSES.txt.' })]);
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    $('text').addEventListener('input', function () {
      var t = $('text').value;
      $('charCount').textContent = cps(t).length + ' chars' + (LB.arabic.containsArabic(t) ? ' · Arabic detected' : '');
      if (t.length > 5000) status('Input is limited to 5000 characters; extra text is ignored.', 'warn');
      requestRender(); debounce('save', saveSettings, 800);
    });
    $('search').addEventListener('input', function () { debounce('search', refreshFonts, 120); });
    ['fCat', 'fKind', 'fSrc', 'fClear'].forEach(function (id) { $(id).addEventListener('change', refreshFonts); });
    ['fHmin', 'fHmax'].forEach(function (id) { $(id).addEventListener('input', function () { debounce('search', refreshFonts, 150); }); });
    $('scopes').addEventListener('click', function (e) { if (e.target.dataset.scope) setScope(e.target.dataset.scope); });
    $('fontList').addEventListener('scroll', function () { paintFontList(false); });
    $('fontList').addEventListener('click', function (e) { var it = e.target.closest('.item'); if (it) selectFont(it.dataset.id); });
    $('fontList').addEventListener('dblclick', function (e) { if (e.target.closest('.item')) toggleFav(); });
    $('fontList').addEventListener('keydown', function (e) {
      var i = S.filtered.indexOf(S.fid);
      if (e.key === 'ArrowDown' && i < S.filtered.length - 1) { selectFont(S.filtered[i + 1]); e.preventDefault(); }
      if (e.key === 'ArrowUp' && i > 0) { selectFont(S.filtered[i - 1]); e.preventDefault(); }
    });
    $('modes').addEventListener('click', function (e) { if (e.target.dataset.mode) setMode(e.target.dataset.mode); });
    $('views').addEventListener('click', function (e) { if (e.target.dataset.view && S.mode === 'text') setView(e.target.dataset.view); });
    $('tabs').addEventListener('click', function (e) { if (e.target.dataset.tab) showTab(e.target.dataset.tab); });
    $('btnFav').onclick = toggleFav;
    $('btnRandom').onclick = function () { if (S.filtered.length) selectFont(S.filtered[Math.floor(Math.random() * S.filtered.length)]); };
    $('btnCompareAdd').onclick = function () { if (S.compare.indexOf(S.fid) < 0) S.compare.push(S.fid); S.compare = S.compare.slice(-6); status('Compare set: ' + S.compare.length + ' font(s)', 'ok'); if (S.view === 'compare') renderCompare(); };
    $('btnImport').onclick = function () { $('fileFonts').click(); };
    $('btnImportZip').onclick = function () { $('fileZip').click(); };
    $('btnManage').onclick = manageFonts;
    $('fileFonts').onchange = function () { importFontFiles(Array.from(this.files)); this.value = ''; };
    $('fileZip').onchange = function () { if (this.files[0]) importZipFile(this.files[0]); this.value = ''; };
    $('fileImage').onchange = function () { if (this.files[0]) loadImageFile(this.files[0]); this.value = ''; };
    $('fileProject').onchange = function () { if (this.files[0]) loadProjectFile(this.files[0]); this.value = ''; };
    $('btnOpenProject').onclick = function () { $('fileProject').click(); };
    $('btnSaveProject').onclick = function () { download(new Blob([JSON.stringify(projectNow(), null, 1)], { type: 'application/json' }), 'design.leerbox.json'); status('Project saved', 'ok'); };
    $('btnAbout').onclick = about;
    $('btnCopy').onclick = function () { if (S.art) copyText(X.toTxt(S.art), 'text'); };
    $('optGraphic').onchange = function () { S.graphic = this.checked; requestRender(0); saveSettings(); };
    $('optAutofit').onchange = function () { S.autofit = this.checked; requestRender(0); saveSettings(); };
    $('btnZoomIn').onclick = function () { setZoom(S.zoomEff * 1.15, true); };
    $('btnZoomOut').onclick = function () { setZoom(S.zoomEff / 1.15, true); };
    $('btnFit').onclick = function () { S.autofit = true; $('optAutofit').checked = true; S.zoom = 1.6; requestRender(0); };
    $('btnFull').onclick = fullscreen;
    $('btnFullClose').onclick = function () { $('fullscreen').classList.remove('on'); };
    $('dlgClose').onclick = function () { $('dlg').close ? $('dlg').close() : $('dlg').removeAttribute('open'); };
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') $('fullscreen').classList.remove('on');
      if (e.key === 'F11' && S.art) { e.preventDefault(); fullscreen(); }
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); $('btnSaveProject').click(); }
      if ((e.ctrlKey || e.metaKey) && e.key === 'o') { e.preventDefault(); $('fileProject').click(); }
    });
    window.addEventListener('resize', function () { debounce('resize', function () { paintFontList(false); if (S.view === 'preview') requestRender(0); }, 150); });
    var dz = $('dropzone'), depth = 0;
    document.addEventListener('dragenter', function (e) { e.preventDefault(); depth++; dz.classList.add('on'); });
    document.addEventListener('dragleave', function () { if (--depth <= 0) { depth = 0; dz.classList.remove('on'); } });
    document.addEventListener('dragover', function (e) { e.preventDefault(); });
    document.addEventListener('drop', function (e) {
      e.preventDefault(); depth = 0; dz.classList.remove('on');
      var files = Array.from(e.dataTransfer.files || []), fontsF = files.filter(function (f) { return /\.(flf|tlf)$/i.test(f.name); });
      if (fontsF.length) importFontFiles(fontsF);
      files.forEach(function (f) {
        if (/\.zip$/i.test(f.name)) importZipFile(f);
        else if (/\.json$/i.test(f.name)) loadProjectFile(f);
        else if (IS && (/^video\//.test(f.type) || (S.mode === 'animation' && /\.gif$/i.test(f.name)))) { setMode('animation'); IS.openAnim(f); }
        else if (IS && (/^image\//.test(f.type) || /\.(tiff?|svg|ico|avif|heic|heif)$/i.test(f.name))) { setMode('image'); IS.addFile(f); }
        else if (/^image\//.test(f.type)) loadImageFile(f);
      });
    });
  }
  function toggleFav() {
    var i = S.favorites.indexOf(S.fid);
    if (i >= 0) S.favorites.splice(i, 1); else S.favorites.push(S.fid);
    status((i >= 0 ? 'Removed from' : 'Added to') + ' favorites: ' + fonts.entries.get(S.fid).name, 'ok');
    saveSettings(); refreshFonts();
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    var t0 = performance.now();
    LB.resources = { arabicTables: JSON.parse($('lb-arabic').textContent), monoFontB64: $('lb-mono').textContent.trim(), glyphMasks: JSON.parse($('lb-glyphs').textContent) };
    try {
      var ff = new FontFace('LeerBox Mono', LB.b64ToBytes(LB.resources.monoFontB64).buffer);
      document.fonts.add(await ff.load());
    } catch (err) { /* system monospace fallback */ }
    var packed = LB.b64ToBytes($('lb-fontpack').textContent.trim());
    var raw = await LB.inflateAuto(packed, 'deflate', 256 * 1024 * 1024);
    fonts = new LB.FontManager(); fonts.loadPack(raw); engine = new LB.Engine(fonts);
    startWorker(raw);
    DB = await dbOpen();
    var stored = await dbTx('readonly', function (st) { return st.getAll(); });
    if (stored && stored.length) for (var i = 0; i < stored.length; i++) {
      var r = await fonts.importBytes(new TextEncoder().encode(stored[i].text), stored[i].name);
      if (r.ok && worker) worker.postMessage({ type: 'addFont', name: stored[i].name, text: stored[i].text });
    }
    var cats = fonts.categories();
    $('fCat').replaceChildren.apply($('fCat'), [el('option', { text: 'All' })].concat(cats.map(function (c) { return el('option', { value: c[0], text: c[0] + ' (' + c[1] + ')' }); })));
    $('fSrc').replaceChildren.apply($('fSrc'), ['All'].concat(fonts.sources(), ['imported']).map(function (s) { return el('option', { text: s }); }));
    $('hdrCount').textContent = fonts.stats().genuine;
    var st = loadSettings();
    if (st) {
      S.favorites = Array.isArray(st.favorites) ? st.favorites.filter(function (x) { return typeof x === 'string'; }) : [];
      S.recents = Array.isArray(st.recents) ? st.recents.filter(function (x) { return typeof x === 'string'; }) : [];
      S.presets = st.presets && typeof st.presets === 'object' ? st.presets : {};
      S.zoom = +st.zoom || 1; S.autofit = st.autofit !== false; S.graphic = st.graphic !== false;
      $('optAutofit').checked = S.autofit; $('optGraphic').checked = S.graphic;
    }
    wire();
    buildLayoutPanel(); buildEffectsPanel(); buildExportPanel(); buildToolPanel();
    try { IS = window.LeerBoxImageStudio.init({ S: S, fonts: fonts, debounce: debounce, dialog: dialog }); }
    catch (err) { IS = null; console.error(err); status('Image Studio unavailable: ' + err.message, 'warn'); }
    if (st && st.last) { try { applyProject(LB.project.parseProject(JSON.stringify(st.last))); } catch (err) { /* ignore stale state */ } }
    setScope('All');
    requestRender(0);
    $('charCount').textContent = cps($('text').value).length + ' chars';
    status('Ready · ' + fonts.entries.size + ' fonts loaded in ' + Math.round(performance.now() - t0) + ' ms', 'ok');
    window.LeerBoxApp = { S: S, fonts: fonts, engine: engine, selectFont: selectFont, setMode: setMode, setView: setView, exportCurrent: exportCurrent, isWorker: function () { return !!(worker && workerReady); }, imageStudio: function () { return IS; } };
  }
  boot().catch(function (err) { status('Startup failed: ' + err.message, 'err'); console.error(err); });
})();
