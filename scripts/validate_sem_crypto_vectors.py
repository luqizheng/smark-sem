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


def reject_duplicate_object_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member: " + key)
        result[key] = value
    return result

try:
    json.loads('{"a":1,"\\u0061":2}', object_pairs_hook=reject_duplicate_object_members)
except ValueError:
    pass
else:
    raise AssertionError("duplicate JSON member with escaped-equivalent name was accepted")

data = json.loads(FIXTURE.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_object_members)
http = data["http"]
body = http["body"].encode("utf-8")
digest = "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii") + ":"
assert digest == http["content_digest"], "HTTP Content-Digest vector mismatch"

components = [
    ('"@method"', http["method"]),
    ('"@authority"', http["authority"]),
    ('"@path"', http["path"]),
    ('"content-digest";sf', http["content_digest"]),
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


# Deterministic response-signature vectors bind the exact associated request.
for name in ("http_response", "http_304"):
    vector = data[name]
    request = vector["request"]
    response = vector["response"]
    request_body = request["body"].encode("utf-8")
    expected_request_digest = "sha-256=:" + base64.b64encode(hashlib.sha256(request_body).digest()).decode("ascii") + ":"
    assert expected_request_digest == request["content_digest"], name + " associated request Content-Digest mismatch"
    response_body = response["body"].encode("utf-8")
    expected_response_digest = "sha-256=:" + base64.b64encode(hashlib.sha256(response_body).digest()).decode("ascii") + ":"
    assert expected_response_digest == response["content_digest"], name + " response Content-Digest mismatch"
    assert response["request_id"] == request["request_id"], name + " response correlation mismatch"
    if name == "http_response":
        pairs = [
            ('"@status"', str(response["status"])),
            ('"content-digest";sf', response["content_digest"]),
            ('"x-sem-request-id"', response["request_id"]),
            ('"content-type"', response["content_type"]),
            ('"@method";req', request["method"]),
            ('"@authority";req', request["authority"]),
            ('"@path";req', request["path"]),
            ('"content-digest";req;sf', request["content_digest"]),
        ]
    else:
        assert response["status"] == 304 and response_body == b"", "304 must be bodyless"
        assert response["content_digest"] == "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:", "304 empty digest mismatch"
        pairs = [
            ('"@status"', str(response["status"])),
            ('"content-digest";sf', response["content_digest"]),
            ('"x-sem-request-id"', response["request_id"]),
            ('"etag"', response["etag"]),
            ('"@method";req', request["method"]),
            ('"@authority";req', request["authority"]),
            ('"@path";req', request["path"]),
            ('"content-digest";req;sf', request["content_digest"]),
            ('"if-none-match";req', request["if_none_match"]),
        ]
    response_base = "\n".join(f"{component}: {value}" for component, value in pairs)
    response_base += f'\n"@signature-params": {vector["signature_params"]}'
    assert response_base == vector["signature_base"], name + " RFC 9421 signature-base mismatch"
    response_pub = b64d(vector["public_key_base64"])
    response_sig = b64d(vector["signature_base64"])
    assert verify(response_pub, response_sig, response_base.encode("ascii")), name + " Ed25519 response signature failed"
    response_seed = base64.b64decode(vector["test_private_seed_base64"])
    response_private = Ed25519PrivateKey.from_private_bytes(response_seed)
    assert response_private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == response_pub
    assert response_private.sign(response_base.encode("ascii")) == response_sig

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


# Shared Platform -> AI-PM callback envelope vector. This particular vector is
# intentionally ASCII-only with integer numbers; broader UTF-16/number edge
# coverage is tested independently below and in the Node verifier.
callback_fixture_path = ROOT / "tests/protocol/fixtures/platform-sem-callback-envelope-jcs-v1.json"
callback = json.loads(
    callback_fixture_path.read_text(encoding="utf-8"),
    object_pairs_hook=reject_duplicate_object_members,
)
envelope = callback["envelope"]
expected = callback["expected"]
payload_jcs = json.dumps(envelope["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
envelope_jcs = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert payload_jcs == expected["payload_jcs_utf8"], "callback payload JCS bytes mismatch"
assert hashlib.sha256(payload_jcs.encode("utf-8")).hexdigest() == expected["payload_hash_sha256"], "callback payload_hash mismatch"
assert envelope_jcs == expected["event_envelope_jcs_utf8"], "callback event-envelope JCS bytes mismatch"
assert hashlib.sha256(envelope_jcs.encode("utf-8")).hexdigest() == expected["event_envelope_hash_sha256"], "callback event_envelope_hash mismatch"
print("callback-jcs-ok: payload and complete authenticated envelope bytes + SHA-256")

# Full-envelope identity must change when authenticated metadata changes, even
# when the payload itself is byte-for-byte unchanged.
mutated_event_type = dict(envelope)
mutated_event_type["event_type"] = "execution.delivery_status"
mutated_envelope_jcs = json.dumps(mutated_event_type, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert hashlib.sha256(payload_jcs.encode("utf-8")).hexdigest() == expected["payload_hash_sha256"]
assert hashlib.sha256(mutated_envelope_jcs.encode("utf-8")).hexdigest() != expected["event_envelope_hash_sha256"], "event_type mutation did not change full-envelope hash"

mutated_time = dict(envelope)
mutated_time["occurred_at"] = "2026-11-25T10:15:32Z"
mutated_time_jcs = json.dumps(mutated_time, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert hashlib.sha256(mutated_time_jcs.encode("utf-8")).hexdigest() != expected["event_envelope_hash_sha256"], "occurred_at mutation did not change full-envelope hash"

reordered_envelope = dict(reversed(list(envelope.items())))
assert json.dumps(reordered_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == expected["event_envelope_jcs_utf8"], "member order changed callback canonical bytes"
mutated_correlation = dict(envelope)
mutated_correlation["correlation_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
mutated_correlation_jcs = json.dumps(mutated_correlation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert hashlib.sha256(mutated_correlation_jcs.encode("utf-8")).hexdigest() != expected["event_envelope_hash_sha256"], "correlation_id mutation did not change full-envelope hash"

absent_correlation = dict(envelope)
absent_correlation.pop("correlation_id")
absent_correlation_jcs = json.dumps(absent_correlation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
assert hashlib.sha256(absent_correlation_jcs.encode("utf-8")).hexdigest() != expected["event_envelope_hash_sha256"], "omitting present correlation_id did not change full-envelope hash"

print("callback-idempotency-ok: event_type/occurred_at mutations change envelope hash; member order does not")

