/* Agent Andy — receipt-chain verifier for the browser (and node, for the test).
 *
 * The same checks as receipts/verify.py, done on your machine: for every receipt
 * line, SHA-256 over the line's bytes with its own "hash" member removed must equal
 * that hash; "prev" must equal the previous receipt's hash (genesis = 64 zeros); "seq"
 * must count from 0. Andy writes every line in canonical JSON (sorted keys, no
 * spaces), so the bytes on disk ARE the hashed bytes — nothing is re-serialized here.
 * A chain not written in that form would fail here and pass in Python; Andy's never are.
 *
 * The tip signature is an OpenSSH signature (ssh-keygen -Y sign, namespace
 * "andy-chain-tip") over "andy-chain-tip v1\ncount=<n>\ntip=<hash>\n". It is checked
 * with WebCrypto Ed25519 against the public key in data/andy-chain-signing.pub; a
 * browser without Ed25519 reports "not checked", never VERIFIED.
 */
(function (root) {
  'use strict';
  const GENESIS = '0'.repeat(64);
  const subtle = (root.crypto || {}).subtle;
  const enc = new TextEncoder();

  function hex(buf) { return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join(''); }
  async function sha256hex(text) { return hex(await subtle.digest('SHA-256', enc.encode(text))); }

  // Split one canonical receipt line into its body (the bytes that were hashed) and
  // its top-level hash, by scanning the JSON text — not by parsing and re-printing.
  function splitHash(line) {
    let depth = 0, inStr = false, escd = false, at = -1;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (inStr) { if (escd) escd = false; else if (c === '\\') escd = true; else if (c === '"') inStr = false; continue; }
      if (c === '"') { if (depth === 1 && line.startsWith('"hash":"', i)) { at = i; break; } inStr = true; continue; }
      if (c === '{' || c === '[') depth++; else if (c === '}' || c === ']') depth--;
    }
    if (at < 0) return null;
    let j = at + 8;                                   // first char of the hash value
    while (j < line.length && line[j] !== '"') { if (line[j] === '\\') j++; j++; }
    let s = at, e = j + 1;
    if (line[s - 1] === ',') s--; else if (line[e] === ',') e++;
    return { body: line.slice(0, s) + line.slice(e), hash: line.slice(at + 8, j) };
  }

  // -> { ok, reason, count, tip, failed } with failed = the index of the first bad receipt.
  async function verifyChain(lines) {
    const rows = lines.filter(l => l.trim());
    if (!rows.length) return { ok: false, reason: 'empty chain', count: 0, tip: null, failed: -1 };
    let prev = GENESIS;
    for (let i = 0; i < rows.length; i++) {
      let r;
      try { r = JSON.parse(rows[i]); } catch (e) { return { ok: false, reason: 'receipt ' + i + ': not valid JSON', count: i, tip: prev, failed: i }; }
      const sp = (r && typeof r === 'object') ? splitHash(rows[i]) : null;
      if (!sp) return { ok: false, reason: 'receipt ' + i + ': missing hash', count: i, tip: prev, failed: i };
      if (await sha256hex(sp.body) !== sp.hash) return { ok: false, reason: 'receipt ' + i + ': hash does not recompute', count: i, tip: prev, failed: i };
      if (r.prev !== prev) return { ok: false, reason: 'receipt ' + i + ': broken link to previous receipt', count: i, tip: prev, failed: i };
      if (r.seq !== i) return { ok: false, reason: 'receipt ' + i + ': sequence mismatch', count: i, tip: prev, failed: i };
      prev = sp.hash;
    }
    return { ok: true, reason: rows.length + ' receipts verified', count: rows.length, tip: prev, failed: -1 };
  }

  // ---- OpenSSH signature (sshsig) over the chain tip ----
  function b64(s) { const bin = atob(s.replace(/\s+/g, '')); const out = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; }
  function reader(bytes) {
    let p = 0;
    return {
      bytes(n) { const v = bytes.slice(p, p + n); p += n; return v; },
      u32() { const v = (bytes[p] << 24 | bytes[p + 1] << 16 | bytes[p + 2] << 8 | bytes[p + 3]) >>> 0; p += 4; return v; },
      str() { const n = this.u32(); return this.bytes(n); },
      done() { return p >= bytes.length; },
    };
  }
  function sshString(b) { const out = new Uint8Array(4 + b.length); new DataView(out.buffer).setUint32(0, b.length); out.set(b, 4); return out; }
  function concat(parts) { const n = parts.reduce((a, p) => a + p.length, 0); const out = new Uint8Array(n); let at = 0; for (const p of parts) { out.set(p, at); at += p.length; } return out; }
  function same(a, b) { if (a.length !== b.length) return false; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }
  const dec = new TextDecoder();

  function parseSshSig(armored) {
    const body = armored.split('\n').filter(l => l && !l.startsWith('-----')).join('');
    const r = reader(b64(body));
    const magic = dec.decode(r.bytes(6));
    if (magic !== 'SSHSIG') throw new Error('not an SSH signature');
    const version = r.u32();
    if (version !== 1) throw new Error('unsupported sshsig version ' + version);
    const pub = r.str(), namespace = dec.decode(r.str()), reserved = r.str(), hashAlg = dec.decode(r.str()), sigBlob = r.str();
    const pr = reader(pub), keyType = dec.decode(pr.str()), keyBytes = pr.str();
    const sr = reader(sigBlob), sigType = dec.decode(sr.str()), sig = sr.str();
    return { pub, keyType, keyBytes, namespace, reserved, hashAlg, sigType, sig };
  }

  function parsePubLine(line) {
    const parts = line.trim().split(/\s+/);
    if (parts.length < 2) throw new Error('not a public key line');
    const blob = b64(parts[1]);
    const r = reader(blob), keyType = dec.decode(r.str()), keyBytes = r.str();
    return { type: parts[0], blob, keyType, keyBytes };
  }

  // -> { state: 'VERIFIED' | 'UNSIGNED' | 'FAIL', reason }
  async function verifyTip(count, tip, armoredSig, pubLine) {
    if (!armoredSig) return { state: 'UNSIGNED', reason: 'no signature file' };
    let sig, pub;
    try { sig = parseSshSig(armoredSig); pub = parsePubLine(pubLine); }
    catch (e) { return { state: 'FAIL', reason: 'signature unreadable: ' + e.message }; }
    if (sig.namespace !== 'andy-chain-tip') return { state: 'FAIL', reason: 'signature namespace is "' + sig.namespace + '", not andy-chain-tip' };
    if (sig.keyType !== 'ssh-ed25519' || sig.sigType !== 'ssh-ed25519' || pub.keyType !== 'ssh-ed25519')
      return { state: 'FAIL', reason: 'not an ed25519 signature or key' };
    if (!same(sig.keyBytes, pub.keyBytes)) return { state: 'FAIL', reason: 'signed by a different key than andy-chain-signing.pub' };
    if (sig.hashAlg !== 'sha512' && sig.hashAlg !== 'sha256') return { state: 'FAIL', reason: 'unknown hash algorithm ' + sig.hashAlg };
    const message = enc.encode('andy-chain-tip v1\ncount=' + count + '\ntip=' + tip + '\n');
    let key;
    try { key = await subtle.importKey('raw', sig.keyBytes, { name: 'Ed25519' }, false, ['verify']); }
    catch (e) { return { state: 'UNSIGNED', reason: 'signature present but not checked: this browser has no Ed25519 in WebCrypto' }; }
    const h = new Uint8Array(await subtle.digest(sig.hashAlg === 'sha512' ? 'SHA-512' : 'SHA-256', message));
    const signed = concat([enc.encode('SSHSIG'), sshString(enc.encode(sig.namespace)), sshString(sig.reserved), sshString(enc.encode(sig.hashAlg)), sshString(h)]);
    let ok = false;
    try { ok = await subtle.verify({ name: 'Ed25519' }, key, sig.sig, signed); }
    catch (e) { return { state: 'UNSIGNED', reason: 'signature present but not checked: ' + e.message }; }
    return ok ? { state: 'VERIFIED', reason: 'chain tip (' + count + ' receipts) signed by Andy\'s chain key (andy-chain-signing.pub)' }
              : { state: 'FAIL', reason: 'the signature does not match this chain\'s tip (' + count + ' receipts)' };
  }

  // Flip one letter inside one receipt's summary, like the viewer's "Flip one byte":
  // the line stays valid JSON and only the hash stops recomputing. Returns new lines.
  function flipOneByte(lines, idx) {
    const rows = lines.slice();
    const line = rows[idx];
    const m = line.indexOf('"summary":"');
    let j = m >= 0 ? m + 11 : 0;
    while (j < line.length && !/[A-Za-z]/.test(line[j])) j++;
    if (j >= line.length) return null;
    const before = line[j];
    let after = before.toLowerCase() !== 'x' ? 'X' : 'Y';
    if (before === before.toLowerCase()) after = after.toLowerCase();
    rows[idx] = line.slice(0, j) + after + line.slice(j + 1);
    return rows;
  }

  root.AndyVerify = { GENESIS, splitHash, sha256hex, verifyChain, parseSshSig, parsePubLine, verifyTip, flipOneByte };
})(typeof window !== 'undefined' ? window : globalThis);
