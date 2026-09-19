/**
 * The scope line (architecture section 10).
 *
 * The only permanent chrome in the app. Everything it carries scopes a claim the rest of the
 * screen makes — which design, which revision, whether the geometry is confirmed, which fidelity
 * the numbers came from, and whether an export exists. None of it is decoration, so none of it
 * scrolls away.
 */

import { useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useWorkbench } from "./WorkbenchContext";

const TIER_CLAIM: Record<string, string> = {
  analytic: "Engineering estimate",
  vspaero_informed: "VSPAERO + mission model",
  replay: "Model replay",
};

export function StatusStrip() {
  const { designId, revisionId, parts, evaluation, doctor, history, busy } = useWorkbench();
  const [exportState, setExportState] = useState<{ tone: "idle" | "ok" | "warn"; text: string }>({
    tone: "idle",
    text: doctor?.ports.cad.real_kernel ? "ready" : "no CAD kernel",
  });

  const features = parts?.geometry_features;
  const confirmed = features?.units_confirmed && features?.frame_confirmed;

  const onExport = async () => {
    if (!revisionId) return;
    setExportState({ tone: "idle", text: "exporting…" });
    try {
      const result = await api.exportStep(revisionId);
      setExportState(
        result.round_trip?.passed
          ? { tone: "ok", text: "STEP verified" }
          : { tone: "warn", text: "round trip not performed" },
      );
    } catch (caught) {
      setExportState({
        tone: "warn",
        text: caught instanceof ApiError ? caught.envelope.code : "unavailable",
      });
    }
  };

  return (
    <header className="status">
      <p className="status-wordmark">DroneBench</p>

      <dl className="status-scope">
        <div className="scope-item">
          <dt>Design</dt>
          <dd>{designId?.replace("dsn_", "") ?? "—"}</dd>
        </div>
        <div className="scope-item">
          <dt>Revision</dt>
          <dd className="num" title={revisionId ?? ""}>
            {revisionId ? revisionId.replace("rev_", "").slice(0, 8) : "—"}
          </dd>
        </div>
        <div className="scope-item">
          <dt>States</dt>
          <dd className="num">{history.length}</dd>
        </div>
        <div className="scope-item">
          <dt>Geometry</dt>
          <dd className={confirmed ? "" : "is-unconfirmed"}>
            {features?.reconstruction_confirmed ? "reconstruction" : "reference mesh"}
            {confirmed ? "" : " · unconfirmed"}
          </dd>
        </div>
        <div className="scope-item">
          <dt>Fidelity</dt>
          <dd>
            {evaluation ? TIER_CLAIM[evaluation.fidelity] ?? evaluation.fidelity : "not evaluated"}
            {evaluation?.produced_by === "B-stub" ? (
              <span className="tag" title="Team C's evaluator is not installed yet">
                stub
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

      {busy ? (
        <p className="status-busy" role="status">
          {busy}
        </p>
      ) : null}

      <div className="status-export">
        <button type="button" onClick={() => void onExport()} disabled={!revisionId}>
          Export STEP
        </button>
        <p className={exportState.tone === "warn" ? "export-note is-warn" : "export-note"}>
          {exportState.text}
        </p>
      </div>
    </header>
  );
}
