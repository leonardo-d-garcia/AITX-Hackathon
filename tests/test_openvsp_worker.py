"""C3 OpenVSP worker: live install state, no hardcoded analysis input names."""

from openvsp_worker import analysis_inputs, available, status_dict, versions


def test_available_true_after_c3_install() -> None:
    assert available() is True


def test_versions_from_this_build() -> None:
    v = versions()
    assert v["openvsp"] == "OpenVSP 3.51.3"
    assert v["vspaero"] is not None
    assert "7.2.2" in v["vspaero"]
    assert v["abi"] == "cp314"


def test_analysis_inputs_enumerated_at_runtime() -> None:
    inputs = analysis_inputs()
    assert "VSPAEROComputeGeometry" in inputs
    assert "VSPAEROSweep" in inputs
    assert isinstance(inputs["VSPAEROComputeGeometry"], list)
    assert "GeomSet" in inputs["VSPAEROComputeGeometry"]
    assert "AlphaStart" in inputs["VSPAEROSweep"]


def test_status_dict_keys() -> None:
    status = status_dict()
    assert status["installed"] is True
    assert status["host"] == "wsl-ubuntu"
    assert status["error"] in (None, "")
