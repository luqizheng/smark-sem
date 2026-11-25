#!/usr/bin/env python3
"""Verify deterministic D-04 Ed25519/HTTP and WSS test vectors.

Only TEST-ONLY fixture keys are used. This is protocol conformance testing,
not production key handling or a full HTTP Message Signatures implementation.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
import struct
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

def jcs_string(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("RFC 8785 rejects unpaired UTF-16 surrogates")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def jcs_number(value) -> str:
    # RFC 8785 numbers use ECMAScript-compatible IEEE-754 binary64 values.
    # Python's repr(float) supplies shortest round-trip digits; this function
    # applies ECMAScript's fixed/scientific notation thresholds and exponent form.
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("number outside finite IEEE-754 range") from exc
    if not math.isfinite(number):
        raise ValueError("RFC 8785 rejects non-finite numbers")
    if number == 0:
        return "0"

    rendered = repr(number).lower()
    sign = ""
    if rendered.startswith("-"):
        sign, rendered = "-", rendered[1:]
    if "e" in rendered:
        mantissa, exponent_text = rendered.split("e")
        exponent = int(exponent_text)
    else:
        mantissa, exponent = rendered, 0
    if "." in mantissa:
        integer, fraction = mantissa.split(".")
    else:
        integer, fraction = mantissa, ""
    digits = integer + fraction
    decimal_position = len(integer) + exponent
    while len(digits) > 1 and digits.startswith("0"):
        digits = digits[1:]
        decimal_position -= 1
    while len(digits) > 1 and digits.endswith("0"):
        digits = digits[:-1]

    # ECMAScript uses fixed notation for 1e-6 <= abs(number) < 1e21.
    if 0 < decimal_position <= 21:
        if len(digits) <= decimal_position:
            body = digits + "0" * (decimal_position - len(digits))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
    elif -5 <= decimal_position <= 0:
        body = "0." + "0" * (-decimal_position) + digits
    else:
        scientific_exponent = decimal_position - 1
        body = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
        body += "e" + ("+" if scientific_exponent >= 0 else "") + str(scientific_exponent)
    return sign + body


def jcs_canonicalize(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return jcs_string(value)
    if isinstance(value, (int, float)):
        return jcs_number(value)
    if isinstance(value, list):
        return "[" + ",".join(jcs_canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError("RFC 8785 object property names must be strings")
            if any(0xD800 <= ord(char) <= 0xDFFF for char in key):
                raise ValueError("RFC 8785 rejects unpaired surrogate property names")
        # RFC 8785 sorts property names by unsigned UTF-16 code units, not
        # Python Unicode code points.
        keys = sorted(value.keys(), key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(
            jcs_string(key) + ":" + jcs_canonicalize(value[key]) for key in keys
        ) + "}"
    raise TypeError("value is not representable as a JSON value")

try:
    json.loads('{"a":1,"\u0061":2}', object_pairs_hook=reject_duplicate_object_members)
except ValueError:
    pass
else:
    raise AssertionError("duplicate JSON member with escaped-equivalent name was accepted")


# Independent Python RFC 8785 edge vectors. These intentionally mirror the
# Node verifier's UTF-16 ordering and Appendix B IEEE-754 cases.
unicode_input = r'{"\u20ac":"Euro Sign","\r":"Carriage Return","\ufb33":"Hebrew Letter Dalet With Dagesh","1":"One","\ud83d\ude00":"Emoji: Grinning Face","\u0080":"Control","\u00f6":"Latin Small Letter O With Diaeresis"}'
unicode_expected = r'{"\r":"Carriage Return","1":"One","":"Control","ö":"Latin Small Letter O With Diaeresis","€":"Euro Sign","😀":"Emoji: Grinning Face","דּ":"Hebrew Letter Dalet With Dagesh"}'
assert jcs_canonicalize(json.loads(unicode_input, object_pairs_hook=reject_duplicate_object_members)) == unicode_expected, "RFC 8785 UTF-16 property ordering mismatch"

number_vectors = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
]
for number_hex, expected_number in number_vectors:
    number = struct.unpack(">d", bytes.fromhex(number_hex))[0]
    assert jcs_canonicalize(number) == expected_number, "RFC 8785 IEEE-754 vector mismatch: " + number_hex

for number_text, expected_number in [
    ("-0", "0"),
    ("1e-6", "0.000001"),
    ("1e-7", "1e-7"),
    ("1e20", "100000000000000000000"),
    ("1e21", "1e+21"),
]:
    assert jcs_canonicalize(json.loads(number_text)) == expected_number, "RFC 8785 exponent boundary mismatch: " + number_text

string_escape_input = r'{"text":"quote:\" slash:/ reverse:\\ unicode:é"}'
string_escape_expected = r'{"text":"quote:\" slash:/ reverse:\\ unicode:é"}'
assert jcs_canonicalize(json.loads(string_escape_input, object_pairs_hook=reject_duplicate_object_members)) == string_escape_expected, "RFC 8785 quote/reverse-solidus/slash/non-ASCII escaping mismatch"

nested_input = r'{"z":[{"b":2,"a":1},3],"a":"\u000f\nplain"}'
nested_expected = r'{"a":"\u000f\nplain","z":[{"a":1,"b":2},3]}'
assert jcs_canonicalize(json.loads(nested_input, object_pairs_hook=reject_duplicate_object_members)) == nested_expected, "RFC 8785 recursive sorting/array order/control escaping mismatch"

try:
    json.loads(r'{"outer":{"a":1,"\u0061":2}}', object_pairs_hook=reject_duplicate_object_members)
except ValueError:
    pass
else:
    raise AssertionError("nested duplicate object member was accepted")

for invalid_json in ("{",):
    try:
        json.loads(invalid_json, object_pairs_hook=reject_duplicate_object_members)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("malformed JSON was accepted")
for invalid_json in (r'{"x":"\ud800"}', r'{"x":"\udc00"}'):
    try:
        jcs_canonicalize(json.loads(invalid_json, object_pairs_hook=reject_duplicate_object_members))
    except ValueError:
        pass
    else:
        raise AssertionError("unpaired surrogate was accepted")
try:
    jcs_canonicalize(json.loads(r'{"\ud800":1}', object_pairs_hook=reject_duplicate_object_members))
except ValueError:
    pass
else:
    raise AssertionError("unpaired surrogate property name was accepted")

for invalid_number in ("NaN", "Infinity", "-Infinity", "1e400"):
    try:
        jcs_canonicalize(json.loads(invalid_number))
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite number was accepted: " + invalid_number)

print("python-jcs-edge-ok: UTF-16 ordering, Appendix B IEEE-754 values, boundaries, and invalid inputs")

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
for name in ("http_response", "http_error_409", "http_error_404", "http_snapshot_200", "http_304", "http_callback_ack", "http_callback_error_404"):
    vector = data[name]
    request = vector["request"]
    response = vector["response"]
    request_body = request["body"].encode("utf-8")
    expected_request_digest = "sha-256=:" + base64.b64encode(hashlib.sha256(request_body).digest()).decode("ascii") + ":"
    assert expected_request_digest == request["content_digest"], name + " associated request Content-Digest mismatch"
    response_body = response["body"].encode("utf-8")
    expected_response_digest = "sha-256=:" + base64.b64encode(hashlib.sha256(response_body).digest()).decode("ascii") + ":"
    assert expected_response_digest == response["content_digest"], name + " response Content-Digest mismatch"
    if name in ("http_callback_ack", "http_callback_error_404"):
        if name == "http_callback_error_404":
            error_body = json.loads(response["body"])
            assert response["status"] == 404 and error_body["error"]["code"] == "EXECUTION_NOT_FOUND", "signed callback 404 fixture must be a structured not-found error"
        assert response["event_id"] == request["event_id"] == request["idempotency_key"], "callback ACK correlation must equal authenticated event_id"
        assert response["event_id"] != request["message_id"], "callback event_id must remain distinct from transport message_id"
        pairs = [
            ('"@status"', str(response["status"])),
            ('"content-digest";sf', response["content_digest"]),
            ('"x-sem-event-id"', response["event_id"]),
            ('"content-type"', response["content_type"]),
            ('"@method";req', request["method"]),
            ('"@authority";req', request["authority"]),
            ('"@path";req', request["path"]),
            ('"content-digest";req;sf', request["content_digest"]),
        ]
    elif name in ("http_response", "http_error_409", "http_error_404", "http_snapshot_200"):
        if name in ("http_error_409", "http_error_404"):
            error_body = json.loads(response["body"])
            expected_status, expected_code = (409, "IDEMPOTENCY_CONFLICT") if name == "http_error_409" else (404, "EXECUTION_NOT_FOUND")
            assert response["status"] == expected_status and error_body["error"]["code"] == expected_code, "signed error fixture status/code mismatch"
        assert response["request_id"] == request["request_id"], name + " response correlation mismatch"
        if name == "http_snapshot_200":
            assert response["status"] == 200 and response["etag"], "snapshot 200 must carry a signed ETag"
        
        assert response["request_id"] != request["message_id"], name + " response correlation must use request_id, not message_id"
        if name == "http_snapshot_200":
            pairs = [
                ('"@status"', str(response["status"])),
                ('"content-digest";sf', response["content_digest"]),
                ('"x-sem-request-id"', response["request_id"]),
                ('"etag"', response["etag"]),
                ('"content-type"', response["content_type"]),
                ('"@method";req', request["method"]),
                ('"@authority";req', request["authority"]),
                ('"@path";req', request["path"]),
                ('"content-digest";req;sf', request["content_digest"]),
            ]
        else:
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
        assert response["request_id"] == request["request_id"], name + " response correlation mismatch"
        assert response["request_id"] != request["message_id"], name + " response correlation must use request_id, not message_id"
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

    # A signed response is bound to the exact originating request context.
    for component_name, wrong_value in (
        ('"@method";req', "PATCH"),
        ('"@authority";req', "other.internal.example"),
        ('"@path";req', request["path"] + "/different"),
        ('"content-digest";req;sf', "sha-256=:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=:"),
    ):
        wrong_context_pairs = list(pairs)
        component_index = next(i for i, pair in enumerate(wrong_context_pairs) if pair[0] == component_name)
        wrong_context_pairs[component_index] = (wrong_context_pairs[component_index][0], wrong_value)
        wrong_context_base = "\n".join(f"{component}: {value}" for component, value in wrong_context_pairs)
        wrong_context_base += f'\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_context_base.encode("ascii")), name + " response accepted a different request context"
    if name == "http_snapshot_200":
        wrong_etag_pairs = list(pairs)
        etag_index = next(i for i, pair in enumerate(wrong_etag_pairs) if pair[0] == '"etag"')
        wrong_etag_pairs[etag_index] = ('"etag"', '"tampered-snapshot-v5"')
        wrong_etag_base = "\\n".join(f"{component}: {value}" for component, value in wrong_etag_pairs)
        wrong_etag_base += f'\\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_etag_base.encode("ascii")), "snapshot 200 signature accepted a tampered ETag"
    if name == "http_304":
        wrong_304_etag_pairs = list(pairs)
        etag_index = next(i for i, pair in enumerate(wrong_304_etag_pairs) if pair[0] == '"etag"')
        wrong_304_etag_pairs[etag_index] = ('"etag"', '"tampered-snapshot-v5"')
        wrong_304_etag_base = "\\n".join(f"{component}: {value}" for component, value in wrong_304_etag_pairs)
        wrong_304_etag_base += f'\\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_304_etag_base.encode("ascii")), "304 signature accepted a tampered ETag"
        wrong_validator_pairs = list(pairs)
        wrong_validator_pairs[8] = ('"if-none-match";req', '"different-validator"')
        wrong_validator_base = "\n".join(f"{component}: {value}" for component, value in wrong_validator_pairs)
        wrong_validator_base += f'\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_validator_base.encode("ascii")), "304 response accepted a different If-None-Match context"

    if name in ("http_response", "http_error_409", "http_error_404", "http_snapshot_200"):
        wrong_pairs = list(pairs)
        wrong_pairs[2] = ('"x-sem-request-id"', request["message_id"])
        wrong_base = "\n".join(f"{component}: {value}" for component, value in wrong_pairs)
        wrong_base += f'\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_base.encode("ascii")), name + " signature unexpectedly accepted message_id as request correlation"

    if name in ("http_callback_ack", "http_callback_error_404"):
        wrong_pairs = list(pairs)
        wrong_pairs[2] = ('"x-sem-event-id"', request["message_id"])
        wrong_base = "\n".join(f"{component}: {value}" for component, value in wrong_pairs)
        wrong_base += f'\n"@signature-params": {vector["signature_params"]}'
        assert not verify(response_pub, response_sig, wrong_base.encode("ascii")), "callback response signature unexpectedly accepted wrong event correlation"
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
assert data["http_callback_ack"]["request"]["body"] == callback["expected"]["event_envelope_jcs_utf8"], "callback ACK HTTP vector must use the shared canonical event-envelope bytes"
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

