/* WebGPU glyph-matching prototype benchmark (evaluation only — not used by the app).
 * Paste into the developer console of LeerBox_Text_Art_Studio_V3.html (needs a WebGPU-capable browser).
 * Compares the CPU GlyphMatcher with an equivalent WGSL compute shader on 200,000 random 4×8 cells. */
(async () => {
  const m = new LB.imgglyphs.GlyphMatcher(LB.imgglyphs.resolvePalette('ascii_high'), 4, 8, 24), N = 200000, F = 32, K = 24, G = m.chars.length;
  let s = 1; const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const cells = new Float64Array(N * F); for (let i = 0; i < cells.length; i++) cells[i] = rnd();
  m.cache = new Map(); let t0 = performance.now(); const cpu = m.match(cells, N); const cpuMs = performance.now() - t0;
  const scale = 255 * m.block, q = new Float32Array(N * F), dens = new Float32Array(G), gl = new Float32Array(G * F);
  for (let c = 0; c < N; c++) for (let i = 0; i < F; i++) { const v = Math.min(1, Math.max(0, cells[c * F + i])); q[c * F + i] = Math.floor(v * m.maxMean * 64 + 0.5); }
  for (let g = 0; g < G; g++) { dens[g] = m.dens[g] / scale; for (let i = 0; i < F; i++) gl[g * F + i] = m.G[g][i] / scale; }
  const dev = await (await navigator.gpu.requestAdapter()).requestDevice();
  const code = `@group(0)@binding(0) var<storage,read> cells:array<f32>; @group(0)@binding(1) var<storage,read> glyphs:array<f32>;
@group(0)@binding(2) var<storage,read> dens:array<f32>; @group(0)@binding(3) var<storage,read_write> outp:array<u32>;
@compute @workgroup_size(64) fn main(@builtin(global_invocation_id) id:vec3<u32>){ let c=id.x; if(c>=${N}u){return;}
 var m=0.0; for(var i=0u;i<${F}u;i++){m+=cells[c*${F}u+i];}
 var lo=0u; var hi=${G}u; loop{ if(lo>=hi){break;} let mid=(lo+hi)/2u; if(dens[mid]<m){lo=mid+1u;}else{hi=mid;} }
 var st=clamp(i32(lo)-${K >> 1},0,${G - K}); var best=3.4e38; var bi=u32(st);
 for(var g=u32(st);g<u32(st)+${K}u;g++){ var d=0.0; for(var i=0u;i<${F}u;i++){ let e=cells[c*${F}u+i]-glyphs[g*${F}u+i]; d+=e*e;} if(d<best){best=d;bi=g;} }
 outp[c]=bi; }`;
  const pipe = dev.createComputePipeline({ layout: 'auto', compute: { module: dev.createShaderModule({ code }), entryPoint: 'main' } });
  const buf = (a) => { const b = dev.createBuffer({ size: a.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST }); dev.queue.writeBuffer(b, 0, a); return b; };
  const times = []; let gpu;
  for (let rep = 0; rep < 3; rep++) {
    t0 = performance.now();
    const bo = dev.createBuffer({ size: N * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC }), rb = dev.createBuffer({ size: N * 4, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
    const bg = dev.createBindGroup({ layout: pipe.getBindGroupLayout(0), entries: [buf(q), buf(gl), buf(dens), bo].map((b, i) => ({ binding: i, resource: { buffer: b } })) });
    const enc = dev.createCommandEncoder(), p = enc.beginComputePass(); p.setPipeline(pipe); p.setBindGroup(0, bg); p.dispatchWorkgroups(Math.ceil(N / 64)); p.end();
    enc.copyBufferToBuffer(bo, 0, rb, 0, N * 4); dev.queue.submit([enc.finish()]);
    await rb.mapAsync(GPUMapMode.READ); gpu = new Uint32Array(rb.getMappedRange().slice(0)); rb.unmap(); times.push(performance.now() - t0);
  }
  let same = 0; for (let c = 0; c < N; c++) if (gpu[c] === cpu[c]) same++;
  const r = { cells: N, cpu_ms: Math.round(cpuMs), gpu_ms_incl_upload_readback: times.map(Math.round), identical_fraction: same / N };
  console.log(r); return r;
})();
