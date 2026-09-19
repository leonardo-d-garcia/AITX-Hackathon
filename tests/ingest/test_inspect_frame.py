"""QA, variant detection and the frame proposal, measured against the real archive."""
from __future__ import annotations

import numpy as np
import pytest

from dronebench_ingest import detect_variants, propose_frame
from dronebench_ingest.frame import categorize

NOT_WATERTIGHT = {
    "Fuselage/fuse2.stl", "Fuselage/fuse4.stl", "Fuselage/fuse5.stl", "Fuselage/hatch2.stl",
    "High Temp PETG or ABS or ASA/motor_mount.stl", "Wings/wing1.stl",
    "Wings/wing3_12mm_hole.stl", "Wings/wing3_16mm_hole.stl", "Wings/wing3_no_hole.stl",
}


def test_qa_reports_real_mesh_state(staged):
    _, _, sources = staged
    assert len(sources) == 24
    assert sum(s.qa.triangles for s in sources) == 580404
    assert {s.source_path for s in sources if not s.qa.watertight} == NOT_WATERTIGHT
    for s in sources:
        assert s.qa.finite and s.qa.consistent_winding
        assert s.qa.components == 1
        assert s.qa.triangles > 0
        lo, hi = s.qa.bounds_native
        assert all(a <= b for a, b in zip(lo, hi))


def test_folder_hint_is_kept_as_evidence(staged):
    _, _, sources = staged
    hints = {s.source_path: s.folder_hint for s in sources}
    assert hints["High Temp PETG or ABS or ASA/motor_mount.stl"] == "High Temp PETG or ABS or ASA"
    assert hints["Wings/wing1.stl"] == "Wings"


def test_variants_detected_and_nothing_selected(staged):
    _, _, sources = staged
    groups = {g.group_id: g for g in detect_variants(sources)}
    assert set(groups) == {"wing3", "fuse3"}
    assert len(groups["wing3"].options) == 3
    assert len(groups["fuse3"].options) == 3
    assert groups["wing3"].options == sorted(groups["wing3"].options)
    for g in groups.values():
        assert g.selected is None
    # neighbours with a trailing digit are separate installed parts, not alternatives
    assert "wing" not in groups and "canopy" not in groups and "hatch" not in groups


def test_frame_proposal_numbers(staged):
    _, _, sources = staged
    frame = propose_frame(sources)
    assert frame.confirmed is False and frame.confirmed_by is None
    assert frame.units == "mm" and frame.scale_to_m == pytest.approx(0.001)
    assert frame.nose_datum_native[1] == pytest.approx(-403.07, abs=0.01)
    assert frame.nose_datum_native[0] == 0.0 and frame.nose_datum_native[2] == 0.0
    R = np.array(frame.native_to_frd)
    assert np.linalg.det(R) == pytest.approx(1.0)
    assert np.allclose(R @ R.T, np.eye(3))
    assert frame.mirror_plane_native == "x=0"
    assert any("confirm" in n for n in frame.notes)


def test_candidate_mapping_produces_the_published_hypotheses(staged):
    from dronebench_ingest import to_frd
    _, _, sources = staged
    frame = propose_frame(sources)
    wing_tip_native = max(s.qa.bounds_native[1][0] for s in sources
                          if categorize(s.source_path) == "wing")
    span = 2 * abs(to_frd(np.array([[wing_tip_native, 0, 0]]), frame)[0][1])
    assert span == pytest.approx(2.2245, abs=0.001)
    nose = to_frd(np.array([[0.0, frame.nose_datum_native[1], 0.0]]), frame)[0]
    assert np.allclose(nose, [0.0, 0.0, 0.0])
    tail_native = max(s.qa.bounds_native[1][1] for s in sources)
    assert to_frd(np.array([[0.0, tail_native, 0.0]]), frame)[0][0] < 0    # aft is negative x


def test_categories_come_from_filenames(staged):
    assert categorize("Wings/wing3_12mm_hole.stl") == "wing"
    assert categorize("Wings/aileron.stl") == "aileron"
    assert categorize("Tail/taileron.stl") == "ruddervator"
    assert categorize("Tail/vtail2.stl") == "vtail"
    assert categorize("High Temp PETG or ABS or ASA/wing_bay_plate.stl") == "mount"
    assert categorize("Fuselage/canopy1.stl") == "canopy"
    assert categorize("something_else.stl") == "other"
