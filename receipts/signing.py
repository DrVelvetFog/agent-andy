"""Signing with Andy's dedicated Ed25519 key, via the system ssh-keygen (-Y sign /
-Y verify). Stdlib only: no crypto library, no shared secret. Anyone with the
public key in data/andy-chain-signing.pub can check a signature; only the holder
of the private key can make one.

ADDITIVE: the receipt format, genesis, and the hash verifier are unchanged. A
chain's signature lives in a sidecar file next to it (<chain>.sig); an earned
answer carries its own signature in a "signature" field.

What gets signed:
  * a chain's TIP — the receipt count and the last receipt's hash (tip_message).
    Because every receipt commits to the one before it, signing the tip vouches
    for the whole chain; a rewrite, an append, or a truncated tail no longer
    matches the signed tip. The tip is re-signed after EVERY append (the trigger),
    so a signed chain is always signed up to its last receipt.
  * each earned answer in data/confirmed_secondary.json, ON ITS OWN, when the
    owner approves it: the signature covers entry_message(entry), the entry
    without its "signature" field in canonical JSON (sorted keys, no spaces,
    UTF-8; the same encoding receipts use). Revoking, deleting, or tampering
    with one entry affects only that entry. This replaced an earlier
    whole-file signature, under which any hand edit staged every entry.

Three states, never conflated:
  VERIFIED  the signature checks against Andy's public key
  UNSIGNED  no signature, or it could not be checked (no ssh-keygen, no public
            key): the content is still hash-checked but NOT authenticated
  FAIL      a signature is present and does not verify

A signature proves only that the holder of Andy's signing key signed that tip or
entry at that time; it does not prove the content is true.

Fail closed: no key, a key ssh-keygen can't use, or any signing error means no
signature is written (and a stale one is removed), so the result reads UNSIGNED,
never signed.

The private key path comes from ANDY_CHAIN_SIGNING_KEY (start-andy.sh sets it
when ~/.ssh/id_ed25519_andy_chain exists); unset means nothing is signed. The
public key defaults to data/andy-chain-signing.pub; ANDY_CHAIN_SIGNING_PUB
overrides it, which the tests use with a throwaway key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import filelock

ROOT = Path(__file__).resolve().parent.parent
PUBKEY_FILE = ROOT / "data" / "andy-chain-signing.pub"

VERIFIED, UNSIGNED, FAIL = "VERIFIED", "UNSIGNED", "FAIL"
CHAIN_NAMESPACE = "andy-chain-tip"
ENTRY_NAMESPACE = "andy-earned-answer"
_PRINCIPAL = "andy"
_TIMEOUT = 10


def signing_key() -> Path | None:
    """The private key to sign with, or None (nothing gets signed)."""
    p = os.environ.get("ANDY_CHAIN_SIGNING_KEY", "").strip()
    if not p:
        return None
    path = Path(p).expanduser()
    return path if path.is_file() else None


def public_key() -> Path:
    p = os.environ.get("ANDY_CHAIN_SIGNING_PUB", "").strip()
    return Path(p).expanduser() if p else PUBKEY_FILE


def sig_path(path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".sig")


def tip_message(count: int, tip_hash: str) -> bytes:
    """The exact bytes a chain-tip signature covers."""
    return f"andy-chain-tip v1\ncount={count}\ntip={tip_hash}\n".encode("ascii")


def _run(args: list[str], data: bytes) -> subprocess.CompletedProcess | None:
    # A new session has no controlling terminal, so ssh-keygen can never sit
    # waiting on a passphrase prompt inside the server.
    try:
        return subprocess.run(args, input=data, capture_output=True, timeout=_TIMEOUT,
                              start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        return None


def sign_bytes(data: bytes, namespace: str) -> str | None:
    """An armored SSH signature over data, or None if signing isn't possible."""
    key = signing_key()
    if key is None or shutil.which("ssh-keygen") is None:
        return None
    r = _run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", namespace], data)
    if r is None or r.returncode != 0 or b"BEGIN SSH SIGNATURE" not in r.stdout:
        return None
    return r.stdout.decode("ascii")


def verify_bytes(data: bytes, signature: str, namespace: str) -> tuple[str, str]:
    """(state, reason) for a signature over data, checked against Andy's public key."""
    pub = public_key()
    if shutil.which("ssh-keygen") is None:
        return UNSIGNED, "signature present but not checked: ssh-keygen not found"
    try:
        key_line = pub.read_text(encoding="utf-8").split("\n")[0].strip()
    except OSError:
        return UNSIGNED, f"signature present but not checked: no public key at {pub.name}"
    parts = key_line.split()
    if len(parts) < 2:
        return UNSIGNED, f"signature present but not checked: {pub.name} is not a public key"
    with tempfile.TemporaryDirectory() as d:
        allowed, sig = Path(d) / "allowed_signers", Path(d) / "sig"
        allowed.write_text(f"{_PRINCIPAL} {parts[0]} {parts[1]}\n", encoding="utf-8")
        sig.write_text(signature, encoding="ascii")
        r = _run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", _PRINCIPAL,
                  "-n", namespace, "-s", str(sig)], data)
    if r is None:
        return UNSIGNED, "signature present but not checked: ssh-keygen did not run"
    if r.returncode != 0:
        return FAIL, "signature does not verify against Andy's public key"
    return VERIFIED, "signed by Andy's chain key"


def _write_sig(path: Path, signature: str | None) -> bool:
    """Write the sidecar atomically, or remove a stale one when there's nothing to
    write, so an old signature never stands in for new content."""
    sp = sig_path(path)
    if signature is None:
        sp.unlink(missing_ok=True)
        return False
    tmp = sp.with_name(sp.name + ".tmp")
    tmp.write_text(signature, encoding="ascii")
    os.replace(tmp, sp)
    return True


def sign_tip(path, count: int, tip_hash: str) -> bool:
    """Sign a chain's tip into <chain>.sig. Called after every append."""
    return _write_sig(Path(path), sign_bytes(tip_message(count, tip_hash), CHAIN_NAMESPACE))


def entry_message(entry: dict) -> bytes:
    """The exact bytes an earned-answer signature covers: the entry without its
    "signature" field, in canonical JSON (sorted keys, no spaces, UTF-8)."""
    from .chain import canonical   # deferred: chain imports this module
    return canonical({k: v for k, v in entry.items() if k != "signature"})


def sign_entry(entry: dict) -> str | None:
    """A signature for one earned answer, or None if signing isn't possible."""
    return sign_bytes(entry_message(entry), ENTRY_NAMESPACE)


def _read_sig(path: Path) -> str | None:
    try:
        return sig_path(path).read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None


def verify_tip(path, count: int, tip_hash: str) -> tuple[str, str]:
    """(state, reason) for a chain whose hashes already verified, given its
    receipt count and last receipt hash."""
    return _check_tip(count, tip_hash, _read_sig(Path(path)))


def _check_tip(count: int, tip_hash: str, signature: str | None) -> tuple[str, str]:
    if signature is None:
        return UNSIGNED, "no signature file"
    state, reason = verify_bytes(tip_message(count, tip_hash), signature, CHAIN_NAMESPACE)
    if state == FAIL:
        reason = f"the signature does not match this chain's tip ({count} receipts)"
    elif state == VERIFIED:
        reason = f"chain tip ({count} receipts) {reason}"
    return state, reason


def chain_signature(path) -> tuple[str, str]:
    """(state, reason) for a chain file. Call it only after verify_chain passed: it
    reads the count and tip from the file and checks the sidecar against them. The
    chain and its .sig are read together under the shared lock, so a writer can
    never slip a new receipt in between them; ssh-keygen runs after the lock."""
    try:
        with filelock.shared_if_present(path):
            lines = [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
            tip = json.loads(lines[-1])["hash"]
            signature = _read_sig(Path(path))
    except (OSError, UnicodeDecodeError, IndexError, KeyError, TypeError, ValueError,
            filelock.LockTimeout):
        return FAIL, "chain unreadable for the signature check"
    return _check_tip(len(lines), tip, signature)


def verify_entry(entry) -> tuple[str, str]:
    """(state, reason) for one earned answer's own signature."""
    if not isinstance(entry, dict):
        return FAIL, "entry is not an object"
    signature = entry.get("signature")
    if not signature:
        return UNSIGNED, "no signature on this entry"
    if not isinstance(signature, str) or not signature.isascii():
        return FAIL, "signature is not an SSH signature"
    return verify_bytes(entry_message(entry), signature, ENTRY_NAMESPACE)
