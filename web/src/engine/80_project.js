/* LeerBox — validated project files (same format as src/leerbox/project.py, interchangeable between editions). */
(function (LB) {
  'use strict';
  var FORMAT = 'leerbox-text-art-project', VERSION = 3;
  function scalar(v) {
    if (v === null || typeof v === 'boolean') return v;
    if (typeof v === 'number') return isFinite(v) ? Math.max(-1e6, Math.min(1e6, v)) : 0;
    if (typeof v === 'string') return v.slice(0, 300);
    return undefined;
  }
  function sanitizeEffects(effects) {
    var D = LB.effects.DEFAULTS, out = [];
    if (!Array.isArray(effects)) return out;
    effects.slice(0, 40).forEach(function (e) {
      if (!e || typeof e !== 'object' || !D[e.type]) return;
      var c = { type: e.type, enabled: e.enabled !== false };
      Object.keys(D[e.type]).forEach(function (k) {
        var dv = D[e.type][k];
        if (!(k in e)) { c[k] = JSON.parse(JSON.stringify(dv)); return; }
        if (Array.isArray(dv)) c[k] = Array.isArray(e[k]) ? e[k].slice(0, 16).map(function (x) { return String(x).slice(0, 16); }) : dv.slice();
        else { var s = scalar(e[k]); c[k] = s === undefined ? dv : s; }
      });
      out.push(c);
    });
    return out;
  }
  function makeProject(text, fontId, fontName, options, effects, exp, extra) {
    var ex = {}; Object.keys(exp || {}).forEach(function (k) { var s = scalar(exp[k]); if (s !== undefined) ex[k] = s; });
    return { format: FORMAT, version: VERSION, app: 'LeerBox Text Art Studio 3.0 (HTML)', savedAt: new Date().toISOString().slice(0, 19),
      text: String(text).slice(0, 5000), font: { id: fontId, name: fontName }, options: LB.textOptions(options),
      effects: sanitizeEffects(effects), export: ex, extra: extra || {} };
  }
  function parseProject(text) {
    if (text.length > 8 * 1024 * 1024) throw new Error('project file too large');
    var obj;
    try { obj = JSON.parse(text.replace(/^﻿/, '')); } catch (e) { throw new Error('invalid JSON: ' + e.message); }
    if (!obj || typeof obj !== 'object' || obj.format !== FORMAT) throw new Error('not a LeerBox project file');
    if (typeof obj.version !== 'number' || obj.version > VERSION) throw new Error('unsupported project version');
    var font = obj.font && typeof obj.font === 'object' ? obj.font : {};
    var ex = {};
    if (obj.export && typeof obj.export === 'object') Object.keys(obj.export).forEach(function (k) { var s = scalar(obj.export[k]); if (s !== undefined) ex[k] = s; });
    return { text: String(obj.text || '').slice(0, 5000), font: { id: String(font.id || '').slice(0, 200), name: String(font.name || '').slice(0, 200) },
      options: LB.textOptions(obj.options), effects: sanitizeEffects(obj.effects), export: ex };
  }
  LB.project = { makeProject: makeProject, parseProject: parseProject, sanitizeEffects: sanitizeEffects, FORMAT: FORMAT };
  if (typeof module !== 'undefined' && module.exports) module.exports = LB;
})(LB);
