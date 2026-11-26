/* LeerBox — Image-to-Art and Animation-to-Art workspaces (HTML edition).
 * Shares the export engine, effects pipeline, settings storage and project format with the Text Studio.
 * Heavy work runs in a dedicated Web Worker (main-thread fallback where workers are unavailable). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var M = LB.imgmodes, IC = LB.imgcore, IG = LB.imgglyphs, IA = LB.imganalysis, AN = LB.imganim, X = LB.exporter;
  var KEY = 'leerbox.imagestudio.v1';
  var ADJUST = ['exposure', 'brightness', 'contrast', 'gamma', 'saturation', 'vibrance', 'hue', 'sharpness', 'blur', 'denoise', 'black', 'white',
    'highlights', 'shadows', 'posterize', 'local_contrast', 'remove_bg', 'equalize', 'grayscale', 'invert'];
  var SECTIONS = [['Algorithm', ['luma', 'dither', 'dither_strength', 'threshold', 'adaptive', 'light_on_dark', 'seed']],
    ['Custom words', ['text', 'text_mode', 'text_dir']], ['Output resolution', ['cols', 'rows', 'cell_aspect', 'lock_aspect', 'target_aspect', 'fit']],
    ['Geometry', ['crop_x0', 'crop_y0', 'crop_x1', 'crop_y1', 'rotate', 'angle', 'flip_h', 'flip_v', 'pad']], ['Image adjustments', ADJUST],
    ['Edges', ['edge_method', 'edge_strength', 'edge_threshold', 'levels']],
    ['Colours & background', ['color', 'colors', 'gradient', 'dominant_k', 'color_target', 'background', 'transparent_bg']]];
  var LABELS = { cols: 'Width (chars)', rows: 'Height (0 = auto)', cell_aspect: 'Cell aspect w/h', target_aspect: 'Custom aspect (0 = image)',
    threshold: 'Threshold / dot sensitivity', remove_bg: 'Remove background', local_contrast: 'Local contrast', light_on_dark: 'Light text on dark',
    transparent_bg: 'Keep transparency empty', edge_threshold: 'Edge threshold', dominant_k: 'Dominant colours', angle: 'Rotate (free °)', rotate: 'Rotate 90°' };
  var app = null, host = null, ui = {}, st = null, worker = null, wReady = false, wId = 0, wCalls = {}, sentKeys = new Set();

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k]; else if (k === 'className') e.className = attrs[k];
      else if (k.indexOf('on') === 0) e.addEventListener(k.slice(2), attrs[k]); else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function status(msg, lvl) { var s = $('status'); s.textContent = msg; s.className = lvl || ''; }
  function info(msg) { $('sizeInfo').textContent = msg; }
  function fmtB(n) { return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
  function download(blob, name) { var a = el('a', { href: URL.createObjectURL(blob), download: name }); document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000); }
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify({ params: st.params, presets: st.presets, palettes: st.palettes })); } catch (e) { /* private mode */ } }

  // ---------------------------------------------------------------- worker
  function startWorker() {
    try {
      var src = $('lb-engine').textContent + '\n' + $('lb-worker-src').textContent;
      worker = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
      worker.onmessage = function (e) {
        var m = e.data;
        if (m.type === 'imgready') { wReady = true; return; }
        var cb = wCalls[m.id]; if (!cb) return;
        if (m.type === 'imgprogress') { if (cb.progress) cb.progress(m.i, m.n); return; }
        delete wCalls[m.id];
        if (m.error) cb.rej(new Error(m.error)); else cb.res(m);
      };
      worker.onerror = function () { worker = null; wReady = false; };
      worker.postMessage({ type: 'imginit', glyphs: LB.resources.glyphMasks, arabic: LB.resources.arabicTables });
    } catch (e) { worker = null; }
  }
  function sendImage(key, img) {
    if (!worker || sentKeys.has(key)) return;
    worker.postMessage({ type: 'imgset', key: key, img: { w: img.w, h: img.h, rgb: img.rgb.buffer.slice(0), a: img.a.buffer.slice(0) } });
    if (key.indexOf('anim:') !== 0) sentKeys.add(key);
  }
  function call(msg, progress) {
    return new Promise(function (res, rej) {
      if (!worker || !wReady) return rej(new Error('no-worker'));
      msg.id = ++wId; wCalls[msg.id] = { res: res, rej: rej, progress: progress }; worker.postMessage(msg);
    });
  }
  function toArt(o) { return new LB.Art(o.chars, o.fg, o.bg, o.meta || {}); }

  // ---------------------------------------------------------------- state
  function cur() { return st.library[st.current] || null; }
  function setParams(p, push) {
    if (push !== false) { st.undo.push(JSON.stringify(st.params)); st.undo = st.undo.slice(-100); st.redo = []; }
    st.params = M.sanitizeParams(p); syncControls(); save(); requestRender();
  }
  function setParam(k, v) { var p = Object.assign({}, st.params); p[k] = v; setParams(p); }

  // ---------------------------------------------------------------- layout
  function buildImageWs() {
    var left = el('aside', { className: 'left' }), center = el('section', { className: 'center' }), right = el('aside', { className: 'right' });
    var fileIn = el('input', { type: 'file', accept: 'image/*,.svg,.tif,.tiff,.ico,.avif,.heic', multiple: '', hidden: '' });
    fileIn.addEventListener('change', function () { Array.from(fileIn.files).forEach(addFile); fileIn.value = ''; });
    ui.lib = el('div', { className: 'imglib' });
    ui.modes = el('div', { className: 'imglib modes2' });
    M.MODE_KEYS.forEach(function (k) { ui.modes.appendChild(el('div', { className: 'item', 'data-k': k, text: M.MODES[k][0], title: M.MODES[k][6], onclick: function () { setParam('mode', k); } })); });
    ui.modeDesc = el('div', { className: 'note' });
    ui.pal = el('input', { type: 'text', list: 'lbPalettes', placeholder: 'palette key or characters' });
    ui.palList = el('datalist', { id: 'lbPalettes' });
    ui.pal.addEventListener('change', function () { setParam('palette', paletteValue(ui.pal.value)); });
    ui.presetSel = el('select', {});
    left.append(el('h4', { text: 'Image import', style: 'margin-top:0' }),
      el('div', { className: 'row' }, [el('button', { text: 'Open…', onclick: function () { fileIn.click(); } }), el('button', { text: 'Paste', onclick: pasteFromClipboard }),
        el('button', { text: 'Remove', onclick: removeImage })]), fileIn,
      el('div', { className: 'note', text: 'Drop images anywhere, paste with Ctrl+V. PNG, JPEG, GIF, BMP, WebP, ICO, sanitised SVG, baseline TIFF (built-in), AVIF/HEIC where this browser decodes them.' }),
      el('h4', { text: 'Image library / batch queue' }), ui.lib, el('button', { text: 'Batch export queue (ZIP)', onclick: batchExport }),
      el('h4', { text: 'Conversion mode' }), ui.modes, ui.modeDesc,
      el('h4', { text: 'Character palette' }), ui.pal, ui.palList,
      el('div', { className: 'row', style: 'margin-top:4px;flex-wrap:wrap' }, [el('button', { text: 'Sort by density', onclick: sortPalette }), el('button', { text: '★ Save', onclick: savePalette }),
        el('button', { text: 'From font', onclick: paletteFromFont }), el('button', { text: 'Import', onclick: importPalettes }), el('button', { text: 'Export', onclick: exportPalettes })]),
      el('h4', { text: 'Saved presets' }), ui.presetSel,
      el('div', { className: 'row', style: 'margin-top:4px' }, [el('button', { text: 'Load', onclick: function () { var p = st.presets[ui.presetSel.value]; if (p) setParams(p); } }),
        el('button', { text: 'Save…', onclick: function () { var n = prompt('Preset name'); if (n) { st.presets[n.slice(0, 80)] = st.params; save(); fillPresets(); } } }),
        el('button', { text: 'Delete', onclick: function () { delete st.presets[ui.presetSel.value]; save(); fillPresets(); } })]));
    ui.view = 'art'; ui.zoom = 1; ui.slider = 0.5; ui.grid = false;
    var views = el('div', { className: 'views' });
    [['art', 'Text art'], ['original', 'Original'], ['side', 'Side by side'], ['slider', 'Slider'], ['split', 'Split']].forEach(function (v) {
      views.appendChild(el('button', { text: v[1], 'data-v': v[0], className: v[0] === 'art' ? 'on' : '', onclick: function () { ui.view = v[0]; views.querySelectorAll('button').forEach(function (b) { b.classList.toggle('on', b.dataset.v === v[0]); }); draw(); } }));
    });
    ui.optSel = el('select', {}); Object.keys(IA.OPT_PRESETS).forEach(function (k) { ui.optSel.appendChild(el('option', { value: k, text: IA.OPT_PRESETS[k].label })); });
    ui.zoomLbl = el('span', { className: 'muted small', text: '100%' });
    ui.adjChk = el('input', { type: 'checkbox' }); ui.adjChk.addEventListener('change', function () { srcCanvas(); draw(); });
    ui.gridChk = el('input', { type: 'checkbox' }); ui.gridChk.addEventListener('change', function () { ui.grid = ui.gridChk.checked; draw(); });
    ui.stage = el('div', { className: 'stage imgstage' });
    ui.canvas = el('canvas', { className: 'art' }); ui.stage.appendChild(ui.canvas);
    center.append(el('div', { className: 'toolbar' }, [views, el('label', {}, [ui.adjChk, 'Adjusted']), el('label', {}, [ui.gridChk, 'Grid']), el('span', { className: 'spacer' }),
      ui.zoomLbl, el('button', { text: '−', onclick: function () { zoom(ui.zoom / 1.25); } }), el('button', { text: '+', onclick: function () { zoom(ui.zoom * 1.25); } }),
      el('button', { text: 'Fit', onclick: fit }), el('button', { text: '⛶', onclick: fullscreenImg })]),
      el('div', { className: 'toolbar' }, [el('button', { text: 'Analyze image', onclick: runAnalyze }), el('span', { className: 'muted small', text: 'Smart Optimize' }), ui.optSel,
        el('button', { className: 'primary', text: 'Run', onclick: runOptimize }), el('span', { className: 'spacer' }),
        el('button', { text: 'Reset', onclick: function () { setParams({ mode: st.params.mode, cols: st.params.cols }); } }),
        el('button', { text: 'Undo', onclick: function () { if (st.undo.length) { st.redo.push(JSON.stringify(st.params)); setParams(JSON.parse(st.undo.pop()), false); } } }),
        el('button', { text: 'Redo', onclick: function () { if (st.redo.length) { st.undo.push(JSON.stringify(st.params)); setParams(JSON.parse(st.redo.pop()), false); } } })]),
      ui.stage, el('div', { className: 'note', text: 'Drag to pan · Ctrl+wheel to zoom · in Slider view drag with Shift held to move the divider' }));
    var pan = null;
    ui.stage.addEventListener('pointerdown', function (e) { pan = { x: e.clientX, y: e.clientY, l: ui.stage.scrollLeft, t: ui.stage.scrollTop, shift: e.shiftKey }; if (pan.shift) sliderTo(e); });
    window.addEventListener('pointermove', function (e) { if (!pan) return; if (pan.shift) sliderTo(e); else { ui.stage.scrollLeft = pan.l - (e.clientX - pan.x); ui.stage.scrollTop = pan.t - (e.clientY - pan.y); } });
    window.addEventListener('pointerup', function () { pan = null; });
    ui.stage.addEventListener('wheel', function (e) { if (e.ctrlKey) { e.preventDefault(); zoom(ui.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)); } }, { passive: false });
    // right panel
    var panel = el('div', { className: 'panel' });
    ui.ctrl = {};
    SECTIONS.forEach(function (sec) {
      panel.appendChild(el('h4', { text: sec[0] }));
      var g = el('div', { className: 'grid2' });
      sec[1].forEach(function (k) { var w = control(k); g.append(el('label', { text: LABELS[k] || k.replace(/_/g, ' ') }), w); ui.ctrl[k] = w; });
      if (sec[0] === 'Output resolution') {
        var cp = el('select', {}); ['preset…', '40', '80', '120', '200', '300', '500', '1000'].forEach(function (v) { cp.appendChild(el('option', { text: v })); });
        cp.addEventListener('change', function () { if (+cp.value) setParam('cols', +cp.value); cp.selectedIndex = 0; });
        ui.ls = el('input', { type: 'number', min: 0, max: 2, step: 0.05, value: app.S.exp.letter_spacing || 0 });
        ui.lh = el('input', { type: 'number', min: 0.8, max: 3, step: 0.05, value: app.S.exp.line_height });
        [ui.ls, ui.lh].forEach(function (i) { i.addEventListener('change', function () { app.S.exp = X.settings(Object.assign({}, app.S.exp, { letter_spacing: +ui.ls.value, line_height: +ui.lh.value })); draw(true); }); });
        g.append(el('label', { text: 'Preset' }), cp, el('label', { text: 'Char spacing' }), ui.ls, el('label', { text: 'Line spacing' }), ui.lh);
        ui.cost = el('div', { className: 'note' });
        panel.append(g, ui.cost);
      } else panel.appendChild(g);
    });
    ui.fx = el('input', { type: 'checkbox' }); ui.fx.addEventListener('change', requestRender);
    ui.fmt = el('select', {}); Object.keys(X.FORMATS).filter(function (k) { return k !== 'json'; }).forEach(function (k) { ui.fmt.appendChild(el('option', { value: k, text: k + ' — ' + X.FORMATS[k][0] })); });
    ui.typoSize = el('input', { type: 'number', min: 4, max: 64, value: 10, style: 'width:60px' });
    ui.typoVary = el('select', {}); ['opacity', 'size', 'weight'].forEach(function (v) { ui.typoVary.appendChild(el('option', { text: v })); });
    ui.typoRot = el('input', { type: 'checkbox' });
    ui.compat = el('div', { className: 'note' });
    var projIn = el('input', { type: 'file', accept: '.json', hidden: '' });
    projIn.addEventListener('change', function () { if (projIn.files[0]) openProject(projIn.files[0]); projIn.value = ''; });
    panel.append(el('h4', { text: 'Effects (shared with Text Studio)' }), el('label', {}, [ui.fx, ' Apply the Text Studio effects pipeline']),
      el('h4', { text: 'Export' }), el('div', { className: 'row' }, [ui.fmt, el('button', { className: 'primary', text: 'Export', onclick: exportArt })]),
      el('div', { className: 'row', style: 'margin-top:4px;flex-wrap:wrap' }, [el('button', { text: 'Copy text', onclick: function () { copy('text'); } }), el('button', { text: 'Copy ANSI', onclick: function () { copy('ansi'); } }),
        el('button', { text: 'Copy HTML', onclick: function () { copy('html'); } }), el('button', { text: 'Comparison PNG', onclick: exportComparison })]),
      el('div', { className: 'note', text: 'Font size, colours, scale and transparency come from the Text Studio Export tab.' }),
      el('h4', { text: 'Typographic composition (graphic, not text)' }), el('div', { className: 'row' }, [ui.typoSize, ui.typoVary, el('label', {}, [ui.typoRot, '90°'])]),
      el('div', { className: 'row', style: 'margin-top:4px' }, [el('button', { text: 'PNG', onclick: function () { exportTypo('png'); } }), el('button', { text: 'SVG', onclick: function () { exportTypo('svg'); } })]),
      el('h4', { text: 'Project' }), el('div', { className: 'row' }, [el('button', { text: 'Save image project', onclick: saveProject }), el('button', { text: 'Open…', onclick: function () { projIn.click(); } }), projIn]),
      ui.compat);
    right.appendChild(panel);
    host.image.append(left, center, right);
    fillPalettes(); fillPresets();
  }
  function control(k) {
    var spec = M.IMG_PARAMS[k], t = spec[0], w;
    if (t === 'bool') { w = el('input', { type: 'checkbox' }); w.addEventListener('change', function () { setParam(k, w.checked); }); }
    else if (t === 'choice') { w = el('select', {}); M.P_CHOICES[k].forEach(function (c) { w.appendChild(el('option', { value: c, text: c })); }); w.addEventListener('change', function () { setParam(k, typeof spec[1] === 'number' ? +w.value : w.value); }); }
    else if (t === 'int' || t === 'float') {
      if (['cols', 'rows', 'seed', 'posterize', 'dominant_k', 'levels'].indexOf(k) >= 0) { w = el('input', { type: 'number', min: spec[2], max: spec[3], step: 1 }); w.addEventListener('change', function () { setParam(k, +w.value); }); }
      else {
        w = el('div', { className: 'row' }); var r = el('input', { type: 'range', min: spec[2], max: spec[3], step: (spec[3] - spec[2]) / 200 }), o = el('span', { className: 'small muted', style: 'width:38px;text-align:right' });
        r.addEventListener('input', function () { o.textContent = (+r.value).toFixed(2); app.debounce('imgp', function () { setParam(k, +r.value); }, 120); });
        w.append(r, o); w._r = r; w._o = o;
      }
    } else { w = el('input', { type: 'text' }); w.addEventListener('change', function () { setParam(k, w.value); }); }
    return w;
  }
  function syncControls() {
    Object.keys(ui.ctrl).forEach(function (k) {
      var w = ui.ctrl[k], v = st.params[k];
      if (w._r) { w._r.value = v; w._o.textContent = (+v).toFixed(2); }
      else if (w.type === 'checkbox') w.checked = !!v; else w.value = v;
    });
    ui.modes.querySelectorAll('.item').forEach(function (it) { it.classList.toggle('sel', it.dataset.k === st.params.mode); });
    ui.modeDesc.textContent = M.MODES[st.params.mode][6];
    if (document.activeElement !== ui.pal) ui.pal.value = st.params.palette;
  }

  // ---------------------------------------------------------------- library & decoding
  function addFile(f) {
    if (f.size > 100 * 1024 * 1024) return status(f.name + ': larger than 100 MB', 'err');
    f.arrayBuffer().then(function (buf) { return addBytes(f.name, new Uint8Array(buf)); });
  }
  function addBytes(name, bytes) {
    status('Decoding ' + name + '…');
    return IC.decodeInBrowser(bytes, name).then(function (img) {
      st.library.push({ name: name, bytes: bytes, img: img, key: 'img' + (++st.seq) });
      st.current = st.library.length - 1; fillLib(); srcCanvas(); requestRender(0);
      status(name + ' — ' + (img.info.source_size || [img.w, img.h]).join('×') + (img.info.reduced_to ? ' (processed at ' + img.info.reduced_to.join('×') + ')' : ''), 'ok');
    }).catch(function (e) { status(name + ': ' + e.message, 'err'); });
  }
  function fillLib() {
    ui.lib.replaceChildren.apply(ui.lib, st.library.map(function (it, i) {
      return el('div', { className: 'item' + (i === st.current ? ' sel' : ''), text: it.name + '  (' + it.img.w + '×' + it.img.h + ')', onclick: function () { st.current = i; fillLib(); srcCanvas(); requestRender(0); } });
    }));
  }
  function removeImage() { if (cur()) { st.library.splice(st.current, 1); st.current = Math.min(st.current, st.library.length - 1); fillLib(); st.art = null; srcCanvas(); requestRender(0); draw(); } }
  async function pasteFromClipboard() {
    try {
      var items = await navigator.clipboard.read();
      for (var i = 0; i < items.length; i++) for (var j = 0; j < items[i].types.length; j++) {
        var t = items[i].types[j];
        if (/^image\//.test(t)) { var b = await items[i].getType(t); return addBytes('clipboard.' + t.split('/')[1], new Uint8Array(await b.arrayBuffer())); }
      }
      status('The clipboard holds no image.', 'warn');
    } catch (e) { status('Clipboard read was blocked by the browser — press Ctrl+V instead.', 'warn'); }
  }
  function onPaste(e) {
    if (app.S.mode !== 'image') return;
    var items = Array.from((e.clipboardData || {}).items || []);
    var img = items.filter(function (it) { return /^image\//.test(it.type); })[0];
    if (img) { e.preventDefault(); var f = img.getAsFile(); if (f) addFile(f); }
  }

  // ---------------------------------------------------------------- rendering
  function requestRender(ms) { app.debounce('imgrender', doRender, ms === undefined ? 120 : ms); }
  function doRender() {
    var it = cur(); if (!it) { draw(); return; }
    var p = st.params, est = M.estimateCost(it.img.w, it.img.h, p);
    ui.cost.textContent = 'Estimate: ' + est.cols + '×' + est.rows + ' = ' + est.cells.toLocaleString() + ' cells · ~' + Math.round(est.est_ms) + ' ms · ~' + fmtB(est.est_memory_bytes) + ' memory · text ≈ ' + fmtB(est.est_text_bytes);
    if (est.heavy && !confirm('This render is estimated at ~' + (est.est_ms / 1000).toFixed(1) + ' s and ' + fmtB(est.est_memory_bytes) + ' of memory (' + est.cells.toLocaleString() + ' cells). Continue?')) return;
    var gen = ++st.gen, fx = ui.fx.checked ? app.S.effects : [], t0 = performance.now();
    status('Rendering ' + M.MODES[p.mode][0] + '…');
    var done = function (art, stats) {
      if (gen !== st.gen) return;
      st.art = art; st.stats = stats; st.ms = performance.now() - t0;
      var colored = art.fg.some(function (r) { return r.some(function (c) { return c !== null; }); }) || art.bg.some(function (r) { return r.some(function (c) { return c !== null; }); });
      var size = colored ? new TextEncoder().encode(X.toAnsi(art, 'truecolor')).length : stats.text_bytes;
      info('Source ' + stats.source.join('×') + ' · Output ' + stats.cols + '×' + stats.rows + ' = ' + stats.chars.toLocaleString() + ' chars · ~' + fmtB(size) + ' · ' + Math.round(st.ms) + ' ms · ' + stats.label + ' · mem ~' + fmtB(stats.est_memory_bytes) + (worker && wReady ? ' · worker' : ''));
      ui.compat.textContent = 'Compatibility: ' + stats.compat;
      status('Ready', 'ok'); draw(true); if (ui.adjChk.checked) srcCanvas();
    };
    if (worker && wReady) {
      sendImage(it.key, it.img);
      call({ type: 'img', key: it.key, params: p, effects: fx }).then(function (m) { done(toArt(m.art), m.stats); }).catch(function (e) { if (gen === st.gen) status('Render failed: ' + e.message, 'err'); });
    } else setTimeout(function () {
      try { var r = M.renderImageArt(it.img, p), a = fx.length ? LB.effects.applyEffects(r.art, fx) : r.art; done(a, r.stats); } catch (e) { status('Render failed: ' + e.message, 'err'); }
    }, 0);
  }
  function srcCanvas() {
    var it = cur(); ui.src = null; if (!it) return;
    var img = ui.adjChk.checked ? M.prepare(it.img, st.params)[0] : it.img, c = el('canvas');
    c.width = img.w; c.height = img.h; c.getContext('2d').putImageData(new ImageData(IC.toRgba(img), img.w, img.h), 0, 0);
    ui.src = c;
  }
  function artCanvas() {
    if (!st.art) return null;
    if (!ui.artC || ui.artC._art !== st.art || ui.artC._exp !== JSON.stringify(app.S.exp)) {
      var s = Object.assign({}, app.S.exp, { padding: 6, scale: 1, font_size: 12 });
      try { ui.artC = X.renderCanvas(st.art, s); } catch (e) { status(e.message, 'warn'); return null; }
      ui.artC._art = st.art; ui.artC._exp = JSON.stringify(app.S.exp);
    }
    return ui.artC;
  }
  function composite() {
    var a = artCanvas(), s = ui.src, v = ui.view;
    if (v === 'original' || !a) return s;
    if (v === 'art' || !s) return a;
    var c = el('canvas'), x = c.getContext('2d'), sw = Math.round(s.width * a.height / s.height);
    if (v === 'side') { c.width = sw + 12 + a.width; c.height = a.height; x.drawImage(s, 0, 0, sw, a.height); x.drawImage(a, sw + 12, 0); return c; }
    c.width = a.width; c.height = a.height;
    if (v === 'split') { x.drawImage(a, 0, 0); x.drawImage(s, 0, 0, s.width, s.height / 2, 0, 0, a.width, a.height / 2); return c; }
    x.drawImage(s, 0, 0, a.width, a.height); var cut = Math.round(a.width * ui.slider);
    x.drawImage(a, 0, 0, cut, a.height, 0, 0, cut, a.height);
    x.fillStyle = '#7c8cff'; x.fillRect(cut - 1, 0, 2, a.height);
    return c;
  }
  function draw() {
    var c = composite(), cv = ui.canvas, ctx = cv.getContext('2d');
    if (!c) { cv.width = 600; cv.height = 120; ctx.fillStyle = '#8a93a6'; ctx.font = '14px sans-serif'; ctx.fillText('Open, drop or paste an image to start. Processing is local.', 16, 40); return; }
    cv.width = Math.max(1, Math.round(c.width * ui.zoom)); cv.height = Math.max(1, Math.round(c.height * ui.zoom));
    ctx.imageSmoothingEnabled = ui.zoom < 1; ctx.drawImage(c, 0, 0, cv.width, cv.height);
    if (ui.grid && st.art && (ui.view === 'art' || ui.view === 'slider' || ui.view === 'split')) {
      var s = X.settings(app.S.exp), cw = 12 * 0.6021 * (1 + s.letter_spacing) * ui.zoom, ch = 12 * s.line_height * ui.zoom, pad = 6 * ui.zoom;
      if (cw >= 4) { ctx.strokeStyle = 'rgba(80,90,120,.45)'; ctx.beginPath();
        for (var x = 0; x <= st.art.width; x++) { ctx.moveTo(pad + x * cw, pad); ctx.lineTo(pad + x * cw, pad + st.art.height * ch); }
        for (var y = 0; y <= st.art.height; y++) { ctx.moveTo(pad, pad + y * ch); ctx.lineTo(pad + st.art.width * cw, pad + y * ch); }
        ctx.stroke(); }
    }
    ui.zoomLbl.textContent = Math.round(ui.zoom * 100) + '%';
  }
  function sliderTo(e) { var r = ui.canvas.getBoundingClientRect(); ui.slider = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); if (ui.view === 'slider') draw(); }
  function zoom(z) { ui.zoom = Math.max(0.05, Math.min(8, z)); draw(); }
  function fit() { var c = composite(); if (c) zoom(Math.min((ui.stage.clientWidth - 4) / c.width, (ui.stage.clientHeight - 4) / c.height)); }
  function fullscreenImg() { var c = composite(); if (!c) return; var h = $('fullHost'); c.style.maxWidth = '100%'; c.style.maxHeight = '100vh'; h.replaceChildren(c); $('fullscreen').classList.add('on'); }

  // ---------------------------------------------------------------- analysis & optimisation
  function runAnalyze() {
    var it = cur(); if (!it) return; status('Analyzing…');
    var show = function (a) {
      var m = a.metrics, rows = Object.keys(m).filter(function (k) { return ['histogram16', 'local_luminance_4x4', 'dominant_colors', 'percentiles', 'gradient_orientation'].indexOf(k) < 0; }).map(function (k) { return el('tr', {}, [el('td', { text: k }), el('td', { text: String(m[k]) })]); });
      var sw = el('div', { className: 'row' }, m.dominant_colors.map(function (d) { return el('span', { className: 'swatch', title: d.color + ' ' + Math.round(d.share * 100) + '%', style: 'background:' + d.color }); }));
      app.dialog([el('h3', { text: 'Image analysis' }), sw, el('table', { className: 'uni' }, rows), el('h4', { text: 'Recommendations (rule-based; every value can be overridden)' }),
        el('ul', {}, a.recommendations.map(function (r) { return el('li', { text: r.key + ' = ' + r.value + ' — ' + r.reason }); })),
        el('button', { className: 'primary', text: 'Apply recommendations', onclick: function () { setParams(IA.recommendedParams(a, st.params)); $('dlg').close(); } })]);
      status('Analysis complete', 'ok');
    };
    if (worker && wReady) { sendImage(it.key, it.img); call({ type: 'imganalyze', key: it.key }).then(function (m) { show(m.result); }).catch(function (e) { status(e.message, 'err'); }); }
    else show(IA.analyze(it.img));
  }
  function runOptimize() {
    var it = cur(); if (!it) return; var preset = ui.optSel.value;
    status('Smart Optimize: rendering candidates…');
    var show = function (res) {
      var tbl = el('table', { className: 'uni' }, [el('tr', {}, ['score', 'mode', 'SSIM', 'edge corr', 'ΔE', 'bytes', ''].map(function (h) { return el('td', { text: h }); }))]);
      res.results.forEach(function (r) {
        var q = r.metrics;
        tbl.appendChild(el('tr', {}, [el('td', { text: r.score }), el('td', { text: M.MODES[r.params.mode][0] }), el('td', { text: q.ssim }), el('td', { text: q.edge_corr }), el('td', { text: q.color_de }), el('td', { text: q.bytes }),
          el('td', {}, [el('button', { text: 'Use', onclick: function () { setParams(r.params); $('dlg').close(); } })])]));
      });
      app.dialog([el('h3', { text: 'Smart Optimize — ' + res.label }), el('p', { className: 'note', text: res.note }), tbl, el('p', { className: 'note', text: res.evaluated + ' candidates in ' + res.ms + ' ms. Adjust any setting afterwards.' })]);
      status('Smart Optimize done', 'ok');
    };
    var prog = function (i, n) { status('Smart Optimize: candidate ' + i + '/' + n); };
    if (worker && wReady) { sendImage(it.key, it.img); call({ type: 'imgopt', key: it.key, params: st.params, preset: preset }, prog).then(function (m) { show(m.result); }).catch(function (e) { status(e.message, 'err'); }); }
    else setTimeout(function () { show(IA.optimize(it.img, st.params, preset, 6, prog)); }, 0);
  }

  // ---------------------------------------------------------------- palettes & presets
  function paletteValue(v) { if (v.indexOf('★ ') === 0) { var d = st.palettes.filter(function (p) { return p.name === v.slice(2); })[0]; return d ? d.chars : ''; } return v; }
  function fillPalettes() { ui.palList.replaceChildren.apply(ui.palList, Object.keys(IG.PALETTES).concat(st.palettes.map(function (p) { return '★ ' + p.name; })).map(function (k) { return el('option', { value: k, label: IG.PALETTES[k] ? IG.PALETTES[k].label : 'favourite' }); })); }
  function fillPresets() { ui.presetSel.replaceChildren.apply(ui.presetSel, [el('option', { value: '', text: '— choose —' })].concat(Object.keys(st.presets).sort().map(function (k) { return el('option', { value: k, text: k }); }))); }
  function sortPalette() { var p = st.params.palette; if (p && !IG.PALETTES[p]) setParam('palette', IG.sortByDensity(IG.graphemes(p)).join('')); }
  function savePalette() { var p = st.params.palette; if (!p) return; var n = prompt('Palette name'); if (!n) return; st.palettes = st.palettes.filter(function (x) { return x.name !== n; }).concat([{ name: n.slice(0, 80), chars: IG.PALETTES[p] ? IG.PALETTES[p].chars : p }]); save(); fillPalettes(); }
  function paletteFromFont() { try { var f = app.fonts.font(app.S.fid); setParam('palette', IG.paletteFromFiglet(f)); status('Palette from ' + app.fonts.entries.get(app.S.fid).name, 'ok'); } catch (e) { status('This font cannot provide a palette: ' + e.message, 'warn'); } }
  function exportPalettes() { download(new Blob([IG.exportPalettes(st.palettes.length ? st.palettes : [{ name: 'current', chars: st.params.palette || ' .:-=+*#%@' }])], { type: 'application/json' }), 'leerbox-palettes.json'); }
  function importPalettes() {
    var i = el('input', { type: 'file', accept: '.json' });
    i.addEventListener('change', function () { if (!i.files[0]) return; i.files[0].text().then(function (t) { try { var items = IG.importPalettes(t), names = new Set(st.palettes.map(function (p) { return p.name; })); items.forEach(function (p) { if (!names.has(p.name)) st.palettes.push(p); }); save(); fillPalettes(); status('Imported ' + items.length + ' palettes', 'ok'); } catch (e) { status(e.message, 'err'); } }); });
    i.click();
  }

  // ---------------------------------------------------------------- export & projects
  function copy(kind) {
    if (!st.art) return;
    if (kind === 'html') return navigator.clipboard.writeText(X.toHtmlFragment(st.art, app.S.exp)).then(function () { status('Copied HTML', 'ok'); });
    var t = kind === 'text' ? X.toTxt(st.art) : X.toAnsi(st.art, app.S.exp.ansi_mode);
    navigator.clipboard.writeText(t).then(function () { status('Copied ' + t.length.toLocaleString() + ' characters (' + kind + ')', 'ok'); }, function () { status('Clipboard write blocked by the browser', 'warn'); });
  }
  function baseName() { var it = cur(); return (it ? it.name.replace(/\.[^.]+$/, '') : 'image') + '-' + st.params.mode; }
  function exportArt() { if (!st.art) return; var f = ui.fmt.value; X.exportBlob(st.art, f, app.S.exp).then(function (b) { download(b, baseName() + X.FORMATS[f][1]); status('Exported ' + f.toUpperCase() + ' (' + fmtB(b.size) + ')', 'ok'); }, function (e) { status(e.message, 'err'); }); }
  function exportComparison() { var it = cur(); if (!it || !st.art) return; AN.comparisonCanvas(it.img, st.art, app.S.exp).toBlob(function (b) { download(b, baseName() + '-comparison.png'); }, 'image/png'); }
  function exportTypo(fmt) {
    var it = cur(); if (!it) return;
    var comp = AN.composeTypographic(it.img, st.params, +ui.typoSize.value, ui.typoVary.value, ui.typoRot.checked ? 90 : 0);
    if (fmt === 'svg') download(new Blob([AN.compositionSvg(comp)], { type: 'image/svg+xml' }), baseName() + '-typographic.svg');
    else AN.compositionCanvas(comp).toBlob(function (b) { download(b, baseName() + '-typographic.png'); }, 'image/png');
  }
  function batchExport() {
    if (!st.library.length) return status('The queue is empty — open several images first.', 'warn');
    var f = ui.fmt.value, files = [], i = 0, report = [];
    (async function () {
      for (; i < st.library.length; i++) {
        var it = st.library[i]; status('Batch ' + (i + 1) + '/' + st.library.length + ': ' + it.name);
        try { var r = M.renderImageArt(it.img, st.params), b = await X.exportBlob(r.art, f, app.S.exp); files.push({ name: ('00' + (i + 1)).slice(-3) + '_' + it.name.replace(/\.[^.]+$/, '') + X.FORMATS[f][1], data: new Uint8Array(await b.arrayBuffer()) }); report.push({ name: it.name, ok: true }); }
        catch (e) { report.push({ name: it.name, ok: false, error: e.message }); }
      }
      files.push({ name: 'batch_report.json', data: new TextEncoder().encode(JSON.stringify(report, null, 1)) });
      download(new Blob([LB.zipWrite(files)], { type: 'application/zip' }), 'leerbox-batch.zip');
      status('Batch: ' + report.filter(function (r) { return r.ok; }).length + '/' + report.length + ' converted', 'ok');
    })();
  }
  function saveProject() {
    var it = cur(), txt = AN.makeImageProject(st.params, it ? it.bytes : null, it ? it.name : '', ui.fx.checked ? app.S.effects : [], {});
    download(new Blob([txt], { type: 'application/json' }), baseName() + '.leerbox-image.json');
  }
  function openProject(file) {
    file.text().then(function (t) {
      var d = AN.parseImageProject(t);
      if (d.effects.length) { app.S.effects = d.effects; ui.fx.checked = true; }
      setParams(d.params);
      if (d.image) addBytes(d.image_name || 'project image', d.image);
      status('Image project opened', 'ok');
    }).catch(function (e) { status(e.message, 'err'); });
  }

  // ================================================================ Animation Studio
  function buildAnimWs() {
    var left = el('aside', { className: 'left' }), center = el('section', { className: 'center' }), right = el('aside', { className: 'right' });
    var fileIn = el('input', { type: 'file', accept: 'image/gif,video/*,.gif,.webm,.mp4,.mov', hidden: '' });
    fileIn.addEventListener('change', function () { if (fileIn.files[0]) openAnim(fileIn.files[0]); fileIn.value = ''; });
    ui.aInfo = el('div', { className: 'note' });
    ui.aFrames = el('div', { className: 'imglib', style: 'flex:1' });
    left.append(el('h4', { text: 'Animation source', style: 'margin-top:0' }), el('button', { text: 'Open GIF or video…', onclick: function () { fileIn.click(); } }), fileIn,
      el('div', { className: 'note', text: 'GIFs are decoded by the built-in decoder (disposal, transparency, interlacing). Videos are decoded locally by this browser; supported containers depend on the browser.' }),
      ui.aInfo, el('h4', { text: 'Frames' }), ui.aFrames);
    ui.aCanvas = el('canvas', { className: 'art' });
    ui.aStage = el('div', { className: 'stage' }, [ui.aCanvas]);
    ui.aScrub = el('input', { type: 'range', min: 0, max: 0, value: 0, style: 'flex:1' });
    ui.aScrub.addEventListener('input', function () { showFrame(+ui.aScrub.value); });
    ui.aLbl = el('span', { className: 'muted small' });
    ui.aPlay = el('button', { text: '▶ Play', onclick: togglePlay });
    ui.aLoop = el('input', { type: 'checkbox', checked: '' });
    center.append(el('div', { className: 'toolbar' }, [ui.aPlay, el('label', {}, [ui.aLoop, 'Loop']), ui.aScrub, ui.aLbl]), ui.aStage);
    var g = el('div', { className: 'grid2' });
    ui.aMode = el('select', {}); M.MODE_KEYS.forEach(function (k) { ui.aMode.appendChild(el('option', { value: k, text: M.MODES[k][0] })); });
    ui.aCols = el('input', { type: 'number', min: 8, max: 400, value: 80 });
    ui.aStart = el('input', { type: 'number', min: 0, value: 0 }); ui.aEnd = el('input', { type: 'number', min: -1, value: -1 });
    ui.aStep = el('input', { type: 'number', min: 1, max: 100, value: 1 }); ui.aFps = el('input', { type: 'number', min: 0, max: 60, value: 0 });
    ui.aVidFps = el('input', { type: 'number', min: 1, max: 30, value: 10 }); ui.aVidMax = el('input', { type: 'number', min: 1, max: 600, value: 120 });
    [['Mode', ui.aMode], ['Width (chars)', ui.aCols], ['First frame', ui.aStart], ['Last frame (−1 = end)', ui.aEnd], ['Use every Nth frame', ui.aStep],
      ['Frame rate (0 = original)', ui.aFps], ['Video sampling fps', ui.aVidFps], ['Video max frames', ui.aVidMax]].forEach(function (r) { g.append(el('label', { text: r[0] }), r[1]); });
    var enc = typeof MediaRecorder !== 'undefined' ? ['video/webm;codecs=vp9', 'video/webm', 'video/mp4'].filter(function (t) { try { return MediaRecorder.isTypeSupported(t); } catch (e) { return false; } }) : [];
    ui.aEnc = enc;
    var panel = el('div', { className: 'panel' }, [el('h4', { text: 'Conversion' }), g,
      el('div', { className: 'note', text: 'All other settings (palette, adjustments, colours, dithering …) come from the Image Studio.' }),
      el('button', { className: 'primary', text: 'Convert frames', onclick: convertAnim }),
      el('h4', { text: 'Export animation' })].concat([['Animated HTML', 'html'], ['GIF', 'gif'], ['Frame sequence (TXT ZIP)', 'zip_txt'], ['Frame sequence (PNG ZIP)', 'zip_png'],
      ['ANSI script (Bash)', 'sh'], ['ANSI script (PowerShell)', 'ps1']].map(function (b) { return el('button', { text: b[0], style: 'display:block;width:100%;margin:2px 0', onclick: function () { exportAnim(b[1]); } }); }),
      enc.length ? [el('button', { text: 'Video (' + (enc[0].indexOf('mp4') >= 0 ? 'MP4' : 'WebM') + ', MediaRecorder)', style: 'display:block;width:100%;margin:2px 0', onclick: function () { exportAnim('video'); } })]
        : [el('div', { className: 'note', text: 'Video export unavailable: this browser has no MediaRecorder video encoder.' })]));
    right.appendChild(panel);
    host.anim.append(left, center, right);
    st.anim = { frames: [], durations: [], arts: [], durs: [], canv: [], pos: 0, timer: null };
  }
  function openAnim(file) {
    var A = st.anim; A.arts = []; A.canv = [];
    if (/^video\//.test(file.type) || /\.(webm|mp4|mov|m4v|ogv)$/i.test(file.name)) return openVideo(file);
    file.arrayBuffer().then(function (buf) {
      var b = new Uint8Array(buf);
      if (IC.sniffFormat(b) !== 'GIF') throw new Error('not a GIF (open GIF animations or video files)');
      var g = AN.decodeGif(b);
      A.frames = g.frames.map(function (d) { return IC.fitSide(IC.fromRgba(g.w, g.h, d, {}), 800); }); A.durations = g.durations;
      animLoaded(file.name + ': ' + A.frames.length + ' frames, ' + g.w + '×' + g.h + ', loop ' + g.loop);
    }).catch(function (e) { status(e.message, 'err'); });
  }
  function openVideo(file) {
    var A = st.anim, v = document.createElement('video'), url = URL.createObjectURL(file), fps = Math.max(1, +ui.aVidFps.value || 10), maxF = Math.max(1, +ui.aVidMax.value || 120);
    v.muted = true; v.preload = 'auto'; v.src = url;
    v.onerror = function () { URL.revokeObjectURL(url); status('This browser cannot decode ' + file.name, 'err'); };
    v.onloadedmetadata = async function () {
      var n = Math.min(maxF, Math.max(1, Math.floor(v.duration * fps))), cw = v.videoWidth, chh = v.videoHeight, f = Math.min(1, 800 / Math.max(cw, chh));
      var c = el('canvas'); c.width = Math.round(cw * f); c.height = Math.round(chh * f); var x = c.getContext('2d', { willReadFrequently: true });
      A.frames = []; A.durations = [];
      for (var i = 0; i < n; i++) {
        await new Promise(function (res) { v.onseeked = res; v.currentTime = Math.min(v.duration - 0.001, i / fps); });
        x.drawImage(v, 0, 0, c.width, c.height);
        A.frames.push(IC.fromRgba(c.width, c.height, x.getImageData(0, 0, c.width, c.height).data, {})); A.durations.push(Math.round(1000 / fps));
        status('Extracting video frames ' + (i + 1) + '/' + n);
      }
      URL.revokeObjectURL(url);
      animLoaded(file.name + ': ' + n + ' frames sampled at ' + fps + ' fps (' + cw + '×' + chh + ', ' + v.duration.toFixed(1) + ' s)');
    };
  }
  function animLoaded(msg) {
    var A = st.anim;
    ui.aInfo.textContent = msg; status(msg, 'ok');
    ui.aFrames.replaceChildren.apply(ui.aFrames, A.durations.map(function (d, i) { return el('div', { className: 'item', text: 'frame ' + (i + 1) + ' · ' + d + ' ms', onclick: function () { showFrame(i); } }); }));
    ui.aMode.value = st.params.mode; ui.aCols.value = Math.min(200, st.params.cols);
    if (worker) worker.postMessage({ type: 'imgset', key: 'anim:clear', img: { w: 0, h: 0, rgb: new ArrayBuffer(0), a: new ArrayBuffer(0) } });
    showFrame(0);
  }
  function convertAnim() {
    var A = st.anim; if (!A.frames.length) return;
    stop();
    var p = Object.assign({}, st.params, { mode: ui.aMode.value, cols: +ui.aCols.value }), args = [+ui.aStart.value, +ui.aEnd.value, +ui.aStep.value, +ui.aFps.value];
    var done = function (arts, durs, stats) {
      A.arts = arts; A.durs = durs;
      var s = Object.assign({}, app.S.exp, { padding: 6, scale: 1, font_size: 10 });
      A.canv = arts.map(function (a) { return X.renderCanvas(a, s); });
      ui.aScrub.max = Math.max(0, arts.length - 1); showFrame(0);
      status('Converted ' + stats.frames + ' frames in ' + stats.ms + ' ms (' + M.MODES[stats.mode][0] + ')', 'ok');
    };
    var prog = function (i, n) { status('Converting frame ' + i + '/' + n); };
    if (worker && wReady) {
      A.frames.forEach(function (f, i) { sendImage('anim:' + i, f); });
      call({ type: 'imganim', keys: A.frames.map(function (_, i) { return 'anim:' + i; }), durations: A.durations, params: p, start: args[0], end: args[1], step: args[2], fps: args[3] }, prog)
        .then(function (m) { done(m.result.arts.map(toArt), m.result.durations, m.result.stats); }).catch(function (e) { status(e.message, 'err'); });
    } else setTimeout(function () { var r = AN.convertAnimation(A.frames, A.durations, p, args[0], args[1], args[2], args[3], prog); done(r.arts, r.durations, r.stats); }, 0);
  }
  function showFrame(i) {
    var A = st.anim, cv = ui.aCanvas, x = cv.getContext('2d');
    if (A.canv.length) { A.pos = Math.max(0, Math.min(A.canv.length - 1, i)); var c = A.canv[A.pos]; cv.width = c.width; cv.height = c.height; x.drawImage(c, 0, 0); ui.aLbl.textContent = (A.pos + 1) + '/' + A.canv.length + ' · ' + A.durs[A.pos] + ' ms'; ui.aScrub.value = A.pos; return; }
    var f = A.frames[i]; if (!f) return; cv.width = f.w; cv.height = f.h; x.putImageData(new ImageData(IC.toRgba(f), f.w, f.h), 0, 0); ui.aLbl.textContent = 'source frame ' + (i + 1);
  }
  function togglePlay() { var A = st.anim; if (A.timer) return stop(); if (!A.canv.length) return; ui.aPlay.textContent = '⏸ Pause'; tick(); }
  function tick() {
    var A = st.anim; showFrame(A.pos);
    var d = A.durs[A.pos], nx = A.pos + 1;
    if (nx >= A.canv.length) { if (!ui.aLoop.checked) { A.timer = null; return stop(); } nx = 0; }
    A.pos = nx; A.timer = setTimeout(tick, Math.max(15, d));
  }
  function stop() { var A = st.anim; clearTimeout(A.timer); A.timer = null; ui.aPlay.textContent = '▶ Play'; }
  async function exportAnim(kind) {
    var A = st.anim; if (!A.arts.length) return status('Convert the frames first.', 'warn');
    var loop = ui.aLoop.checked, s = app.S.exp;
    try {
      if (kind === 'html') return download(new Blob([AN.toAnimatedHtml(A.arts, A.durs, s, loop)], { type: 'text/html' }), 'leerbox-animation.html');
      if (kind === 'sh' || kind === 'ps1') { var t = AN.toAnsiScript(A.arts, A.durs, kind === 'sh' ? 'bash' : 'powershell', s.ansi_mode === 'none' ? 'truecolor' : s.ansi_mode, loop); return download(new Blob([(kind === 'ps1' ? '﻿' : '') + t], { type: 'text/plain' }), 'leerbox-animation.' + kind); }
      if (kind.indexOf('zip') === 0) { status('Building frame ZIP…'); return download(new Blob([await AN.toFrameZip(A.arts, kind.slice(4), s, A.durs)], { type: 'application/zip' }), 'leerbox-frames.zip'); }
      var cs = A.arts.map(function (a) { return X.renderCanvas(a, Object.assign({}, s, { transparent: false })); }), W = Math.max.apply(null, cs.map(function (c) { return c.width; })), H = Math.max.apply(null, cs.map(function (c) { return c.height; }));
      var frames = cs.map(function (c) { var o = el('canvas'); o.width = W; o.height = H; var x = o.getContext('2d'); x.fillStyle = X.settings(s).background; x.fillRect(0, 0, W, H); x.drawImage(c, 0, 0); return o; });
      if (kind === 'gif') { status('Encoding GIF…'); var gif = AN.encodeGif(frames.map(function (o) { return { w: W, h: H, data: o.getContext('2d').getImageData(0, 0, W, H).data }; }), A.durs, loop); return download(new Blob([gif], { type: 'image/gif' }), 'leerbox-animation.gif'); }
      if (kind === 'video') {
        var type = ui.aEnc[0], rec = el('canvas'); rec.width = W; rec.height = H; var rx = rec.getContext('2d'), stream = rec.captureStream(30), mr = new MediaRecorder(stream, { mimeType: type }), chunks = [];
        mr.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
        var stopped = new Promise(function (res) { mr.onstop = res; });
        mr.start(); status('Recording ' + type + ' in real time…');
        for (var i = 0; i < frames.length; i++) { rx.drawImage(frames[i], 0, 0); await new Promise(function (r) { setTimeout(r, Math.max(20, A.durs[i])); }); }
        mr.stop(); await stopped;
        download(new Blob(chunks, { type: type.split(';')[0] }), 'leerbox-animation.' + (type.indexOf('mp4') >= 0 ? 'mp4' : 'webm'));
        status('Video exported (' + type + ')', 'ok');
      }
    } catch (e) { status('Export failed: ' + e.message, 'err'); }
  }

  // ================================================================ integration
  function show(mode) {
    $('mainText').hidden = mode !== 'text'; host.image.hidden = mode !== 'image'; host.anim.hidden = mode !== 'animation';
    if (mode === 'image') { srcCanvas(); draw(); if (st.art) info(''); requestRender(0); }
  }
  function init(appApi) {
    app = appApi;
    var saved = load();
    st = { params: M.sanitizeParams(saved.params || {}), presets: saved.presets && typeof saved.presets === 'object' ? saved.presets : {},
      palettes: Array.isArray(saved.palettes) ? saved.palettes : [], library: [], current: -1, seq: 0, gen: 0, undo: [], redo: [], art: null };
    host = { image: $('wsImage'), anim: $('wsAnim') };
    buildImageWs(); buildAnimWs(); syncControls(); startWorker();
    document.addEventListener('paste', onPaste);
    return { show: show, addFile: addFile, addBytes: addBytes, openAnim: openAnim, openProject: openProject, state: function () { return st; } };
  }
  window.LeerBoxImageStudio = { init: init };
})();
