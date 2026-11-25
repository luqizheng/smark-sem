#!/usr/bin/env python3
"""Verify deterministic D-04 Ed25519/HTTP and WSS test vectors.

Only TEST-ONLY fixture keys are used. This is protocol conformance testing,
not production key handling or a full HTTP Message Signatures implementation.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/protocol/fixtures/crypto-vectors-v1.json"

def b64d(value: str) -> bytes:
    return base64.b64decode(value)

def verify(public: bytes, signature: bytes, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
        return True
    except InvalidSignature:
        return False

data = json.loads(FIXTURE.read_text(encoding="utf-8"))
http = data["http"]
body = http["body"].encode("utf-8")
digest = "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii") + ":"
assert digest == http["content_digest"], "HTTP Content-Digest vector mismatch"

components = [
    ('"@method"', http["method"]),
    ('"@authority"', http["authority"]),
    ('"@path"', http["path"]),
    ('"content-digest"', http["content_digest"]),
    ('"content-type"', http["content_type"]),
    ('"idempotency-key"', http["idempotency_key"]),
    ('"x-sem-message-id"', http["message_id"]),
]
signature_base = "\n".join(f"{name}: {value}" for name, value in components)
signature_base += f'\n"@signature-params": {http["signature_params"]}'
assert signature_base == http["signature_base"], "HTTP signature-base canonicalization mismatch"

http_pub = b64d(http["public_key_base64"])
http_sig = b64d(http["signature_base64"])
assert verify(http_pub, http_sig, signature_base.encode("ascii")), "HTTP Ed25519 signature failed"
assert not verify(http_pub, http_sig, signature_base.replace("POST", "PUT", 1).encode("ascii")), "HTTP method mutation unexpectedly verified"
assert not verify(http_pub, http_sig, (signature_base + " ").encode("ascii")), "HTTP signature-base mutation unexpectedly verified"
for changed in [
    signature_base.replace("sem.internal.example", "evil.internal.example", 1),
    signature_base.replace("/internal/sem/v1/executions", "/internal/sem/v1/other", 1),
    signature_base.replace("application/json", "text/plain", 1),
    signature_base.replace(http["idempotency_key"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 1),
]:
    assert not verify(http_pub, http_sig, changed.encode("ascii")), "HTTP covered-component mutation unexpectedly verified"
mutated_digest = "sha-256=:" + base64.b64encode(hashlib.sha256(body + b" ").digest()).decode("ascii") + ":"
assert not verify(http_pub, http_sig, signature_base.replace(http["content_digest"], mutated_digest).encode("ascii")), "HTTP digest-header mutation unexpectedly verified"
assert digest != "sha-256=:" + base64.b64encode(hashlib.sha256(body + b" ").digest()).decode("ascii") + ":", "Body mutation did not change digest"

rfc = data["rfc9421_official_ed25519"]
rfc_pub = b64d(rfc["public_key_base64"])
rfc_sig = b64d(rfc["signature_base64"])
assert verify(rfc_pub, rfc_sig, rfc["signature_base"].encode("ascii")), "Official RFC 9421 Ed25519 vector failed"
rfc_seed = base64.urlsafe_b64decode(rfc["test_private_seed_base64url"] + "==")
rfc_private = Ed25519PrivateKey.from_private_bytes(rfc_seed)
assert rfc_private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == rfc_pub
assert rfc_private.sign(rfc["signature_base"].encode("ascii")) == rfc_sig

wss = data["wss"]
transcript = wss["transcript"]
# This fixture intentionally uses only ASCII strings and an integer. For this
# restricted fixture shape, sorted compact JSON is byte-identical to RFC 8785 JCS.
jcs = json.dumps(transcript, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert jcs == wss["jcs_utf8"], "WSS JCS serialization mismatch"
message = wss["domain_separation_prefix"].encode("ascii") + jcs.encode("utf-8")
wss_pub = b64d(wss["public_key_base64"])
wss_sig = b64d(wss["signature_base64"])
assert verify(wss_pub, wss_sig, message), "WSS Ed25519 transcript signature failed"

mutated = dict(transcript)
mutated["runner_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
mutated_jcs = json.dumps(mutated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert not verify(wss_pub, wss_sig, wss["domain_separation_prefix"].encode("ascii") + mutated_jcs.encode("utf-8")), "WSS runner_id mutation unexpectedly verified"
assert not verify(wss_pub, wss_sig, jcs.encode("utf-8")), "WSS domain-separation removal unexpectedly verified"
for field, value in [
    ("audience", "other.internal.example"),
    ("authority", "other.internal.example"),
    ("challenge_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    ("protocol", "sem.runner.v2"),
]:
    changed = dict(transcript)
    changed[field] = value
    changed_jcs = json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert not verify(wss_pub, wss_sig, wss["domain_separation_prefix"].encode("ascii") + changed_jcs.encode("utf-8")), f"WSS {field} mutation unexpectedly verified"

# Recreate public keys from the test-only private seeds to ensure fixtures
# are internally consistent and signatures are reproducible.
http_seed = base64.urlsafe_b64decode(http["test_private_seed_base64"] + "==")
http_private = Ed25519PrivateKey.from_private_bytes(http_seed)
assert http_private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == http_pub
assert http_private.sign(signature_base.encode("ascii")) == http_sig
wss_seed = bytes.fromhex(wss["test_private_seed_hex"])
wss_private = Ed25519PrivateKey.from_private_bytes(wss_seed)
assert wss_private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == wss_pub
assert wss_private.sign(message) == wss_sig

print("crypto-vectors-ok: official RFC 9421 Appendix B.2.6 Ed25519 vector")
print("crypto-vectors-ok: HTTP Content-Digest + profile-specific RFC 9421 Ed25519 signature")
print("crypto-vectors-ok: WSS RFC 8785 JCS + domain-separated Ed25519 proof")
print("negative-vectors-ok: HTTP method/authority/path/content-type/idempotency/digest mutations")
print("negative-vectors-ok: WSS runner_id/audience/authority/challenge/protocol/domain-prefix mutations")
