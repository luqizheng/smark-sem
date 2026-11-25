#!/usr/bin/env python3
"""Validate SEM protocol JSON Schemas and discriminator coverage.

This is documentation-contract validation only; it does not run SEM or AI-PM.
"""
from pathlib import Path
import sys
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs/protocol/json-schema"

def load(name):
    path = SCHEMA_DIR / name
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise SystemExit(f"{path}: expected YAML object")
    if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SystemExit(f"{path}: expected JSON Schema 2020-12")
    Draft202012Validator.check_schema(value)
    print(f"schema-ok: {path.relative_to(ROOT)}")
    return value

runner = load("runner-sem-v1.schema.yaml")
handshake = load("runner-sem-handshake-v1.schema.yaml")
platform = load("platform-sem-v1.schema.yaml")

runner_types = set(runner["properties"]["message_type"]["enum"])
runner_branches = {
    item["if"]["properties"]["message_type"]["const"]
    for item in runner.get("allOf", [])
    if isinstance(item, dict)
    and isinstance(item.get("if"), dict)
    and isinstance(item["if"].get("properties"), dict)
    and isinstance(item["if"]["properties"].get("message_type"), dict)
    and "const" in item["if"]["properties"]["message_type"]
}
if runner_types != runner_branches:
    missing = sorted(runner_types - runner_branches)
    extra = sorted(runner_branches - runner_types)
    raise SystemExit(f"Runner WSS message branch mismatch; missing={missing}, extra={extra}")

# Durable Runner observations share one journal stream across reconnects.
# Keep this allow-list aligned with the WSS protocol and D-05 event model.
durable_runner_types = {
    "execution.delivery_received",
    "harness.starting",
    "harness.started",
    "harness.start_failed",
    "harness.process_exited",
    "execution.release_applied",
    "runner.admission.changed",
}
journal_required_types = set()
for item in runner.get("allOf", []):
    condition = item.get("if", {}).get("properties", {}).get("message_type", {})
    required = item.get("then", {}).get("required", [])
    if "journal_id" in required and "event_sequence" in required:
        values = condition.get("enum", [])
        journal_required_types.update(values)
if durable_runner_types != journal_required_types:
    missing = sorted(durable_runner_types - journal_required_types)
    extra = sorted(journal_required_types - durable_runner_types)
    raise SystemExit(
        f"Runner durable journal coverage mismatch; missing={missing}, extra={extra}"
    )

event_defs = platform["$defs"]["SemInfrastructureEventEnvelope"]["oneOf"]
event_names = set(platform["$defs"]["EventBase"]["properties"]["event_type"]["enum"])
event_branches = set()
for item in event_defs:
    ref = item.get("$ref", "")
    name = ref.rsplit("/", 1)[-1]
    definition = platform["$defs"].get(name)
    if not definition:
        raise SystemExit(f"missing event definition: {name}")
    for branch in definition.get("allOf", []):
        props = branch.get("properties", {})
        event_type = props.get("event_type", {}).get("const")
        if event_type:
            event_branches.add(event_type)
if event_names != event_branches:
    missing = sorted(event_names - event_branches)
    extra = sorted(event_branches - event_names)
    raise SystemExit(f"SEM event branch mismatch; missing={missing}, extra={extra}")

# The handshake schema must keep all pre-application frames separate from
# the post-handshake WSS application message enum.
handshake_types = {
    definition["properties"]["message_type"]["const"]
    for definition in handshake["$defs"].values()
    if isinstance(definition, dict)
    and isinstance(definition.get("properties"), dict)
    and isinstance(definition["properties"].get("message_type"), dict)
    and "const" in definition["properties"]["message_type"]
}
if "runner.session.ack" not in handshake_types:
    raise SystemExit("runner.session.ack must be owned by handshake schema")
if handshake_types & runner_types:
    raise SystemExit(
        "Handshake/application frame ownership overlaps: "
        + ", ".join(sorted(handshake_types & runner_types))
    )
if "runner.session.superseded" not in runner_types:
    raise SystemExit("runner.session.superseded must remain a post-handshake application frame")

print(f"coverage-ok: {len(runner_types)} Runner WSS messages, {len(event_names)} SEM event payloads")
