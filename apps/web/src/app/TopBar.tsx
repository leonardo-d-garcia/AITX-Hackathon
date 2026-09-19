/**
 * The persistent top bar (architecture section 10).
 *
 * Design and revision, the reference-versus-reconstruction label, the model fidelity, the mission,
 * and the STEP export status. Every one of these scopes a claim the rest of the screen makes, so
 * none of them may scroll away.
 */

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useWorkbench } from "./WorkbenchContext";

const TIER_LABEL: Record<string, string> = {
  analytic: "Engineering estimate — assumptions shown",
  vspaero_informed: "VSPAERO analysis + mission model",
  replay: "Model replay",
};

export function TopBar() {
  const { designId, revisionId, parts, evaluation, doctor, history } = useWorkbench();
  const [exportNote, setExportNote] = useState<string | null>(null);

  const representation = parts?.geometry_features.reconstruction_confirmed
    ? "Editable reconstruction"
    : "Original mesh reference";
  const confirmed =
    parts?.geometry_features.units_confirmed && parts?.geometry_features.frame_confirmed;

  const onExport = async () => {
    if (!revisionId) return;
    try {
      const result = await api.exportStep(revisionId);
      setExportNote(result.round_trip?.performed ? "STEP exported" : "no round trip performed");
    } catch (caught) {
      // A refusal is the honest answer while the CAD kernel is absent; show it as such.
      setExportNote(
        caught instanceof ApiError ? `unavailable — ${caught.envelope.code}` : "unavailable",
      );
    }
  };

  return (
    <header className="topbar">
      <div className="brand">DroneBench Studio</div>

      <dl className="scope">
        <div>
          <dt>Design</dt>
          <dd>{designId ?? "—"}</dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd title={revisionId ?? ""}>
            {revisionId ? revisionId.slice(0, 12) : "—"}
            <span className="muted"> · {history.length} in history</span>
          </dd>
        </div>
        <div>
          <dt>Representation</dt>
          <dd className={confirmed ? "" : "warn"}>
            {representation}
            {confirmed ? "" : " · unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Fidelity</dt>
          <dd>
            {evaluation ? TIER_LABEL[evaluation.fidelity] ?? evaluation.fidelity : "not evaluated"}
            {evaluation?.produced_by === "B-stub" ? (
              <span className="chip stub" title="Team C's evaluator is not installed yet">
                B-stub
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Mission</dt>
          <dd>{evaluation ? `${evaluation.registry_version}` : "—"}</dd>
        </div>
      </dl>

      <div className="export">
        <button type="button" onClick={() => void onExport()} disabled={!revisionId}>
          Export STEP
        </button>
        <span className={exportNote?.startsWith("unavailable") ? "muted warn" : "muted"}>
          {exportNote ??
            (doctor?.ports.cad.real_kernel ? "ready" : "unavailable — no CAD kernel installed")}
        </span>
      </div>
    </header>
  );
}
