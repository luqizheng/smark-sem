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
