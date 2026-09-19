"""``dronebench-edit``: JSON on stdout, logs on stderr, and the exit code contract.

0 = the command did its job (including a refusal, which is a report),
1 = it could not be carried out, 2 = the command line was wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dronebench_edits.cli import main
from dronebench_edits.store import RevisionStore

STORE = RevisionStore()


def run(capsys, *argv) -> tuple[int, dict, str]:
    """Run the CLI and return (exit code, parsed stdout, stderr)."""
    code = main([str(a) for a in argv])
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else None
    return code, payload, captured.err


# ------------------------------------------------------------------ reading

def test_active_and_history_on_a_confirmed_design(tiny_design, capsys):
    design_dir, base = tiny_design

    code, payload, err = run(capsys, "active", design_dir)
    assert code == 0
    assert payload["active_revision_id"] == base.revision_id
    assert payload["revision"]["cause"] == "confirm"

    code, payload, err = run(capsys, "history", design_dir)
    assert code == 0
    assert [r["revision_id"] for r in payload["revisions"]] == [base.revision_id]
    assert payload["active_revision_id"] == base.revision_id
    assert base.revision_id in err, "the human log goes to stderr, not into the JSON"


def test_history_limit(tiny_design, fake_build, capsys):
    design_dir, base = tiny_design
    newest = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    code, payload, _ = run(capsys, "history", design_dir, "--limit", 1)
    assert code == 0
    assert [r["revision_id"] for r in payload["revisions"]] == [newest.revision_id]


def test_active_on_an_unconfirmed_design_is_a_typed_report(tmp_path, capsys):
    code, payload, err = run(capsys, "active", tmp_path)
    assert code == 0, "a refusal is a valid report, not a crash"
    assert payload["code"] == "MISSING_EVIDENCE"
    assert "MISSING_EVIDENCE" in err


# ------------------------------------------------------------------ accept / decline

def test_accept_moves_the_pointer(tiny_design, fake_build, capsys):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())

    code, payload, _ = run(capsys, "accept", design_dir, preview.revision_id,
                           "--expected-active", base.revision_id)
    assert code == 0
    assert payload["state"] == "committed"
    assert payload["revision_id"] == preview.revision_id
    assert STORE.active_revision(design_dir) == preview.revision_id


def test_stale_accept_reports_and_exits_zero(tiny_design, fake_build, capsys):
    design_dir, base = tiny_design
    first = STORE.create_preview(design_dir, base.revision_id, "edit:a",
                                 fake_build(content={"op": "a"}))
    second = STORE.create_preview(design_dir, base.revision_id, "edit:b",
                                  fake_build(content={"op": "b"}))
    STORE.commit(design_dir, first.revision_id, base.revision_id)

    code, payload, _ = run(capsys, "accept", design_dir, second.revision_id,
                           "--expected-active", base.revision_id)
    assert code == 0
    assert payload["code"] == "STALE_REVISION"
    assert payload["details"]["actual_active"] == first.revision_id
    assert payload["details"]["expected_active"] == base.revision_id
    assert STORE.active_revision(design_dir) == first.revision_id


def test_accept_of_an_unknown_revision(tiny_design, capsys):
    design_dir, _ = tiny_design
    code, payload, _ = run(capsys, "accept", design_dir, "rev-nope")
    assert code == 0
    assert payload["code"] == "MISSING_EVIDENCE"


def test_accept_of_a_blocked_preview_is_refused(tiny_design, fake_build, capsys):
    from dronebench_contracts.models import RoundTripCheck

    design_dir, base = tiny_design
    preview = STORE.create_preview(
        design_dir, base.revision_id, "edit:resize_spar",
        fake_build(checks=[RoundTripCheck(name="propeller_clearance", passed=False,
                                          detail="12 mm to vtail1")]))

    code, payload, _ = run(capsys, "accept", design_dir, preview.revision_id,
                           "--expected-active", base.revision_id)
    assert code == 0, "a refusal is a report"
    assert payload["code"] == "CONSTRAINT_FAILED"
    assert payload["details"]["failed_checks"] == ["propeller_clearance"]
    assert STORE.active_revision(design_dir) == base.revision_id

    # ...and the verdict is visible in `history` without having to try the commit first.
    code, payload, _ = run(capsys, "history", design_dir)
    row = next(r for r in payload["revisions"] if r["revision_id"] == preview.revision_id)
    assert row["edit_status"]["status"] == "blocked"
    assert row["edit_status"]["committable"] is False


def test_decline_reports_and_changes_nothing(tiny_design, fake_build, capsys):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())

    code, payload, _ = run(capsys, "decline", design_dir, preview.revision_id,
                           "--reason", "static margin drops")
    assert code == 0
    assert payload["declined_revision_id"] == preview.revision_id
    assert payload["reason"] == "static margin drops"
    assert payload["active_revision_id"] == base.revision_id
    assert payload["revision"]["state"] == "preview"

    code, payload, _ = run(capsys, "decisions", design_dir)
    assert code == 0
    assert [d["decision"] for d in payload["decisions"]] == ["declined"]


def test_decline_requires_a_reason(tiny_design, capsys):
    design_dir, base = tiny_design
    with pytest.raises(SystemExit) as excinfo:
        main(["decline", str(design_dir), base.revision_id])
    assert excinfo.value.code == 2


# ------------------------------------------------------------------ usage

@pytest.mark.parametrize("argv", [
    [],                                    # no subcommand
    ["nosuchcommand", "."],                # unknown subcommand
    ["history"],                           # missing design_dir
])
def test_usage_errors_exit_two(argv):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_bad_params_json_exits_two(tiny_design, capsys):
    design_dir, base = tiny_design
    code = main(["propose", str(design_dir), "--operation", "resize_spar",
                 "--params", "{not json"])
    assert code == 2
    assert "--params" in capsys.readouterr().err


# ------------------------------------------------------------------ delegation to A3b

def test_propose_without_apply_edit_is_a_clear_json_error(tiny_design, capsys, monkeypatch):
    """Until A3b lands (or if it is not installed), `propose` must fail legibly, not traceback."""
    import dronebench_edits.cli as cli

    def missing():
        raise ImportError("dronebench_edits.apply is not installed")

    monkeypatch.setattr(cli, "_load_apply_edit", missing)
    code, payload, err = run(capsys, "propose", tiny_design[0], "--operation", "resize_spar",
                             "--params", '{"od_m": 0.016}')
    assert code == 1
    assert payload["code"] == "UNSUPPORTED_EDIT"
    assert "apply_edit" in payload["message"]
    assert "UNSUPPORTED_EDIT" in err


def test_propose_delegates_and_can_accept(tiny_design, fake_build, capsys, monkeypatch):
    """With a stand-in for A3b, the CLI stages a preview and `--accept` commits it."""
    import dronebench_edits.cli as cli
    from dronebench_contracts.models import CadEditResult

    design_dir, base = tiny_design
    seen: dict = {}

    def fake_apply_edit(dd: Path, request):
        seen["design_dir"] = Path(dd)
        seen["request"] = request
        preview = STORE.create_preview(dd, request.base_revision_id,
                                       f"edit:{request.operation}", fake_build())
        return CadEditResult(base_revision_id=request.base_revision_id,
                             preview_revision_id=preview.revision_id,
                             operation=request.operation, status="ok",
                             affected_part_ids=["p1"], artifacts=preview.artifacts)

    monkeypatch.setattr(cli, "_load_apply_edit", lambda: fake_apply_edit)

    code, payload, _ = run(capsys, "preview", design_dir, "--operation", "resize_spar",
                           "--target", "spar-1", "--params", '{"od_m": 0.016}')
    assert code == 0
    assert payload["status"] == "ok"
    assert seen["request"].base_revision_id == base.revision_id, "base defaults to the active one"
    assert seen["request"].target_part_ids == ["spar-1"]
    assert seen["request"].parameters == {"od_m": 0.016}
    assert STORE.active_revision(design_dir) == base.revision_id, "a preview commits nothing"

    code, payload, _ = run(capsys, "propose", design_dir, "--operation", "resize_spar",
                           "--params", '{"od_m": 0.016}', "--accept")
    assert code == 0
    assert payload["committed"]["state"] == "committed"
    assert STORE.active_revision(design_dir) == payload["committed"]["revision_id"]


def test_propose_reports_a_blocked_edit_with_exit_zero(tiny_design, capsys, monkeypatch):
    import dronebench_edits.cli as cli
    from dronebench_contracts.models import CadEditResult, ErrorCode, ErrorEnvelope

    def blocking_apply_edit(dd, request):
        return CadEditResult(
            base_revision_id=request.base_revision_id, operation=request.operation,
            status="blocked",
            error=ErrorEnvelope(code=ErrorCode.CONSTRAINT_FAILED,
                                message="18 mm spar will not pass a 16 mm wing hole",
                                details={"od_mm": 18.0, "hole_mm": 16.0}))

    monkeypatch.setattr(cli, "_load_apply_edit", lambda: blocking_apply_edit)
    code, payload, _ = run(capsys, "propose", tiny_design[0], "--operation", "resize_spar",
                           "--params", '{"od_m": 0.018}')
    assert code == 0, "a blocked edit is a successful report"
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == "CONSTRAINT_FAILED"
    assert payload["preview_revision_id"] is None
