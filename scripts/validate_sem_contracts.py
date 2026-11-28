#!/usr/bin/env python3
"""Validate SEM protocol JSON Schemas and discriminator coverage.

This is documentation-contract validation only; it does not run SEM or AI-PM.
"""
from pathlib import Path
import sys
import re
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

# The application schema is intentionally bidirectional. Validate that the
# normative WSS catalogue assigns exactly one sender set to every app message.
wss_protocol = (ROOT / "docs/protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md").read_text(encoding="utf-8")
direction_map = {}
application_message_types = set(runner["properties"]["message_type"]["enum"])
for line in wss_protocol.splitlines():
    if not line.startswith("|"):
        continue
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 3:
        continue
    direction, message_cell, _purpose = cells
    if direction not in {"SEM → Runner", "Runner → SEM", "Either direction"}:
        continue
    message_types = re.findall(r"`([^`]+)`", message_cell)
    allowed_senders = (
        {"SEM"} if direction == "SEM → Runner"
        else {"Runner"} if direction == "Runner → SEM"
        else {"SEM", "Runner"}
    )
    for message_type in message_types:
        # The catalogue also lists four pre-application handshake frames;
        # this validator covers only the post-handshake application schema.
        if message_type not in application_message_types:
            continue
        if message_type in direction_map:
            raise SystemExit(f"duplicate WSS direction entry: {message_type}")
        direction_map[message_type] = allowed_senders

runner_types = set(runner["properties"]["message_type"]["enum"])
if set(direction_map) != runner_types:
    missing = sorted(runner_types - set(direction_map))
    extra = sorted(set(direction_map) - runner_types)
    raise SystemExit(f"WSS direction catalogue mismatch; missing={missing}, extra={extra}")
for message_type, allowed_senders in direction_map.items():
    if not allowed_senders or not allowed_senders <= {"SEM", "Runner"}:
        raise SystemExit(f"invalid WSS sender set for {message_type}: {allowed_senders}")

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

# P0-07: the release request must use the strict tagged expected_binding
# condition. The legacy untagged expected_binding_epoch field is rejected by
# envelope additionalProperties:false; assert the schema really forbids it.
release_request = platform["$defs"]["ExecutionReleaseRequest"]
release_props = release_request.get("properties", {})
if "expected_binding" not in release_props:
    raise SystemExit("ExecutionReleaseRequest must require the tagged expected_binding condition")
if release_request.get("required") is not None and "expected_binding" not in release_request["required"]:
    raise SystemExit("expected_binding must be required on ExecutionReleaseRequest")
if "expected_binding_epoch" in release_props:
    raise SystemExit("legacy untagged expected_binding_epoch must not exist on ExecutionReleaseRequest")
tagged = release_props["expected_binding"]
if "oneOf" not in tagged:
    raise SystemExit("expected_binding must be a strict oneOf")
tagged_states = []
for branch in tagged["oneOf"]:
    state = branch.get("properties", {}).get("state", {}).get("const")
    if not state:
        raise SystemExit("each expected_binding branch must pin one state const")
    if branch.get("additionalProperties") is not False:
        raise SystemExit(f"expected_binding branch {state} must set additionalProperties:false")
    tagged_states.append(state)
if sorted(tagged_states) != ["bound", "unbound"]:
    raise SystemExit(f"expected_binding states must be exactly unbound/bound, got {tagged_states}")
bound_branch = next(b for b in tagged["oneOf"] if b["properties"]["state"]["const"] == "bound")
if "binding_epoch" not in bound_branch.get("required", []):
    raise SystemExit("bound branch must require binding_epoch >= 1")
unbound_branch = next(b for b in tagged["oneOf"] if b["properties"]["state"]["const"] == "unbound")
if "binding_epoch" in unbound_branch.get("properties", {}):
    raise SystemExit("unbound branch must forbid binding_epoch")

# P0-07: the sixth event must exist, be a distinct branch, and carry no
# Runner/binding/process-exit identity at all.
if "execution.unbound_release_applied" not in event_names:
    raise SystemExit("execution.unbound_release_applied must be a SEM event type")
unbound_event = platform["$defs"]["UnboundReleaseAppliedPayload"]
forbidden = {"binding_epoch", "runner_id", "runner_key_version", "boot_id",
             "supervisor_instance_id", "delivery_id", "stop_fence_id",
             "process_exit_evidence_id", "launch_id", "containment_id",
             "process_identity", "exit_evidence"}
payload_props = set(unbound_event.get("properties", {}))
if forbidden & payload_props:
    raise SystemExit(f"unbound release event must not carry Runner/binding/process fields: {sorted(forbidden & payload_props)}")
if unbound_event.get("properties", {}).get("disposition", {}).get("const") != "released_unbound":
    raise SystemExit("unbound release event disposition must be const released_unbound")
if "dispatch_fence_id" not in unbound_event.get("required", []):
    raise SystemExit("unbound release event must require dispatch_fence_id")

# Release acceptance must expose the release_disposition outcome discriminator.
release_acceptance = platform["$defs"]["ReleaseAcceptanceEnvelope"]
if "release_disposition" not in release_acceptance.get("required", []):
    raise SystemExit("ReleaseAcceptanceEnvelope must require release_disposition")
if set(release_acceptance["properties"]["release_disposition"]["enum"]) != {"bound_release_accepted", "unbound_release_fenced"}:
    raise SystemExit("release_disposition enum must be bound_release_accepted/unbound_release_fenced")

# 409 BINDING_ALREADY_ESTABLISHED must be able to carry the actual epoch.
error_props = set(platform["$defs"]["ProtocolErrorEnvelope"]["properties"]["error"]["properties"])
if "binding_epoch" not in error_props:
    raise SystemExit("ProtocolErrorEnvelope.error must allow binding_epoch for BINDING_ALREADY_ESTABLISHED")

# D04 three-sequence separation: Runner journal event_sequence, WSS
# connection-scoped message_sequence and AI-PM execution_event_sequence are
# three distinct namespaces and must never share a schema surface.
if "message_sequence" not in runner.get("required", []) or "event_sequence" in runner.get("required", []):
    raise SystemExit("WSS frames require transport message_sequence; durable journal fields stay conditional")
for definition_name, definition in platform["$defs"].items():
    if not isinstance(definition, dict):
        continue
    props = set(definition.get("properties", {}))
    for nested in definition.get("properties", {}).values():
        if isinstance(nested, dict) and isinstance(nested.get("properties"), dict):
            props |= set(nested["properties"])
    leaked = {"message_sequence", "journal_id"} & props
    if leaked:
        raise SystemExit(f"platform schema {definition_name} leaked WSS/journal sequence fields: {sorted(leaked)}")
for definition_name, definition in runner.get("$defs", {}).items():
    if not isinstance(definition, dict):
        continue
    props = set(definition.get("properties", {}))
    for nested in definition.get("properties", {}).values():
        if isinstance(nested, dict) and isinstance(nested.get("properties"), dict):
            props |= set(nested["properties"])
    if "execution_event_sequence" in props:
        raise SystemExit(f"Runner schema {definition_name} leaked AI-PM execution_event_sequence")

# Acknowledgements echo execution_event_sequence only, never an ambiguous
# journal/transport alias.
ack_props = set(platform["$defs"]["EventAcknowledgementEnvelope"]["properties"])
if "execution_event_sequence" not in ack_props or {"event_sequence", "message_sequence"} & ack_props:
    raise SystemExit("ACK must echo execution_event_sequence and no sequence alias")

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

# Cross-check the OpenAPI draft against the JSON Schema single source of truth.
openapi_path = ROOT / "docs/protocol/openapi/platform-sem-v1-draft.yaml"
openapi = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
schemas = openapi["components"]["schemas"]
release_path = openapi["paths"]["/internal/sem/v1/executions/{execution_id}/release"]["post"]
request_ref = release_path["requestBody"]["content"]["application/json"]["schema"].get("$ref", "")
if request_ref != "#/components/schemas/ExecutionReleaseRequestedEnvelope":
    raise SystemExit("release operation must reference the ExecutionReleaseRequestedEnvelope schema")
for name in ("ExecutionReleaseRequestedEnvelope", "SemInfrastructureEventEnvelope", "EventAcknowledgementEnvelope"):
    ref = schemas.get(name, {}).get("$ref", "")
    if not ref.startswith("../json-schema/platform-sem-v1.schema.yaml#/"):
        raise SystemExit(f"OpenAPI {name} must reference the shared JSON Schema, got {ref!r}")
openapi_release_request = schemas["ExecutionReleaseRequest"]
if "expected_binding" not in openapi_release_request.get("properties", {}) or "expected_binding_epoch" in openapi_release_request.get("properties", {}):
    raise SystemExit("OpenAPI ExecutionReleaseRequest must use the tagged expected_binding condition")
if "released_unbound" not in schemas["ExecutionSnapshotEnvelope"]["properties"]["infrastructure_state"]["enum"]:
    raise SystemExit("ExecutionSnapshotEnvelope.infrastructure_state must include released_unbound")
if "release_disposition" not in schemas["ReleaseAcceptanceEnvelope"].get("required", []):
    raise SystemExit("OpenAPI ReleaseAcceptanceEnvelope must require release_disposition")
if "binding_epoch" not in schemas["ProtocolErrorEnvelope"]["properties"]["error"]["properties"]:
    raise SystemExit("OpenAPI ProtocolErrorEnvelope.error must allow binding_epoch")
print("openapi-ok: release path, shared schema refs, tagged release, snapshot tombstone state")

print(f"coverage-ok: {len(runner_types)} Runner WSS messages, {len(event_names)} SEM event payloads")
