/* LeerBox — JavaScript engine tests (Node >= 18). Run: node tests/js/run_tests.js
 * Verifies the HTML edition's engine against the pyfiglet reference and the Python engine (cross-edition fixtures). */
'use strict';
const fs = require('fs'), path = require('path'), zlib = require('zlib');
const ROOT = path.resolve(__dirname, '..', '..');
const LB = require(path.join(ROOT, 'dist', 'leerbox_engine.js'));
LB.resources = { arabicTables: JSON.parse(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/arabic_tables.json'), 'utf8')) };
const packed = new Uint8Array(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/fontpack.bin')));
let pass = 0, fail = 0;
const failures = [];
function check(name, ok, detail) {
  if (ok) pass++; else { fail++; failures.push(name + (detail ? ' :: ' + detail : '')); }
}
function eq(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

// --- inflate & zip
const raw = LB.inflateZlib(packed);
check('js inflate == zlib', Buffer.compare(Buffer.from(raw), zlib.inflateSync(Buffer.from(packed))) === 0);
const rawDeflate = zlib.deflateRawSync(Buffer.from('hello hello hello '.repeat(1000)));
check('inflateRaw', Buffer.from(LB.inflateRaw(new Uint8Array(rawDeflate))).toString() === 'hello hello hello '.repeat(1000));
let bombBlocked = false;
try { LB.inflateRaw(new Uint8Array(zlib.deflateRawSync(Buffer.alloc(5e6))), 1e6); } catch (e) { bombBlocked = /limit/.test(e.message); }
check('inflate output limit (zip bomb guard)', bombBlocked);

const fm = new LB.FontManager(); fm.loadPack(raw);
const eng = new LB.Engine(fm);
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'FONT_MANIFEST.json'), 'utf8'));
check('font count matches manifest', fm.stats().genuine === manifest.counts.genuineFigletToilet, fm.stats().genuine);

// --- pyfiglet reference
const ref = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/golden/figlet_reference.json'), 'utf8'));
let refFail = 0;
for (const c of ref.cases) {
  const rows = LB.figlet.renderFigletRows(fm.font(c.font), c.text, {}).map(r => r.replace(/\s+$/, ''));
  while (rows.length && !rows[rows.length - 1]) rows.pop();
  if (!eq(rows, c.expected)) { refFail++; if (refFail <= 5) failures.push('pyfiglet ref ' + c.font + ' ' + JSON.stringify(c.text)); }
}
check(`pyfiglet reference (${ref.cases.length} cases)`, refFail === 0, refFail + ' mismatches');

// --- cross-edition fixtures (Python engine output)
const ce = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/golden/cross_edition.json'), 'utf8'));
let ceFail = 0;
for (const c of ce.cases) {
  let art;
  try { art = eng.render(c.font, c.text, c.options, c.effects); } catch (e) { ceFail++; failures.push('cross ' + c.name + ' threw ' + e.message); continue; }
  const txt = LB.exporter.toTxt(art), ansi = LB.exporter.toAnsi(art, 'truecolor');
  const a256 = LB.exporter.toAnsi(art, '256'), a16 = LB.exporter.toAnsi(art, '16');
  if (txt !== c.txt || ansi !== c.ansi || a256 !== c.ansi256 || a16 !== c.ansi16 || art.width !== c.w || art.height !== c.h) {
    ceFail++;
    if (ceFail <= 8) failures.push('cross ' + c.name + (txt !== c.txt ? ' [txt]' : '') + (ansi !== c.ansi ? ' [ansi]' : '') + (a256 !== c.ansi256 ? ' [256]' : '') + (a16 !== c.ansi16 ? ' [16]' : ''));
  }
}
check(`cross-edition renders (${ce.cases.length} cases, txt + 3 ANSI modes)`, ceFail === 0, ceFail + ' mismatches');
for (const a of ce.arabic) {
  check('arabic shape ' + a.text, LB.arabic.shape(a.text) === a.shaped);
  check('arabic visual ' + a.text, LB.arabic.visualText(a.text) === a.visual);
  check('arabic visual rtl ' + a.text, LB.arabic.visualText(a.text, 'rtl') === a.visual_rtl);
  check('arabic visual ltr ' + a.text, LB.arabic.visualText(a.text, 'ltr') === a.visual_ltr);
}
for (const k of Object.keys(ce.styles)) check('style ' + k, LB.unicode.stylize('Hello World 2026!', k) === ce.styles[k], LB.unicode.stylize('Hello World 2026!', k));
for (const k of Object.keys(ce.encodings)) check('encoding ' + k, LB.unicode.encode('LeerBox Ä€ 3.0', k) === ce.encodings[k], LB.unicode.encode('LeerBox Ä€ 3.0', k));
for (const k of Object.keys(ce.boxes)) check('box ' + k, LB.unicode.textBox('Hello\nبوكس wide 全角', k, 1, 'center', 'Title') === ce.boxes[k]);
const img = { width: ce.image.w, height: ce.image.h, pixels: ce.image.pixels };
ce.images.forEach((c, i) => {
  const o = c.options, art = LB.imageart.imageToArt(img, { cols: o.cols, mode: o.mode, ramp: o.ramp, brightness: o.brightness, contrast: o.contrast,
    gamma: o.gamma, invert: o.invert, dither: o.dither, color: o.color, aspect: o.aspect, threshold: o.threshold });
  check(`image ${i} ${o.mode}/${o.dither}/${o.color}`, LB.exporter.toTxt(art) === c.txt && LB.exporter.toAnsi(art, 'truecolor') === c.ansi);
});
for (const [q, t, s] of ce.fuzzy) check(`fuzzy ${q}/${t}`, LB.fuzzyScore(q, t) === s, LB.fuzzyScore(q, t) + ' != ' + s);
for (const q of Object.keys(ce.search)) check('search ' + q, eq(fm.search(q).slice(0, 15), ce.search[q]), JSON.stringify(fm.search(q).slice(0, 5)));

// --- engine-level behaviour
const r = new LB.effects.Rng(1);
check('mulberry32 reference', eq([r.next(), r.next(), r.next()].map(x => x.toFixed(10)), ['0.6270739406', '0.0027357212', '0.5274470400']));
const zipBlob = LB.zipWrite([{ name: 'a.flf', data: new TextEncoder().encode('x') }, { name: '../evil.flf', data: new Uint8Array(3) }]);
zipBlob.arrayBuffer().then(buf => {
  const ents = LB.zipRead(new Uint8Array(buf));
  check('zip roundtrip', new TextDecoder().decode(ents[0].data) === 'x');
  check('zip path traversal rejected', ents[1].error === 'unsafe path rejected');
  const evil = LB.Art.fromText('a\x1b[2Jb\x07');
  check('control characters stripped (ESC/BEL removed, harmless text kept)', LB.exporter.toTxt(evil) === 'a[2Jb\n');
  check('html escaped', LB.exporter.toHtml(LB.Art.fromText('<script>x</script>')).indexOf('<script>') < 0);
  let bad = false; try { LB.figlet.parseFont('flf2a$ 999 1 1 0 0\n'); } catch (e) { bad = true; }
  check('malformed font rejected', bad);
  try { LB.project.parseProject('{"format":"x"}'); check('bad project rejected', false); } catch (e) { check('bad project rejected', true); }
  const pr = LB.project.parseProject(JSON.stringify({ format: 'leerbox-text-art-project', version: 3, text: 'x'.repeat(9000), font: { id: 'fig:standard' }, effects: [{ type: 'eval' }, { type: 'frame' }] }));
  check('project sanitized', pr.text.length === 5000 && pr.effects.length === 1 && pr.effects[0].type === 'frame');
  // every font renders
  let renderFail = [];
  for (const id of fm.order) { try { LB.renderFont(fm.font(id), 'Ab1', LB.textOptions({})); } catch (e) { renderFail.push(id); } }
  check(`every built-in font renders (${fm.order.length})`, renderFail.length === 0, renderFail.slice(0, 5).join(','));
  // import duplicate
  fm.importBytes(fm.payload(fm.entries.get('fig:standard')), 'std.flf').then(res => {
    check('duplicate import rejected', !res.ok && res.duplicate === 'fig:standard');
    const img = require('./image_tests.js')(LB, check, failures);
    console.log(`Image Studio cross-edition: ${img.exact}/${img.total} cases identical (${img.cellsSame}/${img.cellsTotal} cells)`);
    console.log(`JS tests: ${pass} passed, ${fail} failed`);
    if (failures.length) console.log('FAILURES:\n  ' + failures.join('\n  '));
    process.exit(fail ? 1 : 0);
  });
});
