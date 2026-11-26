/* LeerBox — Image Studio JS tests (cross-edition consistency + codec/unit checks). Run: node tests/js/image_tests.js
 * Exported as a function so run_tests.js can include it. */
'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');

function runImageTests(LB, check, failures, opts) {
  opts = opts || {};
  LB.resources = LB.resources || {};
  LB.resources.glyphMasks = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/glyph_masks.json'), 'utf8'));
  const gold = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/golden/image_cross_edition.json'), 'utf8'));
  const imgs = {};
  for (const [name, d] of Object.entries(gold.images)) imgs[name] = LB.imgcore.fromRgba(d.w, d.h, Buffer.from(d.rgba, 'base64'), {});
  let exact = 0, total = 0, cellsTotal = 0, cellsSame = 0;
  const report = [];
  for (const c of gold.cases) {
    const r = LB.imgmodes.renderImageArt(imgs[c.image], c.params).art;
    const want = c.chars.map(s => s.split('\u0000'));
    let same = 0, n = 0, dims = r.height === want.length && r.width === (want[0] || []).length;
    if (dims) {
      for (let y = 0; y < want.length; y++) for (let x = 0; x < want[y].length; x++) {
        n++;
        const f = r.fg[y][x] === null ? -1 : r.fg[y][x], b = r.bg[y][x] === null ? -1 : r.bg[y][x];
        if (r.chars[y][x] === want[y][x] && f === c.fg[y][x] && b === c.bg[y][x]) same++;
      }
    }
    total++; cellsTotal += n; cellsSame += same;
    const rate = n ? same / n : 0;
    if (dims && same === n) exact++;
    report.push({ image: c.image, params: c.params, dims: dims, rate: rate });
    check('image x-edition ' + c.image + ' ' + JSON.stringify(c.params), dims && rate >= 0.99, dims ? (rate * 100).toFixed(2) + '% cells identical' : 'size ' + r.width + 'x' + r.height);
  }
  if (opts.verbose) report.filter(r => r.rate < 1).forEach(r => console.log('  not identical:', r.image, JSON.stringify(r.params), (r.rate * 100).toFixed(2) + '%'));
  for (const [name, a] of Object.entries(gold.analyses)) {
    const js = LB.imganalysis.analyze(imgs[name]);
    const keys = a.recommendations.map(r => r.key + '=' + JSON.stringify(r.value)).join(';');
    const jkeys = js.recommendations.map(r => r.key + '=' + JSON.stringify(r.value)).join(';');
    check('image analysis recommendations identical: ' + name, keys === jkeys, jkeys + ' vs ' + keys);
  }
  // ---- unit checks
  const braille = LB.imgglyphs.BRAILLE_DOTS;
  check('braille dot map is ISO 11548-1', JSON.stringify(braille) === JSON.stringify([[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [0, 3], [1, 3]]));
  check('sextant mapping', LB.imgglyphs.sextantChar(1) === '\u{1FB00}' && LB.imgglyphs.sextantChar(21) === '▌' && LB.imgglyphs.sextantChar(42) === '▐' && LB.imgglyphs.sextantChar(62) === '\u{1FB3B}');
  const lv = LB.imgmodes.densityLevels(LB.imgglyphs.resolvePalette('ascii_basic'));
  check('density levels ascending', lv.every((v, i) => i === 0 || v >= lv[i - 1]));
  // GIF round trip with the built-in encoder/decoder
  const fr = [];
  for (let k = 0; k < 3; k++) { const d = new Uint8ClampedArray(20 * 10 * 4); for (let i = 0; i < 200; i++) { d[i * 4] = (i * 7 + k * 40) & 255; d[i * 4 + 1] = k * 100; d[i * 4 + 2] = 255 - ((i * 3) & 255); d[i * 4 + 3] = 255; } fr.push({ w: 20, h: 10, data: d }); }
  const gif = LB.imganim.encodeGif(fr, [100, 120, 140], true), dec = LB.imganim.decodeGif(gif);
  check('GIF encode/decode frame count & timing', dec.frames.length === 3 && dec.durations.join() === '100,120,140' && dec.loop === 0);
  let maxErr = 0; for (let i = 0; i < 800; i++) maxErr = Math.max(maxErr, Math.abs(dec.frames[1][i] - fr[1].data[i]));
  check('GIF round-trip colour error small (palette quantisation)', maxErr <= 40, 'max channel error ' + maxErr);
  const pyGif = path.join(ROOT, 'tests/golden/anim_test.gif');
  if (fs.existsSync(pyGif)) {
    const ref = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/golden/anim_test_frames.json'), 'utf8'));
    const g = LB.imganim.decodeGif(new Uint8Array(fs.readFileSync(pyGif)));
    let ok = g.frames.length === ref.frames.length;
    for (let i = 0; ok && i < ref.frames.length; i++) ok = Buffer.from(g.frames[i]).toString('base64') === ref.frames[i];
    check('GIF decoder == Pillow frames (disposal, transparency, interlace)', ok, g.frames.length + ' frames');
  }
  for (const t of ['raw', 'lzw', 'packbits']) {
    const p = path.join(ROOT, 'tests/golden/tiff_' + t + '.tif');
    if (!fs.existsSync(p)) continue;
    const ref = fs.readFileSync(path.join(ROOT, 'tests/golden/tiff_ref.rgba'));
    const d = LB.imganim.decodeTiff(new Uint8Array(fs.readFileSync(p)));
    check('TIFF decoder (' + t + ') == Pillow', Buffer.compare(Buffer.from(d.data), ref) === 0);
  }
  const svgBad = ['<svg><script>alert(1)</script></svg>', '<svg onload="x()"/>', '<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', '<svg><image href="https://x/y.png"/></svg>', '<svg><style>@import url(x.css)</style></svg>'];
  check('SVG sanitiser rejects scripts/handlers/entities/external refs', svgBad.every(s => !LB.imgcore.svgIsSafe(s)[0]));
  check('SVG sanitiser accepts plain shapes', LB.imgcore.svgIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4" fill="#f00"/><use href="#a"/></svg>')[0]);
  // ANSI output: valid SGR only + reset
  const ar = LB.imgmodes.renderImageArt(imgs.portrait, { mode: 'truecolor', cols: 30 }).art, ansi = LB.exporter.toAnsi(ar, 'truecolor');
  const escs = ansi.match(/\x1b\[[0-9;]*[A-Za-z]/g) || [];
  check('image ANSI uses only SGR sequences and resets', escs.every(e => /m$/.test(e)) && /\x1b\[0m\n?$/.test(ansi.split('\n').filter(Boolean).pop() + '\n') && !/\x1b[^\[]/.test(ansi));
  // project round trip
  const pj = LB.imganim.makeImageProject({ mode: 'braille', cols: 77 }, new Uint8Array([1, 2, 3]), 'x.png');
  const back = LB.imganim.parseImageProject(pj);
  check('image project round trip', back.params.mode === 'braille' && back.params.cols === 77 && back.image.length === 3);
  let rejected = false; try { LB.imganim.parseImageProject('{"format":"other"}'); } catch (e) { rejected = true; }
  check('foreign project rejected', rejected);
  const sp = LB.imgmodes.sanitizeParams({ cols: 1e9, mode: 'nope', palette: 'ab\x1bc', color: 'x' });
  check('image params sanitised', sp.cols === 1000 && sp.mode === 'classic' && sp.palette === 'abc' && sp.color === 'none');
  return { exact: exact, total: total, cellsSame: cellsSame, cellsTotal: cellsTotal };
}
module.exports = runImageTests;

if (require.main === module) {
  const LB = require(path.join(ROOT, 'dist', 'leerbox_engine.js'));
  LB.resources = { arabicTables: JSON.parse(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/arabic_tables.json'), 'utf8')) };
  let pass = 0, fail = 0; const failures = [];
  const check = (n, ok, d) => { if (ok) pass++; else { fail++; failures.push(n + (d ? ' :: ' + d : '')); } };
  const t0 = Date.now();
  const s = runImageTests(LB, check, failures, { verbose: true });
  console.log(`image cases exactly identical: ${s.exact}/${s.total}; cells identical ${s.cellsSame}/${s.cellsTotal} (${(s.cellsSame / s.cellsTotal * 100).toFixed(3)}%)`);
  failures.forEach(f => console.log('FAIL', f));
  console.log(`${pass} passed, ${fail} failed (${Date.now() - t0} ms)`);
  process.exit(fail ? 1 : 0);
}
