/* Image Studio JS benchmarks (Node) — same image as tools/benchmark_image.py; prints JSON. */
'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const LB = require(path.join(ROOT, 'dist', 'leerbox_engine.js'));
LB.resources = { arabicTables: JSON.parse(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/arabic_tables.json'), 'utf8')),
  glyphMasks: JSON.parse(fs.readFileSync(path.join(ROOT, 'src/leerbox/data/glyph_masks.json'), 'utf8')) };
const { execFileSync } = require('child_process');
const raw = execFileSync('python', ['-c', 'import sys,base64;sys.path.insert(0,"tests");import image_fixtures as F;w,h,d=F.large_photo();print(w,h,base64.b64encode(d).decode())'], { cwd: ROOT, maxBuffer: 64 << 20 }).toString().trim().split(' ');
const img = LB.imgcore.fromRgba(+raw[0], +raw[1], Buffer.from(raw[2], 'base64'), {});
function t(fn, n) { let best = Infinity; for (let i = 0; i < (n || 1); i++) { const t0 = process.hrtime.bigint(); fn(); best = Math.min(best, Number(process.hrtime.bigint() - t0) / 1e6); } return Math.round(best * 10) / 10; }
const out = { node: process.version, modes_80_cols_ms: {}, modes_200_cols_ms: {} };
LB.imgmodes.MODE_KEYS.forEach(m => { out.modes_80_cols_ms[m] = t(() => LB.imgmodes.renderImageArt(img, { mode: m, cols: 80 }), 2); });
['classic', 'braille', 'sextant', 'truecolor', 'typographic', 'dense', 'mosaic', 'ansi16'].forEach(m => { out.modes_200_cols_ms[m] = t(() => LB.imgmodes.renderImageArt(img, { mode: m, cols: 200 })); });
out.braille_floyd_500_cols_ms = t(() => LB.imgmodes.renderImageArt(img, { mode: 'braille', cols: 500, dither: 'floyd' }));
out.classic_1000_cols_ms = t(() => LB.imgmodes.renderImageArt(img, { mode: 'classic', cols: 1000 }));
out.typographic_300_cols_ms = t(() => LB.imgmodes.renderImageArt(img, { mode: 'typographic', cols: 300 }));
out.analyze_ms = t(() => LB.imganalysis.analyze(img), 2);
out.optimize_similarity_80_cols_ms = t(() => LB.imganalysis.optimize(img, { cols: 80 }, 'similarity'));
const m = new LB.imgglyphs.GlyphMatcher(LB.imgglyphs.resolvePalette('ascii_high'), 4, 8, 24);
let s = 1; const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
const cells = new Float64Array(200000 * 32); for (let i = 0; i < cells.length; i++) cells[i] = rnd();
m.cache = new Map(); const t0 = Date.now(); m.match(cells, 200000); const dt = (Date.now() - t0) / 1000;
out.glyph_match_200k_random_cells_ms = Math.round(dt * 1000); out.glyph_match_comparisons_per_s = Math.round(200000 * 24 / dt);
console.log(JSON.stringify(out));
