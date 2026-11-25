#!/usr/bin/env python3
"""Validate positive and negative fixtures for every D-04 payload branch."""
from __future__ import annotations
import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs/protocol/json-schema"
FIXTURE = ROOT / "tests/protocol/fixtures/payload-fixtures-v1.json"
FORMAT = FormatChecker()

def load_schema(name):
    return yaml.safe_load((SCHEMAS / name).read_text(encoding="utf-8"))

def expect_valid(validator, value, label):
    errors = list(validator.iter_errors(value))
    if errors:
        raise AssertionError(f"{label}: expected valid, got: {errors[0].message}")

def expect_invalid(validator, value, label):
    errors = list(validator.iter_errors(value))
    if not errors:
        raise AssertionError(f"{label}: invalid mutation unexpectedly validated")

data = json.loads(FIXTURE.read_text(encoding="utf-8"))
runner_schema = load_schema("runner-sem-v1.schema.yaml")
platform_schema = load_schema("platform-sem-v1.schema.yaml")
runner_validator = Draft202012Validator(runner_schema, format_checker=FORMAT)
platform_validator = Draft202012Validator(platform_schema, format_checker=FORMAT)

runner_types = set(runner_schema["properties"]["message_type"]["enum"])
fixture_types = {item["message_type"] for item in data["runner_messages"]}
assert runner_types == fixture_types, f"Runner fixture coverage mismatch: missing={runner_types-fixture_types}, extra={fixture_types-runner_types}"

for item in data["runner_messages"]:
    label = f"Runner {item['message_type']}"
    expect_valid(runner_validator, item, label)
    extra_top = dict(item)
    extra_top["unexpected_top_level"] = True
    expect_invalid(runner_validator, extra_top, label + " unknown top-level field")
    extra_payload = json.loads(json.dumps(item))
    extra_payload["payload"]["unexpected_payload_field"] = True
    expect_invalid(runner_validator, extra_payload, label + " unknown payload field")
    empty_payload = json.loads(json.dumps(item))
    empty_payload["payload"] = {}
    expect_invalid(runner_validator, empty_payload, label + " missing required payload fields")

    if item["message_type"] in {
        "execution.delivery_received",
        "harness.starting",
        "harness.started",
        "harness.start_failed",
        "harness.process_exited",
        "execution.release_applied",
        "runner.admission.changed",
    }:
        missing_journal = dict(item)
        missing_journal.pop("journal_id", None)
        expect_invalid(runner_validator, missing_journal, label + " missing durable journal_id")
        missing_sequence = dict(item)
        missing_sequence.pop("event_sequence", None)
        expect_invalid(runner_validator, missing_sequence, label + " missing durable event_sequence")

    if item["message_type"] == "protocol.ack":
        ack_missing_journal = json.loads(json.dumps(item))
        ack_missing_journal["payload"].pop("acknowledged_journal_id", None)
        expect_invalid(runner_validator, ack_missing_journal, label + " event ACK missing journal_id")
        ack_missing_sequence = json.loads(json.dumps(item))
        ack_missing_sequence["payload"].pop("acknowledged_event_sequence", None)
        expect_invalid(runner_validator, ack_missing_sequence, label + " event ACK missing event_sequence")
        ack_missing_both = json.loads(json.dumps(item))
        ack_missing_both["payload"].pop("acknowledged_journal_id", None)
        ack_missing_both["payload"].pop("acknowledged_event_sequence", None)
        expect_invalid(runner_validator, ack_missing_both, label + " durably_recorded ACK missing both cursor fields")
        non_durable_without_cursor = json.loads(json.dumps(item))
        non_durable_without_cursor["payload"]["disposition"] = "accepted"
        non_durable_without_cursor["payload"].pop("acknowledged_journal_id", None)
        non_durable_without_cursor["payload"].pop("acknowledged_event_sequence", None)
        expect_valid(runner_validator, non_durable_without_cursor, label + " non-durable ACK without journal cursor")

for item in data["platform_requests"]:
    label = f"Platform request {item['message_type']}"
    expect_valid(platform_validator, item, label)
    extra_top = dict(item)
    extra_top["unexpected_top_level"] = True
    expect_invalid(platform_validator, extra_top, label + " unknown top-level field")
    extra_payload = json.loads(json.dumps(item))
    extra_payload["payload"]["unexpected_payload_field"] = True
    expect_invalid(platform_validator, extra_payload, label + " unknown payload field")
    empty_payload = json.loads(json.dumps(item))
    empty_payload["payload"] = {}
    expect_invalid(platform_validator, empty_payload, label + " missing required payload fields")

event_types = set(platform_schema["$defs"]["EventBase"]["properties"]["event_type"]["enum"])
fixture_event_types = {item["event_type"] for item in data["sem_events"]}
assert event_types == fixture_event_types, f"SEM event fixture coverage mismatch: missing={event_types-fixture_event_types}, extra={fixture_event_types-event_types}"

ack_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **platform_schema["$defs"]["EventAcknowledgementEnvelope"]}
ack_validator = Draft202012Validator(ack_schema, format_checker=FORMAT)
for item in data.get("event_acknowledgements", []):
    expect_valid(ack_validator, item, "SEM event acknowledgement")
    legacy = dict(item)
    legacy["event_sequence"] = legacy.pop("execution_event_sequence")
    expect_invalid(ack_validator, legacy, "ACK legacy ambiguous event_sequence field")
    extra = dict(item)
    extra["unexpected"] = True
    expect_invalid(ack_validator, extra, "ACK unknown field")

for item in data["sem_events"]:
    label = f"SEM event {item['event_type']}"
    expect_valid(platform_validator, item, label)
    extra_top = dict(item)
    extra_top["unexpected_top_level"] = True
    expect_invalid(platform_validator, extra_top, label + " unknown top-level field")
    extra_payload = json.loads(json.dumps(item))
    extra_payload["payload"]["unexpected_payload_field"] = True
    expect_invalid(platform_validator, extra_payload, label + " unknown payload field")
    empty_payload = json.loads(json.dumps(item))
    empty_payload["payload"] = {}
    expect_invalid(platform_validator, empty_payload, label + " missing required payload fields")

# Cross-field process/release evidence invariants.
process_event = next(item for item in data["sem_events"] if item["event_type"] == "harness.process_observed")
exited_both = json.loads(json.dumps(process_event))
exited_both["payload"]["observation"] = "exited"
exited_both["payload"]["process_identity"] = {
    "pid": 4312, "process_start_identity": "proc-start-4312",
    "cgroup_path": "/system.slice/sem-exec-111",
    "systemd_invocation_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
}
exited_both["payload"]["exit_evidence"] = {
    "evidence_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "cgroup_populated": 0,
    "systemd_invocation_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    "exit_code": 0, "exit_signal": 9
}
expect_invalid(platform_validator, exited_both, "process exit with both exit_code and exit_signal")

exited_missing = json.loads(json.dumps(exited_both))
del exited_missing["payload"]["exit_evidence"]
expect_invalid(platform_validator, exited_missing, "process exit without exit evidence")

release_event = next(item for item in data["sem_events"] if item["event_type"] == "execution.release_status")
release_missing = json.loads(json.dumps(release_event))
release_missing["payload"]["release_state"] = "process_exited"
expect_invalid(platform_validator, release_missing, "process_exited release without evidence reference")
released_missing = json.loads(json.dumps(release_event))
released_missing["payload"]["release_state"] = "released"
expect_invalid(platform_validator, released_missing, "released state without process-exit evidence reference")

# Cross-protocol process-exit and uncertainty invariants.
runner_exit = next(item for item in data["runner_messages"] if item["message_type"] == "harness.process_exited")
assert runner_exit["payload"]["exit_status"]["kind"] in {"code", "signal", "unknown"}
runner_signal = json.loads(json.dumps(runner_exit))
runner_signal["payload"]["exit_status"] = {"kind": "signal", "signal": 9}
expect_valid(runner_validator, runner_signal, "Runner process terminated by signal")
runner_unknown_with_code = json.loads(json.dumps(runner_exit))
runner_unknown_with_code["payload"]["exit_status"] = {"kind": "unknown", "code": 137}
expect_invalid(runner_validator, runner_unknown_with_code, "Runner unknown exit status with numeric code")
runner_unknown_with_signal = json.loads(json.dumps(runner_exit))
runner_unknown_with_signal["payload"]["exit_status"] = {"kind": "unknown", "signal": 9}
expect_invalid(runner_validator, runner_unknown_with_signal, "Runner unknown exit status with numeric signal")

runner_release = next(item for item in data["runner_messages"] if item["message_type"] == "execution.release_applied")
for release_disposition in ("process_stopped", "already_exited"):
    release_without_evidence = json.loads(json.dumps(runner_release))
    release_without_evidence["payload"]["disposition"] = release_disposition
    expect_invalid(runner_validator, release_without_evidence, f"Runner {release_disposition} without process-exit evidence")
    release_with_evidence = json.loads(json.dumps(runner_release))
    release_with_evidence["payload"]["disposition"] = release_disposition
    release_with_evidence["payload"]["process_exit_evidence_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    expect_valid(runner_validator, release_with_evidence, f"Runner {release_disposition} with process-exit evidence")

for release_disposition in ("stop_fenced", "stale_rejected", "local_uncertain"):
    release_with_false_evidence = json.loads(json.dumps(runner_release))
    release_with_false_evidence["payload"]["disposition"] = release_disposition
    release_with_false_evidence["payload"]["process_exit_evidence_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    expect_invalid(runner_validator, release_with_false_evidence, f"Runner {release_disposition} carrying positive process-exit evidence")

runner_missing_digest = json.loads(json.dumps(runner_exit))
del runner_missing_digest["payload"]["evidence_digest"]
expect_invalid(runner_validator, runner_missing_digest, "Runner process exit without evidence digest")
runner_bad_digest = json.loads(json.dumps(runner_exit))
runner_bad_digest["payload"]["evidence_digest"] = "not-a-sha256"
expect_invalid(runner_validator, runner_bad_digest, "Runner process exit with malformed evidence digest")
runner_bad_evidence_version = json.loads(json.dumps(runner_exit))
runner_bad_evidence_version["payload"]["evidence_schema_version"] = 2
expect_invalid(runner_validator, runner_bad_evidence_version, "Runner process exit with unsupported evidence schema version")

unknown_event = next(
    item for item in data["sem_events"]
    if item["event_type"] == "harness.process_observed"
    and item["payload"]["observation"] == "exit_status_unknown"
)
expect_valid(platform_validator, unknown_event, "SEM process exit with unknown numeric status")
unknown_with_code = json.loads(json.dumps(unknown_event))
unknown_with_code["payload"]["exit_evidence"]["exit_code"] = 137
expect_invalid(platform_validator, unknown_with_code, "SEM unknown exit status carrying exit_code")
unknown_with_signal = json.loads(json.dumps(unknown_event))
unknown_with_signal["payload"]["exit_evidence"]["exit_signal"] = 9
expect_invalid(platform_validator, unknown_with_signal, "SEM unknown exit status carrying exit_signal")

uncertain_event = next(item for item in data["sem_events"] if item["event_type"] == "execution.infrastructure_uncertain")
uncertain_without_reservation = json.loads(json.dumps(uncertain_event))
del uncertain_without_reservation["payload"]["reservation_retained"]
expect_invalid(platform_validator, uncertain_without_reservation, "Infrastructure uncertainty without retained reservation")

print(f"ack-fixtures-ok: {len(data.get('event_acknowledgements', []))} SEM event acknowledgements")
print(f"payload-fixtures-ok: {len(runner_types)} Runner messages, {len(data['platform_requests'])} Platform requests, {len(event_types)} SEM events")
print(f"negative-fixtures-ok: unknown top-level, unknown payload and missing required payload fields for every branch")
