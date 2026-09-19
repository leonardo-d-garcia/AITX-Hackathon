/**
 * Mount point for Team C's simulation view.
 *
 * `apps/web/src/features/simulation/` belongs to Team C (architecture section 11). Team B owns the
 * shell and the revision context; C replaces this body with the replay scene and its charts.
 *
 * Meanwhile it runs the reduced-order mission model for the active revision and shows the real
 * telemetry that comes back, labelled with its tier. Section 8 is emphatic that a replay is not
 * physical bench testing, so the assumptions are rendered in full rather than tucked behind a
 * disclosure chevron.
 */

import { useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import { ApiError, api } from "@/lib/api";
import type { SimulationRun } from "@/lib/contracts.gen";

export function MissionRun() {
  const { revisionId } = useWorkbench();
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const go = async () => {
    if (!revisionId) return;
    setNote(null);
    try {
      const response = await api.simulate(revisionId);
      setRun(response.run);
    } catch (caught) {
      setRun(null);
      setNote(caught instanceof ApiError ? caught.envelope.message : String(caught));
    }
  };

  const samples = run?.samples ?? [];
  const last = samples[samples.length - 1];

  return (
    <div className="run">
      <header>
        <h2>Simulate</h2>
        <span className="state">Team C</span>
        <button type="button" className="primary" onClick={() => void go()} disabled={!revisionId}>
          Run the mission model
        </button>
      </header>

      <p className="muted">
        Distance and energy integrated along the declared route at a fixed altitude and speed.
        Team C&apos;s replay scene replaces this panel.
      </p>

      {note ? <p className="muted">{note}</p> : null}

      {run && last ? (
        <>
          <dl className="factgrid">
            <div>
              <dt>Revision</dt>
              <dd>
                <code>{run.revision_id.slice(0, 12)}</code>
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{(run.flight_model_tier ?? "reduced_order_mission").replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Outcome</dt>
              <dd className={run.completed_route ? "" : "is-unconfirmed"}>
                {run.termination_reason.replace(/_/g, " ")}
              </dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{(last.t_s / 60).toFixed(1)} min</dd>
            </div>
            <div>
              <dt>Distance</dt>
              <dd>{last.distance_km.toFixed(1)} km</dd>
            </div>
            <div>
              <dt>Energy left</dt>
              <dd>{last.remaining_energy_wh.toFixed(1)} Wh usable</dd>
            </div>
          </dl>

          <EnergyTrace run={run} />

          <section className="limits">
            <h3>What this run assumes</h3>
            <ul>
              {(run.assumptions ?? []).map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </div>
  );
}

/** A plain SVG trace of remaining usable energy. Never clamped: zero means the run ended there. */
function EnergyTrace({ run }: { run: SimulationRun }) {
  const samples = run.samples ?? [];
  const first = samples[0];
  const last = samples[samples.length - 1];
  if (!first || !last || samples.length < 2) return null;

  const maxTime = last.t_s || 1;
  const maxEnergy = first.remaining_energy_wh || 1;
  const points = samples
    .map((sample) => {
      const x = 10 + (sample.t_s / maxTime) * 300;
      const y = 90 - (sample.remaining_energy_wh / maxEnergy) * 80;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 320 100" className="trace" role="img" aria-label="Remaining usable energy">
      <polyline points={points} fill="none" />
      <line x1="10" y1="90" x2="310" y2="90" className="axis" />
      <text x="10" y="99" className="axis-label">
        0
      </text>
      <text x="270" y="99" className="axis-label">
        {(maxTime / 60).toFixed(0)} min
      </text>
      <text x="10" y="12" className="axis-label">
        {maxEnergy.toFixed(0)} Wh usable
      </text>
    </svg>
  );
}
