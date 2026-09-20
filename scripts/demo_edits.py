"""End-to-end demo: import the Avenger, confirm it, run four edits, accept one.

    .venv/bin/python scripts/demo_edits.py [workdir]

Prints one line per step. Everything it writes is throwaway except the STEP files.
"""
from __future__ import annotations

import sys, time, pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
for pkg in ("contracts", "ingest", "cad", "edits", "viewer"):
    sys.path.insert(0, str(REPO / "packages" / pkg))

from dronebench_ingest import stage_archive, inspect_sources, detect_variants, confirm, load_manifest
from dronebench_contracts.models import CadEditRequest, EditOperation
from dronebench_edits.apply import apply_edit
from dronebench_edits import store


def main(workdir: str = "/tmp/avenger_demo") -> int:
    wd = pathlib.Path(workdir); wd.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    staged = stage_archive(REPO / "vendor_assets" / "avenger", wd / "design")
    variants = detect_variants(inspect_sources(staged))
    pick = lambda g, want: next(o for o in next(v for v in variants if v.group_id == g).options if want in o)
    base = confirm(wd / "design", units="mm", mirror="x=0", confirmed_by="demo",
                   design_id="titan_avenger", title="Titan Avenger",
                   variants={"wing3": pick("wing3", "16mm"), "fuse3": pick("fuse3", "clean")})
    man = load_manifest(wd / "design")
    print(f"[{time.time()-t0:5.1f}s] confirmed {base.revision_id}: {len(man.parts)} parts "
          f"({sum(1 for p in man.parts if p.mirror_of)} mirrored)")

    battery = next(p.part_id for p in man.parts if p.category == "battery")
    edits = [
        ("battery +20 mm forward", EditOperation.translate_component, [battery], {"delta_m": [0.02, 0, 0]}),
        ("spar 10 -> 12 mm",       EditOperation.resize_spar,         ["recon_spar"], {"outer_d_mm": 12.0}),
        ("spar -> 17 mm (blocked)",EditOperation.resize_spar,         ["recon_spar"], {"outer_d_mm": 17.0}),
        ("wing tip +0.1 m",        EditOperation.set_wing_tip_extension, [],          {"extension_m": 0.1}),
    ]
    results = {}
    for label, op, targets, params in edits:
        t = time.time()
        r = apply_edit(wd / "design", CadEditRequest(base_revision_id=base.revision_id, operation=op,
                                                     target_part_ids=targets, parameters=params))
        results[label] = r
        verified = getattr(r, "verified", None)
        print(f"[{time.time()-t0:5.1f}s] {label:26s} {r.status:8s} "
              f"{'verified' if verified else 'unverified' if verified is False else ''} "
              f"{r.preview_revision_id or '-'} ({time.time()-t:.1f}s)")
        if r.error:
            print(f"            reason: {r.error.code.value}: {r.error.message[:120]}")
        for c in r.changes[:3]:
            print(f"            {c.get('part_id')}.{c.get('field')}: {c.get('before')} -> {c.get('after')} {c.get('unit','')}")
        failed = [c.name for c in r.checks if not c.passed]
        print(f"            checks {sum(1 for c in r.checks if c.passed)}/{len(r.checks)}"
              + (f", failed: {failed}" if failed else ""))

    ok = next((r for r in results.values() if r.status == "ok" and r.preview_revision_id), None)
    if ok:
        m = store.commit(wd / "design", ok.preview_revision_id, expected_active=base.revision_id)
        print(f"[{time.time()-t0:5.1f}s] accepted {m.revision_id} -> active {store.active_revision(wd/'design')}")
        print(f"            history: {[(h.revision_id, h.state.value, h.cause) for h in store.history(wd/'design')]}")
    else:
        print("            nothing committable")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
