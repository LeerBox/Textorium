/* LeerBox — pure JavaScript DEFLATE / zlib decoder (RFC 1950/1951).
 * Used when DecompressionStream is unavailable and for ZIP font imports.
 * Enforces an output limit to defeat decompression bombs. */
var LB = (typeof LB !== 'undefined') ? LB : {};
(function (LB) {
  'use strict';
  var LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  var LEN_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  var DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  var CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  function Huff(lengths, n) {
    this.counts = new Uint16Array(16);
    this.symbols = new Uint16Array(n);
    for (var i = 0; i < n; i++) this.counts[lengths[i]]++;
    this.counts[0] = 0;
    var offs = new Uint16Array(16);
    for (i = 1; i < 16; i++) offs[i] = offs[i - 1] + this.counts[i - 1];
    for (i = 0; i < n; i++) if (lengths[i]) this.symbols[offs[lengths[i]]++] = i;
  }

  function inflateRaw(data, maxOut) {
    maxOut = maxOut || 512 * 1024 * 1024;
    var pos = 0, bitBuf = 0, bitCnt = 0;
    var out = new Uint8Array(Math.max(1024, data.length * 4)), outLen = 0;
    function need(n) {
      if (outLen + n > out.length) {
        var size = out.length * 2;
        while (size < outLen + n) size *= 2;
        if (size > maxOut * 2 + 1024) size = Math.max(outLen + n, maxOut + 1);
        var nb = new Uint8Array(size); nb.set(out.subarray(0, outLen)); out = nb;
      }
      if (outLen + n > maxOut) throw new Error('decompressed data exceeds limit');
    }
    function bits(n) {
      while (bitCnt < n) {
        if (pos >= data.length) throw new Error('unexpected end of compressed data');
        bitBuf |= data[pos++] << bitCnt; bitCnt += 8;
      }
      var v = bitBuf & ((1 << n) - 1);
      bitBuf >>>= n; bitCnt -= n;
      return v;
    }
    function decode(h) {
      var code = 0, first = 0, index = 0;
      for (var len = 1; len < 16; len++) {
        code |= bits(1);
        var count = h.counts[len];
        if (code - count < first) return h.symbols[index + (code - first)];
        index += count; first += count; first <<= 1; code <<= 1;
      }
      throw new Error('invalid Huffman code');
    }
    var fixedLit, fixedDist;
    function fixed() {
      if (!fixedLit) {
        var l = new Uint8Array(288), i;
        for (i = 0; i < 144; i++) l[i] = 8;
        for (; i < 256; i++) l[i] = 9;
        for (; i < 280; i++) l[i] = 7;
        for (; i < 288; i++) l[i] = 8;
        fixedLit = new Huff(l, 288);
        var d = new Uint8Array(30); for (i = 0; i < 30; i++) d[i] = 5;
        fixedDist = new Huff(d, 30);
      }
    }
    var final = 0;
    while (!final) {
      final = bits(1);
      var type = bits(2);
      if (type === 0) {
        bitBuf = 0; bitCnt = 0;
        if (pos + 4 > data.length) throw new Error('truncated stored block');
        var len = data[pos] | (data[pos + 1] << 8), nlen = data[pos + 2] | (data[pos + 3] << 8);
        pos += 4;
        if ((len ^ 0xffff) !== nlen) throw new Error('stored block length mismatch');
        if (pos + len > data.length) throw new Error('truncated stored block');
        need(len); out.set(data.subarray(pos, pos + len), outLen); outLen += len; pos += len;
        continue;
      }
      var lit, dist;
      if (type === 1) { fixed(); lit = fixedLit; dist = fixedDist; }
      else if (type === 2) {
        var hlit = bits(5) + 257, hdist = bits(5) + 1, hclen = bits(4) + 4;
        var cl = new Uint8Array(19), i2;
        for (i2 = 0; i2 < hclen; i2++) cl[CL_ORDER[i2]] = bits(3);
        var clh = new Huff(cl, 19);
        var lens = new Uint8Array(hlit + hdist), n = 0;
        while (n < hlit + hdist) {
          var sym = decode(clh);
          if (sym < 16) lens[n++] = sym;
          else {
            var rep = 0, val = 0;
            if (sym === 16) { if (!n) throw new Error('repeat with no previous length'); val = lens[n - 1]; rep = 3 + bits(2); }
            else if (sym === 17) rep = 3 + bits(3);
            else rep = 11 + bits(7);
            if (n + rep > hlit + hdist) throw new Error('too many code lengths');
            while (rep--) lens[n++] = val;
          }
        }
        lit = new Huff(lens.subarray(0, hlit), hlit);
        dist = new Huff(lens.subarray(hlit), hdist);
      } else throw new Error('invalid block type');
      for (;;) {
        var s = decode(lit);
        if (s < 256) { need(1); out[outLen++] = s; }
        else if (s === 256) break;
        else {
          s -= 257;
          if (s >= 29) throw new Error('invalid length symbol');
          var L = LEN_BASE[s] + bits(LEN_EXTRA[s]);
          var ds = decode(dist);
          if (ds >= 30) throw new Error('invalid distance symbol');
          var D = DIST_BASE[ds] + bits(DIST_EXTRA[ds]);
          if (D > outLen) throw new Error('distance too far back');
          need(L);
          for (var k = 0; k < L; k++) { out[outLen] = out[outLen - D]; outLen++; }
        }
      }
    }
    return out.subarray(0, outLen);
  }

  function inflateZlib(data, maxOut) {
    if (data.length < 2 || (data[0] & 0x0f) !== 8 || ((data[0] << 8) | data[1]) % 31 !== 0) throw new Error('not a zlib stream');
    return inflateRaw(data.subarray(2), maxOut);
  }

  async function inflateAuto(data, format, maxOut) {
    // Prefer the browser's native decompressor; fall back to the JS implementation.
    if (typeof DecompressionStream !== 'undefined') {
      try {
        var ds = new DecompressionStream(format);
        var stream = new Blob([data]).stream().pipeThrough(ds);
        var buf = new Uint8Array(await new Response(stream).arrayBuffer());
        if (maxOut && buf.length > maxOut) throw new Error('decompressed data exceeds limit');
        return buf;
      } catch (e) { if (/exceeds limit/.test(e.message)) throw e; /* fall through */ }
    }
    return format === 'deflate' ? inflateZlib(data, maxOut) : inflateRaw(data, maxOut);
  }

  function b64ToBytes(b64) {
    if (typeof atob === 'function') {
      var bin = atob(b64), out = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    return new Uint8Array(Buffer.from(b64, 'base64'));
  }

  LB.inflateRaw = inflateRaw;
  LB.inflateZlib = inflateZlib;
  LB.inflateAuto = inflateAuto;
  LB.b64ToBytes = b64ToBytes;
})(LB);
