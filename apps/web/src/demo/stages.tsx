/**
 * The four panels after ingest. One per beat of the demo, sharing the scene behind them.
 */

import { TITAN_ENVELOPES, TITAN_PARTS } from "@/viewport/titan";

import {
  DEMO_CHECKS,
  DEMO_PROPOSALS,
  DEMO_RUNS,
  SOLVER_NOTE,
  type DemoProposal,
} from "./data";

export type StageId = "ingest" | "inspect" | "graph" | "improve" | "fly";

export const STAGES: { id: StageId; label: string }[] = [
  { id: "ingest", label: "Ingest" },
  { id: "inspect", label: "Inspect" },
  { id: "graph", label: "Trace" },
  { id: "improve", label: "Improve" },
  { id: "fly", label: "Fly" },
];

const ALL_PARTS = [...TITAN_PARTS, ...TITAN_ENVELOPES];

interface StageProps {
  stage: StageId;
  selected: string | null;
  onSelect: (partId: string | null) => void;
  accepted: string[];
  declined: string[];
  onAccept: (proposal: DemoProposal) => void;
  onDecline: (proposal: DemoProposal) => void;
  telemetry: { t: number; distanceKm: number; energyWh: number; speed: number };
  flying: boolean;
}

export function Stage(props: StageProps) {
  if (props.stage === "inspect") return <Inspect {...props} />;
  if (props.stage === "graph") return <Trace {...props} />;
  if (props.stage === "improve") return <Improve {...props} />;
  if (props.stage === "fly") return <Fly {...props} />;
  return null;
}

/* ------------------------------------------------------------------ inspect */

function Inspect({ selected, onSelect, accepted }: StageProps) {
  const part = ALL_PARTS.find((entry) => entry.partId === selected);
  const unknown = ALL_PARTS.filter((entry) => entry.massKg === null);
  const known = ALL_PARTS.filter((entry) => entry.massKg !== null);
  const total = known.reduce((sum, entry) => sum + (entry.massKg ?? 0), 0);

  return (
    <div className="panel">
      <header className="panel-head">
        <h2>What the archive contains</h2>
        <p className="panel-sub">
          {ALL_PARTS.length} installed occurrences. Click any part in the model.
        </p>
      </header>

      <div className="stat-row">
        <div className="stat">
          <p className="stat-label">Established mass</p>
          <p className="stat-value num">{total.toFixed(2)}<span> kg</span></p>
        </div>
        <div className="stat is-unknown">
          <p className="stat-label">No mass evidence</p>
          <p className="stat-value num">{unknown.length}<span> parts</span></p>
        </div>
      </div>

      {part ? (
        <section className="detail">
          <h3>{part.name}</h3>
          <dl className="detail-rows">
            <div>
              <dt>Identity</dt>
              <dd className="num">{part.partId}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{part.role.replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Mass</dt>
              <dd className={part.massKg === null ? "is-unknown num" : "num"}>
                {part.massKg === null ? "unknown" : `${part.massKg.toFixed(3)} kg`}
              </dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{"massSource" in part ? part.massSource : "—"}</dd>
            </div>
            {"file" in part && part.file ? (
              <div>
                <dt>Mesh</dt>
                <dd className="num">{part.file}</dd>
              </div>
            ) : null}
            {"mirrorOf" in part && part.mirrorOf ? (
              <div>
                <dt>Mirrors</dt>
                <dd className="num">{part.mirrorOf}</dd>
              </div>
            ) : null}
          </dl>
          {part.massKg === null ? (
            <p className="callout">
              This mass is not established. It is not zero and it is not ignored — every
              weight-dependent result downstream is reported unknown until a measured value with
              provenance is entered.
            </p>
          ) : null}
        </section>
      ) : (
        <p className="panel-hint">Select a part to see its evidence.</p>
      )}

      <section className="list">
        <h3>Parts with no mass evidence</h3>
        <ul>
          {unknown.map((entry) => (
            <li key={entry.partId}>
              <button
                type="button"
                className={entry.partId === selected ? "row-btn is-selected" : "row-btn"}
                onClick={() => onSelect(entry.partId)}
              >
                <span>{entry.name}</span>
                <span className="row-flag">unknown</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {accepted.length ? <p className="panel-hint">{accepted.length} change accepted.</p> : null}
    </div>
  );
}

/* -------------------------------------------------------------------- trace */

function Trace({ selected, onSelect }: StageProps) {
  const failing = DEMO_CHECKS.filter((check) => check.status === "fail");
  const unknown = DEMO_CHECKS.filter((check) => check.status === "unknown");

  return (
    <div className="panel">
      <header className="panel-head">
        <h2>What depends on what</h2>
        <p className="panel-sub">
          Typed relations with their evidence. Proximity is never promoted to a joint.
        </p>
      </header>

      <section className="chain">
        <h3>Why the centre of gravity fails</h3>
        <ol className="chain-steps">
          <li>
            <button
              type="button"
              className={selected === "prt_battery" ? "chain-node is-selected" : "chain-node"}
              onClick={() => onSelect("prt_battery")}
            >
              Battery pack · 0.98 kg
            </button>
            <span className="chain-rel">constrained_by</span>
          </li>
          <li>
            <span className="chain-node is-constraint">CG envelope · fail</span>
            <span className="chain-rel">applies_to</span>
          </li>
          <li>
            <span className="chain-node is-constraint">Static margin · fail</span>
          </li>
        </ol>
        <p className="chain-note">
          Both failures have one cause. The pack is the heaviest movable mass and it sits at the
          back of its bay.
        </p>
      </section>

      <section className="checks">
        <h3>
          Checks · {failing.length} failing · {unknown.length} unknown
        </h3>
        <ul>
          {DEMO_CHECKS.map((check) => (
            <li key={check.id} className={`check-row is-${check.status}`}>
              <span className="check-flag">{check.status}</span>
              <span className="check-name">{check.title}</span>
              <span className="check-value num">{check.value}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ improve */

function Improve({ accepted, declined, onAccept, onDecline, onSelect }: StageProps) {
  return (
    <div className="panel">
      <header className="panel-head">
        <h2>Bounded proposals</h2>
        <p className="panel-sub">
          Each one previewed on a real child revision before it is offered. Accept or decline.
        </p>
      </header>

      {DEMO_PROPOSALS.map((proposal) => {
        const isAccepted = accepted.includes(proposal.id);
        const isDeclined = declined.includes(proposal.id);
        return (
          <article
            key={proposal.id}
            className={`proposal${isAccepted ? " is-accepted" : ""}${isDeclined ? " is-declined" : ""}`}
          >
            <header>
              <h3>{proposal.title}</h3>
              <span className={`pill${isAccepted ? " is-ok" : isDeclined ? " is-off" : ""}`}>
                {isAccepted ? "accepted" : isDeclined ? "declined" : proposal.recommended ? "recommended" : "optional"}
              </span>
            </header>

            <p className="proposal-issue">{proposal.issue}</p>
            <p className="proposal-op num">{proposal.operation}</p>
            <p className="proposal-why">{proposal.rationale}</p>

            <table className="tradeoff-table">
              <tbody>
                {proposal.tradeoffs.map((row) => (
                  <tr key={row.metric} className={`is-${row.direction}`}>
                    <th scope="row" className="num">{row.metric}</th>
                    <td className="num">{row.before}</td>
                    <td className="arrow">→</td>
                    <td className="num">{row.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <footer className="proposal-actions">
              <button
                type="button"
                className="primary"
                onClick={() => {
                  onAccept(proposal);
                  onSelect(proposal.targetPartId);
                }}
                disabled={isAccepted}
              >
                {isAccepted ? "Accepted" : "Accept and apply"}
              </button>
              <button type="button" onClick={() => onDecline(proposal)} disabled={isDeclined}>
                {isDeclined ? "Declined" : "Decline"}
              </button>
            </footer>
          </article>
        );
      })}

      {accepted.length ? (
        <section className="export">
          <h3>New revision</h3>
          <p>
            The accepted change is committed as an immutable child revision. The ghost in the model
            is the candidate geometry over the baseline.
          </p>
          <a className="button-link" href="/titan/manifest.json" download="updated_reconstruction.json">
            Download the revision manifest
          </a>
          <p className="panel-hint">
            STEP export needs the CAD kernel, which is not installed here. The workbench refuses
            rather than producing a file it cannot verify.
          </p>
        </section>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------------- fly */

function Fly({ accepted, telemetry }: StageProps) {
  const hasCandidate = accepted.length > 0;
  const baseline = DEMO_RUNS.baseline;
  const candidate = DEMO_RUNS.candidate;

  return (
    <div className="panel">
      <header className="panel-head">
        <h2>Same mission, both configurations</h2>
        <p className="panel-sub">
          Identical route, speed, atmosphere, and starting state. Only the design differs.
        </p>
      </header>

      <div className="compare">
        <div className="compare-col">
          <p className="compare-head">As supplied</p>
          <Metric label="Endurance" value={baseline.enduranceMin.toFixed(1)} unit="min" />
          <Metric label="Range" value={baseline.rangeKm.toFixed(1)} unit="km" />
          <Metric label="CG station" value={baseline.cgStation.toFixed(3)} unit="m" bad />
          <Metric label="Static margin" value={baseline.staticMargin.toFixed(1)} unit="%" bad />
          <p className="compare-outcome is-bad">{baseline.outcome}</p>
        </div>

        <div className={hasCandidate ? "compare-col is-live" : "compare-col is-muted"}>
          <p className="compare-head">With the accepted change</p>
          <Metric label="Endurance" value={candidate.enduranceMin.toFixed(1)} unit="min" good />
          <Metric label="Range" value={candidate.rangeKm.toFixed(1)} unit="km" good />
          <Metric label="CG station" value={candidate.cgStation.toFixed(3)} unit="m" good />
          <Metric label="Static margin" value={candidate.staticMargin.toFixed(1)} unit="%" good />
          <p className="compare-outcome is-good">{candidate.outcome}</p>
          {!hasCandidate ? (
            <p className="panel-hint">Accept the proposal in Improve to fly this configuration.</p>
          ) : null}
        </div>
      </div>

      <section className="solver">
        <h3>Where these numbers come from</h3>
        <dl className="detail-rows">
          <div>
            <dt>Solver</dt>
            <dd className="num">{SOLVER_NOTE.solver} · {SOLVER_NOTE.version}</dd>
          </div>
          <div>
            <dt>Alpha sweep</dt>
            <dd className="num">{SOLVER_NOTE.alphaSweep}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{SOLVER_NOTE.status}</dd>
          </div>
        </dl>
        <p className="panel-hint">
          A replay, not a live solve and not a flight test. The mission model is straight and level;
          the bank you see in the turn is a display convention, not a modelled manoeuvre load.
        </p>
      </section>

      <p className="panel-hint num">route {(telemetry.t * 100).toFixed(0)} % complete</p>
    </div>
  );
}

function Metric({
  label,
  value,
  unit,
  good,
  bad,
}: {
  label: string;
  value: string;
  unit: string;
  good?: boolean;
  bad?: boolean;
}) {
  return (
    <div className={`metric${good ? " is-good" : ""}${bad ? " is-bad" : ""}`}>
      <p className="metric-label">{label}</p>
      <p className="metric-value num">
        {value}
        <span> {unit}</span>
      </p>
    </div>
  );
}
