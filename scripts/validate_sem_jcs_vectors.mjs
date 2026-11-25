#!/usr/bin/env node
/**
 * Independent Node.js verifier for the D-04 RFC 8785 / Ed25519 WSS vector.
 * Fixture transcript is restricted to ASCII strings and integer values so
 * JSON.stringify + UTF-16 key ordering is byte-identical to RFC 8785 JCS.
 */
import fs from "node:fs";
import crypto from "node:crypto";

const fixture = JSON.parse(fs.readFileSync("tests/protocol/fixtures/crypto-vectors-v1.json", "utf8"));
const vector = fixture.wss;

function jcs(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(jcs).join(",") + "]";
  return "{" + Object.keys(value).sort().map(
    key => JSON.stringify(key) + ":" + jcs(value[key])
  ).join(",") + "}";
}

const canonical = jcs(vector.transcript);
if (canonical !== vector.jcs_utf8) {
  throw new Error("Node JCS bytes differ from the committed RFC 8785 transcript");
}
const prefix = Buffer.from(vector.domain_separation_prefix, "ascii");
const message = Buffer.concat([prefix, Buffer.from(canonical, "utf8")]);
const publicRaw = Buffer.from(vector.public_key_base64, "base64");
const publicDerPrefix = Buffer.from("302a300506032b6570032100", "hex");
const publicKey = crypto.createPublicKey({
  key: Buffer.concat([publicDerPrefix, publicRaw]),
  format: "der",
  type: "spki",
});
const signature = Buffer.from(vector.signature_base64, "base64");
if (!crypto.verify(null, message, publicKey, signature)) {
  throw new Error("Node Ed25519 verification of WSS transcript failed");
}

const seed = Buffer.from(vector.test_private_seed_hex, "hex");
const privateDerPrefix = Buffer.from("302e020100300506032b657004220420", "hex");
const privateKey = crypto.createPrivateKey({
  key: Buffer.concat([privateDerPrefix, seed]),
  format: "der",
  type: "pkcs8",
});
const reproduced = crypto.sign(null, message, privateKey);
if (!reproduced.equals(signature)) {
  throw new Error("Node Ed25519 reproduction differs from committed WSS signature");
}


// Cross-check the body-bearing response and conditional 304 vectors using
// Node's independent Ed25519 implementation and exact request context.
for (const name of ["http_response", "http_error_409", "http_error_404", "http_snapshot_200", "http_304", "http_callback_ack", "http_callback_error_404"]) {
  const vector = fixture[name];
  const request = vector.request;
  const response = vector.response;
  const requestBody = Buffer.from(request.body, "utf8");
  const requestDigest = "sha-256=:" + crypto.createHash("sha256").update(requestBody).digest("base64") + ":";
  if (requestDigest !== request.content_digest) throw new Error(name + " associated request Content-Digest mismatch");
  const responseBody = Buffer.from(response.body, "utf8");
  const responseDigest = "sha-256=:" + crypto.createHash("sha256").update(responseBody).digest("base64") + ":";
  if (responseDigest !== response.content_digest) throw new Error(name + " Content-Digest mismatch");
  let pairs;
  if (name === "http_callback_ack" || name === "http_callback_error_404") {
    if (name === "http_callback_error_404") {
      const errorBody = parseStrictJson(response.body);
      if (response.status !== 404 || errorBody.error?.code !== "EXECUTION_NOT_FOUND") {
        throw new Error("Signed callback 404 fixture must be a structured not-found error");
      }
    }
    if (response.event_id !== request.event_id || response.event_id !== request.idempotency_key) {
      throw new Error("Callback ACK correlation must equal authenticated event_id");
    }
    if (response.event_id === request.message_id) throw new Error("Callback event_id must remain distinct from transport message_id");
    pairs = [
      ['"@status"', String(response.status)],
      ['"content-digest";sf', response.content_digest],
      ['"x-sem-event-id"', response.event_id],
      ['"content-type"', response.content_type],
      ['"@method";req', request.method],
      ['"@authority";req', request.authority],
      ['"@path";req', request.path],
      ['"content-digest";req;sf', request.content_digest],
    ];
  } else if (name === "http_response" || name === "http_error_409" || name === "http_error_404" || name === "http_snapshot_200") {
    if (name === "http_error_409" || name === "http_error_404") {
      const errorBody = parseStrictJson(response.body);
      const expectedStatus = name === "http_error_409" ? 409 : 404;
      const expectedCode = name === "http_error_409" ? "IDEMPOTENCY_CONFLICT" : "EXECUTION_NOT_FOUND";
      if (response.status !== expectedStatus || errorBody.error?.code !== expectedCode) {
        throw new Error("Signed error fixture status/code mismatch");
      }
    }
    if (response.request_id !== request.request_id) throw new Error(name + " response correlation mismatch");
    if (response.request_id === request.message_id) throw new Error(name + " response correlation must use request_id, not message_id");
    if (name === "http_snapshot_200" && (response.status !== 200 || !response.etag)) {
      throw new Error("Snapshot 200 must carry a signed ETag");
    }
    if (name === "http_snapshot_200") {
      pairs = [
        ['"@status"', String(response.status)],
        ['"content-digest";sf', response.content_digest],
        ['"x-sem-request-id"', response.request_id],
        ['"etag"', response.etag],
        ['"content-type"', response.content_type],
        ['"@method";req', request.method],
        ['"@authority";req', request.authority],
        ['"@path";req', request.path],
        ['"content-digest";req;sf', request.content_digest],
      ];
    } else {
      pairs = [
        ['"@status"', String(response.status)],
        ['"content-digest";sf', response.content_digest],
        ['"x-sem-request-id"', response.request_id],
        ['"content-type"', response.content_type],
        ['"@method";req', request.method],
        ['"@authority";req', request.authority],
        ['"@path";req', request.path],
        ['"content-digest";req;sf', request.content_digest],
      ];
    }
  } else {
    if (response.request_id !== request.request_id) throw new Error(name + " response correlation mismatch");
    if (response.request_id === request.message_id) throw new Error(name + " response correlation must use request_id, not message_id");
    const emptyDigest = "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:";
    if (response.status !== 304 || responseBody.length !== 0 || response.content_digest !== emptyDigest) {
      throw new Error("304 must have empty content and the SHA-256 empty-content digest");
    }
    pairs = [
      ['"@status"', String(response.status)],
      ['"content-digest";sf', response.content_digest],
      ['"x-sem-request-id"', response.request_id],
      ['"etag"', response.etag],
      ['"@method";req', request.method],
      ['"@authority";req', request.authority],
      ['"@path";req', request.path],
      ['"content-digest";req;sf', request.content_digest],
      ['"if-none-match";req', request.if_none_match],
    ];
  }
  const responseBase = pairs.map(([component, value]) => component + ": " + value).join("\n")
    + '\n"@signature-params": ' + vector.signature_params;
  if (responseBase !== vector.signature_base) throw new Error(name + " RFC 9421 signature-base mismatch");
  const responsePublicRaw = Buffer.from(vector.public_key_base64, "base64");
  const responsePublicKey = crypto.createPublicKey({
    key: Buffer.concat([publicDerPrefix, responsePublicRaw]),
    format: "der",
    type: "spki",
  });
  const responseSignature = Buffer.from(vector.signature_base64, "base64");
  if (!crypto.verify(null, Buffer.from(responseBase, "ascii"), responsePublicKey, responseSignature)) {
    throw new Error(name + " Ed25519 response signature failed");
  }

  // A signed response is bound to the exact originating request context.
  for (const [componentName, wrongValue] of [
    ['"@method";req', "PATCH"],
    ['"@authority";req', "other.internal.example"],
    ['"@path";req', request.path + "/different"],
    ['"content-digest";req;sf', "sha-256=:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=:"],
  ]) {
    const wrongContextPairs = pairs.map(pair => [...pair]);
    const componentIndex = wrongContextPairs.findIndex(pair => pair[0] === componentName);
    wrongContextPairs[componentIndex][1] = wrongValue;
    const wrongContextBase = wrongContextPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrongContextBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error(name + " response accepted a different request context");
    }
  }
  if (name === "http_snapshot_200") {
    const wrongEtagPairs = pairs.map(pair => [...pair]);
    const etagIndex = wrongEtagPairs.findIndex(pair => pair[0] === '"etag"');
    wrongEtagPairs[etagIndex][1] = '"tampered-snapshot-v5"';
    const wrongEtagBase = wrongEtagPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrongEtagBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error("Snapshot 200 signature accepted a tampered ETag");
    }
  }
  if (name === "http_304") {
    const wrong304EtagPairs = pairs.map(pair => [...pair]);
    const etagIndex = wrong304EtagPairs.findIndex(pair => pair[0] === '"etag"');
    wrong304EtagPairs[etagIndex][1] = '"tampered-snapshot-v5"';
    const wrong304EtagBase = wrong304EtagPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrong304EtagBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error("304 signature accepted a tampered ETag");
    }
    const wrongValidatorPairs = pairs.map(pair => [...pair]);
    wrongValidatorPairs[8][1] = '"different-validator"';
    const wrongValidatorBase = wrongValidatorPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrongValidatorBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error("304 response accepted a different If-None-Match context");
    }
  }

  if (name === "http_response" || name === "http_error_409" || name === "http_error_404" || name === "http_snapshot_200") {
    const wrongPairs = pairs.map(pair => [...pair]);
    wrongPairs[2][1] = request.message_id;
    const wrongBase = wrongPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrongBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error(name + " signature accepted message_id as request correlation");
    }
  }
  if (name === "http_callback_ack" || name === "http_callback_error_404") {
    const wrongPairs = pairs.map(pair => [...pair]);
    wrongPairs[2][1] = request.message_id;
    const wrongBase = wrongPairs.map(([component, value]) => component + ": " + value).join("\\n")
      + '\\n"@signature-params": ' + vector.signature_params;
    if (crypto.verify(null, Buffer.from(wrongBase, "ascii"), responsePublicKey, responseSignature)) {
      throw new Error("Callback response signature accepted a mismatched X-SEM-Event-Id");
    }
  }
  const responseSeed = Buffer.from(vector.test_private_seed_base64, "base64");
  const responsePrivateKey = crypto.createPrivateKey({
    key: Buffer.concat([privateDerPrefix, responseSeed]),
    format: "der",
    type: "pkcs8",
  });
  if (!crypto.sign(null, Buffer.from(responseBase, "ascii"), responsePrivateKey).equals(responseSignature)) {
    throw new Error(name + " response signature reproduction failed");
  }
}

console.log("node-http-response-ok: signed 202, callback ACK 200 and conditional 304 bind their exact request contexts");

const rfc = fixture.rfc9421_official_ed25519;
const rfcPublicRaw = Buffer.from(rfc.public_key_base64, "base64");
const rfcPublicKey = crypto.createPublicKey({
  key: Buffer.concat([publicDerPrefix, rfcPublicRaw]),
  format: "der",
  type: "spki",
});
if (!crypto.verify(null, Buffer.from(rfc.signature_base, "ascii"), rfcPublicKey, Buffer.from(rfc.signature_base64, "base64"))) {
  throw new Error("Node failed the official RFC 9421 Appendix B.2.6 Ed25519 vector");
}

console.log("node-jcs-ok: RFC 8785 transcript matches Python fixture bytes");
console.log("node-ed25519-ok: WSS proof verifies and reproduces independently");
console.log("node-rfc9421-ok: official RFC 9421 Appendix B.2.6 Ed25519 vector");


// RFC 8785 edge coverage. JavaScript's default string ordering is by UTF-16
// code units, and JSON.stringify supplies ECMAScript number/string formatting.
// The explicit validation below rejects values JCS forbids before serialization.
function assertWellFormedUtf16(value, label) {
  for (let i = 0; i < value.length; i += 1) {
    const unit = value.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new Error(`JCS rejected unpaired high surrogate in ${label}`);
      }
      i += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new Error(`JCS rejected unpaired low surrogate in ${label}`);
    }
  }
}

function canonicalize(value, label = "$") {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    if (typeof value === "string") assertWellFormedUtf16(value, label);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error(`JCS rejected non-finite number at ${label}`);
    return JSON.stringify(value); // ECMAScript number serialization, including -0 => 0.
  }
  if (Array.isArray(value)) {
    return "[" + value.map((item, index) => canonicalize(item, `${label}[${index}]`)).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    for (const key of keys) assertWellFormedUtf16(key, `${label} property name`);
    keys.sort(); // ECMAScript string order is unsigned UTF-16 code-unit order.
    return "{" + keys.map(key =>
      JSON.stringify(key) + ":" + canonicalize(value[key], `${label}.${key}`)
    ).join(",") + "}";
  }
  throw new Error(`JCS rejected non-JSON value at ${label}`);
}

function parseStrictJson(input) {
  let index = 0;
  const whitespace = () => {
    while (index < input.length && /[\t\n\r ]/.test(input[index])) index += 1;
  };
  const scanString = () => {
    const start = index;
    index += 1;
    while (index < input.length) {
      const ch = input[index];
      if (ch === "\\") {
        index += 2;
      } else if (ch === '"') {
        index += 1;
        return input.slice(start, index);
      } else {
        index += 1;
      }
    }
    throw new Error("Malformed JSON string");
  };
  const scanValue = () => {
    whitespace();
    const ch = input[index];
    if (ch === '"') {
      scanString();
      return;
    }
    if (ch === "{") {
      index += 1;
      whitespace();
      const names = new Set();
      if (input[index] === "}") { index += 1; return; }
      while (index < input.length) {
        whitespace();
        if (input[index] !== '"') throw new Error("Malformed JSON object key");
        const name = JSON.parse(scanString());
        if (names.has(name)) throw new Error("Duplicate JSON object member: " + name);
        names.add(name);
        whitespace();
        if (input[index] !== ":") throw new Error("Malformed JSON object separator");
        index += 1;
        scanValue();
        whitespace();
        if (input[index] === "}") { index += 1; return; }
        if (input[index] !== ",") throw new Error("Malformed JSON object delimiter");
        index += 1;
      }
      throw new Error("Unterminated JSON object");
    }
    if (ch === "[") {
      index += 1;
      whitespace();
      if (input[index] === "]") { index += 1; return; }
      while (index < input.length) {
        scanValue();
        whitespace();
        if (input[index] === "]") { index += 1; return; }
        if (input[index] !== ",") throw new Error("Malformed JSON array delimiter");
        index += 1;
      }
      throw new Error("Unterminated JSON array");
    }
    while (index < input.length && !/[\s,\]}]/.test(input[index])) index += 1;
  };
  scanValue();
  whitespace();
  if (index !== input.length) throw new Error("Trailing data after JSON value");
  return JSON.parse(input);
}

function expectCanonical(input, expected, label) {
  const actual = canonicalize(parseStrictJson(input));
  if (actual !== expected) {
    throw new Error("JCS edge vector failed (" + label + "): expected " + expected + ", got " + actual);
  }
}

function expectReject(action, label) {
  let rejected = false;
  try { action(); } catch { rejected = true; }
  if (!rejected) throw new Error(`JCS invalid-input vector was accepted: ${label}`);
}

// RFC 8785 §3.2.3 UTF-16 property ordering example, including a supplementary
// plane emoji whose surrogate pair sorts before U+FB33.
const unicodeInput = String.raw`{"\u20ac":"Euro Sign","\r":"Carriage Return","\ufb33":"Hebrew Letter Dalet With Dagesh","1":"One","\ud83d\ude00":"Emoji: Grinning Face","\u0080":"Control","\u00f6":"Latin Small Letter O With Diaeresis"}`;
const unicodeExpected = String.raw`{"\r":"Carriage Return","1":"One","":"Control","ö":"Latin Small Letter O With Diaeresis","€":"Euro Sign","😀":"Emoji: Grinning Face","דּ":"Hebrew Letter Dalet With Dagesh"}`;
expectCanonical(unicodeInput, unicodeExpected, "UTF-16 property ordering");

// RFC 8785 Appendix B representative IEEE-754 serialization cases, including
// negative zero, subnormals, exponent formatting boundaries and large values.
const numberVectors = [
  ["0000000000000000", "0"],
  ["8000000000000000", "0"],
  ["0000000000000001", "5e-324"],
  ["8000000000000001", "-5e-324"],
  ["7fefffffffffffff", "1.7976931348623157e+308"],
  ["ffefffffffffffff", "-1.7976931348623157e+308"],
  ["4340000000000000", "9007199254740992"],
  ["c340000000000000", "-9007199254740992"],
  ["4430000000000000", "295147905179352830000"],
  ["44b52d02c7e14af5", "9.999999999999997e+22"],
  ["44b52d02c7e14af6", "1e+23"],
  ["44b52d02c7e14af7", "1.0000000000000001e+23"],
  ["444b1ae4d6e2ef4e", "999999999999999700000"],
  ["444b1ae4d6e2ef4f", "999999999999999900000"],
  ["444b1ae4d6e2ef50", "1e+21"],
];
for (const [hex, expected] of numberVectors) {
  const bytes = Buffer.from(hex, "hex");
  const value = bytes.readDoubleBE(0);
  const actual = canonicalize(value);
  if (actual !== expected) throw new Error(`RFC 8785 number vector ${hex}: expected ${expected}, got ${actual}`);
}
expectCanonical("-0", "0", "negative zero");
expectCanonical("1e-6", "0.000001", "lower exponent boundary");
expectCanonical("1e-7", "1e-7", "small exponent");
expectCanonical("1e20", "100000000000000000000", "upper fixed-notation boundary");
expectCanonical("1e21", "1e+21", "upper exponent boundary");

// Recursive sorting, array-order preservation, Unicode/control escaping and
// malformed / forbidden data rejection.
expectCanonical(
  String.raw`{"z":[{"b":2,"a":1},3],"a":"\u000f\nplain"}`,
  String.raw`{"a":"\u000f\nplain","z":[{"a":1,"b":2},3]}`,
  "recursive sort, array order and control escaping"
);
expectCanonical(
  String.raw`{"text":"quote:\" slash:/ reverse:\\ unicode:é"}`,
  String.raw`{"text":"quote:\" slash:/ reverse:\\ unicode:é"}`,
  "quote, reverse solidus, slash and non-ASCII escaping"
);
expectReject(() => JSON.parse("{"), "malformed JSON");
const duplicateMemberInput = String.raw`{"a":1,"\u0061":2}`;
expectReject(() => parseStrictJson(duplicateMemberInput), "duplicate object member after escape decoding");
expectReject(() => parseStrictJson(String.raw`{"outer":{"a":1,"\u0061":2}}`), "nested duplicate object member after escape decoding");
expectReject(() => canonicalize(JSON.parse(String.raw`{"x":"\ud800"}`)), "unpaired high surrogate");
expectReject(() => canonicalize(JSON.parse(String.raw`{"x":"\udc00"}`)), "unpaired low surrogate");
expectReject(() => canonicalize(JSON.parse(String.raw`{"\ud800":1}`)), "unpaired surrogate property name");
expectReject(() => canonicalize(Number.NaN), "NaN");
expectReject(() => canonicalize(Number.POSITIVE_INFINITY), "positive infinity");
expectReject(() => canonicalize(Number.NEGATIVE_INFINITY), "negative infinity");

console.log("jcs-edge-vectors-ok: UTF-16 ordering, Unicode, recursive objects and arrays");
console.log("jcs-number-vectors-ok: RFC 8785 Appendix B IEEE-754 samples and exponent boundaries");
console.log("jcs-negative-vectors-ok: malformed JSON, lone surrogates and non-finite numbers");


// Shared Platform -> AI-PM callback envelope vector. The fixture is loaded
// with the strict parser so duplicate object members are rejected before
// canonicalization, just as they must be at the production callback boundary.
const callbackFixtureText = fs.readFileSync(
  "tests/protocol/fixtures/platform-sem-callback-envelope-jcs-v1.json",
  "utf8"
);
const callbackFixture = parseStrictJson(callbackFixtureText);
const callbackEnvelope = callbackFixture.envelope;
const callbackExpected = callbackFixture.expected;
if (fixture.http_callback_ack.request.body !== callbackExpected.event_envelope_jcs_utf8) {
  throw new Error("Callback ACK HTTP vector must use the shared canonical event-envelope bytes");
}
const payloadJcs = canonicalize(callbackEnvelope.payload);
const envelopeJcs = canonicalize(callbackEnvelope);
if (payloadJcs !== callbackExpected.payload_jcs_utf8) {
  throw new Error("Callback payload JCS bytes differ from shared fixture");
}
if (crypto.createHash("sha256").update(payloadJcs, "utf8").digest("hex") !== callbackExpected.payload_hash_sha256) {
  throw new Error("Callback payload_hash differs from shared fixture");
}
if (envelopeJcs !== callbackExpected.event_envelope_jcs_utf8) {
  throw new Error("Callback complete-envelope JCS bytes differ from shared fixture");
}
if (crypto.createHash("sha256").update(envelopeJcs, "utf8").digest("hex") !== callbackExpected.event_envelope_hash_sha256) {
  throw new Error("Callback event_envelope_hash differs from shared fixture");
}
console.log("callback-jcs-ok: payload and complete authenticated envelope bytes + SHA-256");

// A replay with the same payload but a changed authenticated envelope field
// is not a duplicate. Object member order, however, is not semantically relevant.
const mutatedEventType = { ...callbackEnvelope, event_type: "execution.delivery_status" };
const mutatedEventTypeJcs = canonicalize(mutatedEventType);
if (crypto.createHash("sha256").update(mutatedEventTypeJcs, "utf8").digest("hex") === callbackExpected.event_envelope_hash_sha256) {
  throw new Error("Changing event_type did not change the complete-envelope hash");
}
const mutatedOccurredAt = { ...callbackEnvelope, occurred_at: "2026-11-25T10:15:32Z" };
const mutatedOccurredAtJcs = canonicalize(mutatedOccurredAt);
if (crypto.createHash("sha256").update(mutatedOccurredAtJcs, "utf8").digest("hex") === callbackExpected.event_envelope_hash_sha256) {
  throw new Error("Changing occurred_at did not change the complete-envelope hash");
}
const reorderedEnvelope = Object.fromEntries(Object.entries(callbackEnvelope).reverse());
if (canonicalize(reorderedEnvelope) !== callbackExpected.event_envelope_jcs_utf8) {
  throw new Error("Reordering callback envelope members changed canonical bytes");
}
const mutatedCorrelation = { ...callbackEnvelope, correlation_id: "ffffffff-ffff-4fff-8fff-ffffffffffff" };
const mutatedCorrelationJcs = canonicalize(mutatedCorrelation);
if (crypto.createHash("sha256").update(mutatedCorrelationJcs, "utf8").digest("hex") === callbackExpected.event_envelope_hash_sha256) {
  throw new Error("Changing optional correlation_id did not change the complete-envelope hash");
}
const absentCorrelation = { ...callbackEnvelope };
delete absentCorrelation.correlation_id;
const absentCorrelationJcs = canonicalize(absentCorrelation);
if (crypto.createHash("sha256").update(absentCorrelationJcs, "utf8").digest("hex") === callbackExpected.event_envelope_hash_sha256) {
  throw new Error("Omitting a present optional correlation_id did not change the complete-envelope hash");
}
console.log("callback-idempotency-ok: event_type/occurred_at mutations change envelope hash; member order does not");

