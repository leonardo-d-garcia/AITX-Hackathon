/**
 * The demo shell.
 *
 * A single narrative in five beats, each one a real screen rather than a slide:
 *
 *   1. Ingest    — read the supplied archive, report what it does and does not contain
 *   2. Inspect   — orbit the real geometry, select parts, see the unknowns
 *   3. Graph     — the dependency path from a part to the constraint it feeds
 *   4. Improve   — bounded proposals, accept one, watch the geometry change
 *   5. Fly       — the same aircraft flown with and without the change
 *
 * What is real: the 24 STL meshes, the frame mapping, the variant exclusions, the unknown-mass
 * propagation, the graph traversal, the proposal arithmetic, and the accept transaction. What is
 * staged for the demo: the VSPAERO numbers, which are a recorded run rather than a live solve, and
 * are labelled as such on screen.
 */

import { useCallback, useEffect, useState } from "react";

import { TitanScene, type ViewMode } from "@/viewport/TitanScene";
import { EXCLUDED_VARIANTS, TITAN_ENVELOPES, TITAN_PARTS } from "@/viewport/titan";

import { DEMO_RUNS, type DemoProposal } from "./data";
import { Stage, STAGES, type StageId } from "./stages";
import "./demo.css";

const SCENE_PALETTE = {
  bg: "#fbfbfa",
  surface: "#dcdcd8",
  line: "#7d7d79",
  accent: "#2a52c9",
  unknown: "#c08419",
};

export function Demo() {
  const [stage, setStage] = useState<StageId>("ingest");
  const [loaded, setLoaded] = useState(0);
  const [total, setTotal] = useState(TITAN_PARTS.length);
  const [selected, setSelected] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [declined, setDeclined] = useState<string[]>([]);
  const [flying, setFlying] = useState(false);
  const [telemetry, setTelemetry] = useState({ t: 0, distanceKm: 0, energyWh: 0, speed: 0 });

  const ingestDone = loaded >= total && total > 0;
  const hasCandidate = accepted.length > 0;

  const viewMode: ViewMode =
    stage === "graph" ? "exploded" : stage === "improve" && hasCandidate ? "diff" : "assembly";

  useEffect(() => {
    setFlying(stage === "fly");
  }, [stage]);

  // Advance out of ingest on its own once the archive is in: the loader is the content there.
  useEffect(() => {
    if (stage === "ingest" && ingestDone) {
      const timer = setTimeout(() => setStage("inspect"), 900);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [stage, ingestDone]);

  const onProgress = useCallback((n: number, t: number) => {
    setLoaded(n);
    setTotal(t);
  }, []);

  const accept = (proposal: DemoProposal) => {
    setAccepted((previous) => (previous.includes(proposal.id) ? previous : [...previous, proposal.id]));
    setSelected(proposal.targetPartId);
  };
  const decline = (proposal: DemoProposal) => {
    setDeclined((previous) => (previous.includes(proposal.id) ? previous : [...previous, proposal.id]));
  };

  return (
    <div className="demo">
      <header className="demo-bar">
        <p className="demo-mark">DroneBench</p>
        <p className="demo-source">
          Titan Avenger · 24 supplied meshes · 580,404 triangles
        </p>
        <nav className="demo-stages" aria-label="Demo stage">
          {STAGES.map((entry, index) => (
            <button
              key={entry.id}
              type="button"
              className={entry.id === stage ? "stage-step is-active" : "stage-step"}
              onClick={() => setStage(entry.id)}
              aria-current={entry.id === stage}
              disabled={!ingestDone && entry.id !== "ingest"}
            >
              <span className="stage-index">{index + 1}</span>
              {entry.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="demo-stage">
        <TitanScene
          mode={viewMode}
          showCandidate={hasCandidate}
          flying={flying}
          selectedPartId={selected}
          onSelect={setSelected}
          onProgress={onProgress}
          onFlight={setTelemetry}
          palette={SCENE_PALETTE}
        />

        {stage === "ingest" ? <Ingest loaded={loaded} total={total} /> : null}

        {stage !== "ingest" ? (
          <aside className="demo-panel">
            <Stage
              stage={stage}
              selected={selected}
              onSelect={setSelected}
              accepted={accepted}
              declined={declined}
              onAccept={accept}
              onDecline={decline}
              telemetry={telemetry}
              flying={flying}
            />
          </aside>
        ) : null}

        {stage === "fly" ? <FlightHud telemetry={telemetry} candidate={hasCandidate} /> : null}
      </div>
    </div>
  );
}

function Ingest({ loaded, total }: { loaded: number; total: number }) {
  const pct = total ? Math.round((loaded / total) * 100) : 0;
  return (
    <div className="ingest">
      <div className="ingest-card">
        <h1>Reading the supplied archive</h1>
        <p className="ingest-lede">
          Titan Avenger, as delivered. No STEP, no feature history, no bill of materials, no
          assembly manifest — 24 binary meshes and nothing that says how they go together.
        </p>

        <div className="ingest-meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="ingest-fill" style={{ width: `${pct}%` }} />
        </div>
        <p className="ingest-count num">
          {loaded} of {total} meshes · {pct}%
        </p>

        <dl className="ingest-facts">
          <div>
            <dt>Triangles</dt>
            <dd className="num">580,404</dd>
          </div>
          <div>
            <dt>Frame</dt>
            <dd>FRD, nose datum estimated</dd>
          </div>
          <div>
            <dt>Variants excluded</dt>
            <dd className="num">{EXCLUDED_VARIANTS.length}</dd>
          </div>
          <div>
            <dt>Envelopes added</dt>
            <dd className="num">{TITAN_ENVELOPES.length}</dd>
          </div>
        </dl>

        <ul className="ingest-notes">
          {EXCLUDED_VARIANTS.slice(0, 3).map((variant) => (
            <li key={variant.file}>
              <span className="num">{variant.file}</span> — {variant.why}
            </li>
          ))}
          <li>
            Bought components are not in the archive. They are added as labelled envelopes, never
            inferred from the file name.
          </li>
        </ul>
      </div>
    </div>
  );
}

function FlightHud({
  telemetry,
  candidate,
}: {
  telemetry: { t: number; distanceKm: number; energyWh: number; speed: number };
  candidate: boolean;
}) {
  const baseline = DEMO_RUNS.baseline;
  const improved = DEMO_RUNS.candidate;
  const run = candidate ? improved : baseline;
  const remaining = Math.max(0, run.usableWh * (1 - telemetry.t));

  return (
    <div className="hud">
      <div className="hud-block">
        <p className="hud-label">Distance</p>
        <p className="hud-value num">{telemetry.distanceKm.toFixed(1)}<span> km</span></p>
      </div>
      <div className="hud-block">
        <p className="hud-label">Airspeed</p>
        <p className="hud-value num">{run.cruiseMps.toFixed(0)}<span> m/s</span></p>
      </div>
      <div className="hud-block">
        <p className="hud-label">Energy remaining</p>
        <p className="hud-value num">{remaining.toFixed(1)}<span> Wh</span></p>
        <div className="hud-meter">
          <div className="hud-fill" style={{ width: `${(1 - telemetry.t) * 100}%` }} />
        </div>
      </div>
      <div className="hud-block">
        <p className="hud-label">Endurance</p>
        <p className="hud-value num">{run.enduranceMin.toFixed(1)}<span> min</span></p>
      </div>
      <div className="hud-block is-wide">
        <p className="hud-label">Configuration</p>
        <p className="hud-value-text">
          {candidate ? "With the accepted change" : "As supplied"}
        </p>
      </div>
    </div>
  );
}
