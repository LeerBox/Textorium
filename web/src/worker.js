/* LeerBox — Web Worker for background gallery rendering and recommendations.
 * The worker is created from a Blob containing the engine source + this file, so it also works from file:// URLs. */
var fm = null, engine = null;
self.onmessage = function (e) {
  var m = e.data;
  try {
    if (m.type && m.type.indexOf('img') === 0) { imageMessage(m); return; }
    if (m.type === 'init') {
      LB.resources = { arabicTables: m.arabic };
      fm = new LB.FontManager(); fm.loadPack(new Uint8Array(m.pack)); engine = new LB.Engine(fm);
      self.postMessage({ type: 'ready' });
    } else if (m.type === 'addFont') {
      fm.importBytes(new TextEncoder().encode(m.text), m.name).then(function () { /* registered */ });
    } else if (m.type === 'removeFont') {
      fm.removeUser(m.id);
    } else if (m.type === 'render') {
      if (!fm.entries.has(m.fid)) { self.postMessage({ type: 'rendered', id: m.id, gen: m.gen, error: 'font not available in worker' }); return; }
      var art = engine.render(m.fid, m.text, m.opts, m.effects);
      self.postMessage({ type: 'rendered', id: m.id, gen: m.gen, text: art.toText(), w: art.width, h: art.height });
    } else if (m.type === 'recommend') {
      var out = [];
      m.ids.forEach(function (id) {
        try {
          if (!fm.entries.has(id) || engine.unsupportedChars(id, m.text).length) return;
          var a = engine.render(id, m.text, {}, []);
          out.push({ id: id, width: a.width, height: a.height, score: LB.smart.score(a.width, a.height, m.target, Array.from(m.text).length) });
        } catch (err) { /* skip broken font */ }
      });
      self.postMessage({ type: 'recommended', gen: m.gen, results: out });
    }
  } catch (err) {
    self.postMessage({ type: 'rendered', id: m.id, gen: m.gen, error: String(err && err.message || err) });
  }
};

/* ---- Image / Animation Studio jobs (images are sent once and cached by key) ---- */
var imgCache = new Map(), animCache = new Map();
function artOut(a) { return { chars: a.chars, fg: a.fg, bg: a.bg, meta: a.meta }; }
function imageMessage(m) {
  try {
    if (m.type === 'imginit') { LB.resources = LB.resources || {}; LB.resources.glyphMasks = m.glyphs; LB.resources.arabicTables = m.arabic; self.postMessage({ type: 'imgready' }); return; }
    if (m.type === 'imgset') {
      var store = m.key.indexOf('anim:') === 0 ? animCache : imgCache;
      if (m.key === 'anim:clear') { animCache.clear(); return; }
      store.set(m.key, { w: m.img.w, h: m.img.h, rgb: new Float64Array(m.img.rgb), a: new Float64Array(m.img.a), info: {} });
      while (imgCache.size > 12) imgCache.delete(imgCache.keys().next().value);
      return;
    }
    var img = imgCache.get(m.key);
    if (m.type !== 'imganim' && !img) throw new Error('image not cached in worker');
    if (m.type === 'img') {
      var r = LB.imgmodes.renderImageArt(img, m.params), art = r.art;
      if (m.effects && m.effects.length) art = LB.effects.applyEffects(art, m.effects);
      self.postMessage({ type: 'imgdone', id: m.id, art: artOut(art), stats: r.stats });
    } else if (m.type === 'imganalyze') {
      self.postMessage({ type: 'imgdone', id: m.id, result: LB.imganalysis.analyze(img) });
    } else if (m.type === 'imgopt') {
      var res = LB.imganalysis.optimize(img, m.params, m.preset, 6, function (i, n) { self.postMessage({ type: 'imgprogress', id: m.id, i: i, n: n }); });
      res.results.forEach(function (x) { x.art = artOut(x.art); });
      self.postMessage({ type: 'imgdone', id: m.id, result: res });
    } else if (m.type === 'imganim') {
      var frames = m.keys.map(function (k) { return animCache.get(k); });
      var out = LB.imganim.convertAnimation(frames, m.durations, m.params, m.start, m.end, m.step, m.fps, function (i, n) { self.postMessage({ type: 'imgprogress', id: m.id, i: i, n: n }); });
      self.postMessage({ type: 'imgdone', id: m.id, result: { arts: out.arts.map(artOut), durations: out.durations, stats: out.stats } });
    }
  } catch (err) { self.postMessage({ type: 'imgdone', id: m.id, error: String(err && err.message || err) }); }
}
