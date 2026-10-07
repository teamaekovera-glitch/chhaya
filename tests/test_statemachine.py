"""CHHAYA Phase 5 — ASL contract tests for infra/statemachine.asl.json (task brief d).

No AWS credentials are used: these are pure structural checks on the Amazon
States Language definition — JSON validity, state closure (every ``Next`` /
``Catch`` target resolves to a defined state), the §10-Phase-5 state shape
(FetchData -> RunShadeSeason Map -> ValidateGraph -> UploadArtifacts ->
WriteManifest, Fail reachable), the lambda:invoke task shape, and the
no-hardcoded-AWS-credentials guard over the diff surface (task brief: "assert
no hardcoded AWS credentials anywhere in the diff surface using a regex grep").
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASL_PATH = ROOT / "infra" / "statemachine.asl.json"
TEMPLATE_PATH = ROOT / "infra" / "template.yaml"

REQUIRED_STATES = ("FetchData", "RunShadeSeason", "ValidateGraph", "UploadArtifacts", "WriteManifest")


@pytest.fixture(scope="module")
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


def _all_states(definition: dict) -> dict:
    """Top-level states plus all ItemProcessor states, keyed by name."""
    states: dict = dict(definition.get("States", {}))
    for state in definition.get("States", {}).values():
        processor = state.get("ItemProcessor")
        if processor:
            states.update(processor.get("States", {}))
    return states


# ------------------------------------------------------------------- json + shape


def test_asl_is_valid_json_with_start_at(asl: dict) -> None:
    assert isinstance(asl, dict) and asl.get("StartAt")


def test_required_states_defined(asl: dict) -> None:
    names = set(_all_states(asl))
    missing = [s for s in REQUIRED_STATES if s not in names]
    assert missing == [], f"required states missing from ASL: {missing}"


def test_map_state_shape(asl: dict) -> None:
    mapping = asl["States"]["RunShadeSeason"]
    assert mapping["Type"] == "Map"
    assert mapping["ItemsPath"] == "$.seasons"
    assert mapping["MaxConcurrency"] >= 1
    processor = mapping["ItemProcessor"]
    assert processor["StartAt"] in processor["States"]


def test_every_next_and_catch_target_resolves(asl: dict) -> None:
    """State closure: any referenced state name must be defined — a dangling wire
    would fail at deploy, not at test time, so guard it structurally."""
    states = _all_states(asl)
    for name, state in states.items():
        target = state.get("Next")
        if target is not None:
            assert target in states, f"{name}.Next -> undefined state {target!r}"
        for catcher in state.get("Catch", []):
            assert catcher["Next"] in states, f"Catch in {name} -> undefined state {catcher['Next']!r}"


def test_every_state_terminates(asl: dict) -> None:
    """Each state must have Next, End, or be a Fail/Succeed/Choice leaf."""
    for name, state in _all_states(asl).items():
        terminal = state.get("End") is True or state["Type"] in {"Fail", "Succeed", "Choice"}
        assert terminal or "Next" in state, f"state {name} has neither End, Next, nor terminal type"


def test_fail_state_is_reachable_and_the_notify_slot(asl: dict) -> None:
    failure = asl["States"]["NotifyValidationFailure"]
    assert failure["Type"] == "Fail"
    assert failure.get("Error") and failure.get("Cause")
    catches = [c for st in _all_states(asl).values() for c in st.get("Catch", [])]
    assert any(c["Next"] == "NotifyValidationFailure" for c in catches)


def test_task_states_use_lambda_invoke_integration(asl: dict) -> None:
    tasks = [st for st in _all_states(asl).values() if st["Type"] == "Task"]
    assert tasks, "state machine must have at least one Task state"
    for task in tasks:
        assert task["Resource"] == "arn:aws:states:::lambda:invoke", task
        params = task["Parameters"]
        assert params["FunctionName"] == "${PrecomputeHandlerArn}"
        # Parameters.Path style: season.$ etc. composing the handler event from
        # the Map results, so the handler contract keys stay stable.
        assert set(params["Payload"]) == {"season.$", "GRAPH_BUCKET.$", "S3_KEY_GRAPH.$"}
        for key in params["Payload"].values():
            assert key.startswith("$."), key


def test_state_machine_is_region_agnostic(asl: dict) -> None:
    """No hardcoded region/account ARN may appear in the ASL."""
    raw = ASL_PATH.read_text(encoding="utf-8")
    assert not re.search(r"arn:aws:lambda:[a-z0-9-]+:\d{12}:", raw)


# ----------------------------------------------------------- template wiring guard


def test_template_declares_and_substitutes_the_handler() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "PrecomputeStateMachine:" in template
    assert "PrecomputeHandlerArn: !GetAtt PrecomputeHandlerFunction.Arn" in template
    assert "AWS::Serverless::StateMachine" in template
    # Manifest stub, not the direct S3 integration (DECISIONS.md Phase 5 decision):
    assert "arn:aws:states:::s3:" not in template


# -------------------------------------------------------- credential-leak guard

# Task brief: "assert repo has NO literal ACCESS_KEY/SECRET strings — no hardcoded
# AWS credentials anywhere in the diff surface". One regex, four shapes:
#   1. a 20-char AK-class access-key literal (AKIA…)
#   2. unencrypted private-key headers (OpenSSH/RSA/EC/DSA/PGP)
#   3. credentials-file style `aws_access_key_id = <literal>`
#   4. Python/KV style `secret_access_key = "literal"`
_CRED_PATTERN = re.compile(
    r"AKIA[0-9A-Z]{16}"
    r"|-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY-----"
    r"|(?i:\baws_(?:access_key_id|secret_access_key)\b\s*[:=]\s*[\"'][A-Za-z0-9/+]{16,}[\"'])"
    r"|(?i:\b(?:access_key_id|secret_access_key)\b\s*[:=]\s*['\"][A-Za-z0-9/+]{16,}['\"])"
)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / line for line in out.stdout.splitlines() if line]


def test_no_hardcoded_aws_credentials_in_repo() -> None:
    leaks = []
    for path in _tracked_files():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = _CRED_PATTERN.search(text)
        if match:
            leaks.append(f"{path.relative_to(ROOT)}: {match.group(0)[:40]!r}")
    assert leaks == [], "hardcoded AWS credentials / private keys found:\n" + "\n".join(leaks)


def test_diff_surface_is_double_clean() -> None:
    """The brief's diff-surface emphasis: the files this PR adds must be clean."""
    for rel in (
        "infra/statemachine.asl.json",
        "infra/template.yaml",
        "lambdas/precompute_handler/handler.py",
        "tests/test_precompute_handler.py",
        "tests/test_statemachine.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not _CRED_PATTERN.search(text), f"credential-shaped literal in {rel}"
