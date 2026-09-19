"""Inline assumed fixtures. fixtures/c/ are gitkeeps; numbers match the Lane C brief."""

from __future__ import annotations

# All of these are source_kind: assumed. They are not Avenger measurements.
S = 0.40
B = 2.20
C = 0.20
CANT_RAD = 0.6981317007977318
PANEL_AREA = 0.05
TAIL_ARM = 0.85
CD_PROFILE = 0.015
CD_FUSELAGE = 0.008
CD_INTERFERENCE = 0.002
E_OSWALD = 0.80
CL_MAX = 1.3
CRUISE_MPS = 15.0
RHO = 1.225
G = 9.80665
RESERVE = 0.2
BATTERY_MASS_KG = 0.60
BATTERY_ENERGY_WH = 88.0
BATTERY_X = -0.25
SPAR_DO = 0.016
SPAR_DI = 0.012
SPAR_ALLOW_PA = 400e6


def vtail_geometry() -> dict:
    return {
        "revision_id": "synthetic_vtail_demo",
        "source_kind": "assumed",
        "reference": {"S": S, "b": B, "c": C},
        "aero": {
            "CD_profile": CD_PROFILE,
            "CD_fuselage": CD_FUSELAGE,
            "CD_interference": CD_INTERFERENCE,
            "e": E_OSWALD,
            "CLmax": CL_MAX,
        },
        "vtail": {
            "layout": "vtail",
            "cant_rad": CANT_RAD,
            "panel_area": PANEL_AREA,
            "tail_arm": TAIL_ARM,
        },
        "spar": {
            "Do": SPAR_DO,
            "Di": SPAR_DI,
            "allow_pa": SPAR_ALLOW_PA,
            "count": 2,
        },
    }


def conventional_geometry() -> dict:
    geo = vtail_geometry()
    geo["revision_id"] = "conventional_tail_demo"
    geo.pop("vtail")
    geo["tail"] = {
        "layout": "conventional",
        "S_h": 0.05,
        "S_v": 0.04,
        "l_h": TAIL_ARM,
        "l_v": TAIL_ARM,
    }
    return geo


def default_mission() -> dict:
    return {
        "cruise_mps": CRUISE_MPS,
        "rho": RHO,
        "g": G,
        "reserve_fraction": RESERVE,
    }


def default_parts(
    *,
    battery_mass_kg: float | None = BATTERY_MASS_KG,
    battery_energy_wh: float = BATTERY_ENERGY_WH,
) -> list[dict]:
    return [
        {"id": "wing_L", "type": "wing", "mass_kg": 0.35},
        {"id": "wing_R", "type": "wing", "mass_kg": 0.35},
        {"id": "fuse", "type": "fuselage", "mass_kg": 0.50},
        {"id": "vtail_L", "type": "tail", "mass_kg": 0.08},
        {"id": "vtail_R", "type": "tail", "mass_kg": 0.08},
        {
            "id": "spar_L",
            "type": "spar",
            "mass_kg": 0.12,
            "specs": {"Do": SPAR_DO, "Di": SPAR_DI, "allow_pa": SPAR_ALLOW_PA},
        },
        {
            "id": "spar_R",
            "type": "spar",
            "mass_kg": 0.12,
            "specs": {"Do": SPAR_DO, "Di": SPAR_DI, "allow_pa": SPAR_ALLOW_PA},
        },
        {
            "id": "battery",
            "type": "battery",
            "mass_kg": battery_mass_kg,
            "x": BATTERY_X,
            "specs": {"energy_wh": battery_energy_wh, "chemistry": "lipo"},
        },
        {"id": "motor", "type": "motor", "mass_kg": 0.13, "specs": {"kv": 900, "rm": 0.08, "i0": 0.6, "imax": 25}},
        {"id": "prop", "type": "prop", "mass_kg": 0.03},
        {"id": "esc", "type": "esc", "mass_kg": 0.05, "specs": {"imax": 30}},
        {"id": "servo_L", "type": "servo", "mass_kg": 0.03},
        {"id": "servo_R", "type": "servo", "mass_kg": 0.03},
        {"id": "payload", "type": "payload", "mass_kg": 0.20, "locked": True},
    ]


def check_by_id(result: dict, check_id: str) -> dict:
    for item in result["checks"]:
        if item["id"] == check_id:
            return item
    raise KeyError(check_id)


def metric(result: dict, name: str) -> dict:
    return result["metrics"][name]


def all_missing_fields(result: dict) -> list[str]:
    found: list[str] = list(result.get("missing_fields") or [])
    for item in result.get("checks") or []:
        found.extend(item.get("missing_fields") or [])
    for claim in (result.get("metrics") or {}).values():
        if isinstance(claim, dict):
            found.extend(claim.get("missing_fields") or [])
    for claim in result.get("quarantined") or []:
        if isinstance(claim, dict):
            found.extend(claim.get("missing_fields") or [])
    return found
