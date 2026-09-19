/**
 * The review panel (architecture section 10, Improve).
 *
 * "Recommendation cards explain the specific issue, evidence, exact editable parameter,
 * before/after modeled result, geometry diff and tradeoff... Disable acceptance while preview is
 * incomplete or stale; decline always remains available."
 *
 * Two rules are enforced in the markup rather than left to discipline:
 *
 * - Accept is disabled unless the card is `review_ready` with a preview hash to quote. Decline is
 *   never disabled, because declining is always a legitimate answer.
 * - Every tradeoff is listed, worsening ones included and not collapsed. A proposal that buys spar
 *   margin with mass has to show the mass.
 *
 * Missing-evidence requests render above the proposals, because a proposal ranked on an unknown
 * input is not worth reading yet.
 */

import { useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import type { EvidenceRequest, Recommendation, Tradeoff } from "@/lib/contracts.gen";

export function ReviewPanel() {
  const { recommendations, recommend, evaluation, busy, revisionId } = useWorkbench();

  if (!revisionId) return <p className="muted">No revision loaded.</p>;

  return (
    <div className="review">
      <header>
        <h2>Improve</h2>
        <button
          type="button"
          className="primary"
          onClick={() => void recommend()}
          disabled={Boolean(busy)}
        >
          {recommendations ? "Regenerate proposals" : "Generate proposals"}
        </button>
      </header>

      {evaluation ? <CheckStrip /> : null}

      {!recommendations ? (
        <p className="muted">
          Generate proposals to see bounded changes for the failing checks. Each one is previewed
          on a real child revision before it is shown.
        </p>
      ) : null}

      {recommendations?.evidence_requests?.length ? (
        <section className="requests">
          <h3>Asked for before any number is promised</h3>
          {recommendations.evidence_requests.map((request) => (
            <EvidenceRequestCard key={request.request_id} request={request} />
          ))}
        </section>
      ) : null}

      {recommendations?.generated?.length ? (
        <section className="cards">
          {recommendations.generated
            .slice()
            .sort(
              (a, b) =>
                indexOf(recommendations.displayed_proposal_ids ?? [], a.proposal_id) -
                indexOf(recommendations.displayed_proposal_ids ?? [], b.proposal_id),
            )
            .map((proposal) => (
              <ProposalCard
                key={proposal.proposal_id}
                proposal={proposal}
                displayed={
                  recommendations.displayed_proposal_ids?.includes(proposal.proposal_id) ?? false
                }
              />
            ))}
        </section>
      ) : null}

      {recommendations?.budget_notes?.length ? (
        <details className="notes">
          <summary>How these were chosen ({recommendations.budget_notes.length} notes)</summary>
          <ul>
            {recommendations.budget_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function indexOf(order: string[], id: string): number {
  const position = order.indexOf(id);
  return position === -1 ? Number.MAX_SAFE_INTEGER : position;
}

function CheckStrip() {
  const { evaluation } = useWorkbench();
  if (!evaluation) return null;
  return (
    <ul className="checkstrip">
      {(evaluation.checks ?? []).map((check) => (
        <li key={check.check_id} className={`check ${check.status}`} title={check.reason}>
          <span className="check-status">{check.status}</span>
          <span className="check-id">{check.check_id}</span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceRequestCard({ request }: { request: EvidenceRequest }) {
  const { selectPart, setMode } = useWorkbench();
  return (
    <article className="card request">
      <h4>{request.title}</h4>
      <p>{request.why_it_matters}</p>
      <p className="muted">
        Blocks: {request.blocked_check_ids?.join(", ") || "nothing"} · acceptable sources:{" "}
        {request.suggested_source_kinds?.join(", ")}
      </p>
      {request.target_part_id ? (
        <button
          type="button"
          onClick={() => {
            selectPart(request.target_part_id!);
            setMode("inspect");
          }}
        >
          Enter a value in Inspect
        </button>
      ) : null}
    </article>
  );
}

function ProposalCard({
  proposal,
  displayed,
}: {
  proposal: Recommendation;
  displayed: boolean;
}) {
  const { decide, busy } = useWorkbench();
  const [reason, setReason] = useState("");

  const preview = proposal.preview ?? null;
  const evaluated = Boolean(preview?.evaluation);
  const acceptable = proposal.state === "review_ready" && Boolean(preview?.preview_hash);
  const worsening = (proposal.tradeoffs ?? []).filter((t) => t.direction === "worsens");
  const improving = (proposal.tradeoffs ?? []).filter((t) => t.direction === "improves");
  const informational = (proposal.tradeoffs ?? []).filter((t) => t.direction === "informational");

  return (
    <article className={`card proposal state-${proposal.state} ${displayed ? "" : "demoted"}`}>
      <header>
        <h3>{evaluated ? proposal.title : "Unevaluated proposal"}</h3>
        <span className={`chip state-${proposal.state}`}>{proposal.state}</span>
        {proposal.origin === "provider" ? (
          <span className="chip" title="Authored by the model, validated identically">
            model-authored
          </span>
        ) : null}
      </header>

      <p className="issue">
        <strong>Issue:</strong> {proposal.issue}
      </p>
      <p className="rationale">{proposal.rationale}</p>

      <dl className="operation">
        <dt>Operation</dt>
        <dd>
          <code>{proposal.operation.operation}</code> on{" "}
          <code>{proposal.operation.target_part_id}</code>
        </dd>
      </dl>

      {proposal.prerequisites?.length ? (
        <details>
          <summary>Prerequisites this rests on</summary>
          <ul>
            {proposal.prerequisites.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {proposal.evidence_path ? (
        <details>
          <summary>Evidence path</summary>
          <ol className="path">
            {proposal.evidence_path.steps.map((step, index) => (
              <li key={index}>
                {step.from_label} —<em>{step.relation}</em>→ {step.to_label}
              </li>
            ))}
          </ol>
          <p className="muted">{proposal.evidence_path.conclusion}</p>
        </details>
      ) : null}

      {preview ? (
        <p className="muted">
          Previewed on revision <code>{preview.preview_revision_id.slice(0, 12)}</code>
          {preview.evaluation
            ? ` · ${preview.evaluation.verified_feasible ? "verified feasible" : "not feasible"} within the implemented model`
            : " · not evaluated"}
        </p>
      ) : (
        <p className="muted">No preview has been built yet.</p>
      )}

      {preview?.blocked_reasons?.length ? (
        <div className="blocked">
          <strong>Blocked by:</strong>
          <ul>
            {preview.blocked_reasons.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {proposal.tradeoffs?.length ? (
        <section className="tradeoffs">
          <h4>Tradeoffs</h4>
          <TradeoffList title="Improves" rows={improving} />
          <TradeoffList title="Costs" rows={worsening} />
          {informational.length ? (
            <details>
              <summary>
                Moved, but not better or worse on its own ({informational.length})
              </summary>
              <TradeoffList title="" rows={informational} />
            </details>
          ) : null}
        </section>
      ) : null}

      <footer className="actions">
        <button
          type="button"
          className="primary"
          disabled={!acceptable || Boolean(busy)}
          title={
            acceptable
              ? "Commit precisely this preview"
              : "Acceptance is disabled until a complete, feasible preview exists"
          }
          onClick={() =>
            void decide(proposal.proposal_id, "accept", preview?.preview_hash ?? undefined)
          }
        >
          Accept
        </button>

        <input
          type="text"
          placeholder="Reason (optional)"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-label="Reason for declining"
        />
        <button
          type="button"
          disabled={Boolean(busy)}
          onClick={() =>
            void decide(proposal.proposal_id, "decline", undefined, reason || undefined)
          }
        >
          Decline
        </button>
      </footer>
    </article>
  );
}

function TradeoffList({ title, rows }: { title: string; rows: Tradeoff[] }) {
  if (!rows.length) return null;
  return (
    <div className="tradeoff-group">
      {title ? <h5>{title}</h5> : null}
      <ul>
        {rows.map((row) => (
          <li key={row.metric} className={`t-${row.direction}`}>
            <span className="metric">{row.metric}</span>
            <span className="values">
              {format(row.baseline)} → {format(row.candidate)} {row.unit}
            </span>
            {row.basis ? <span className="muted basis">{row.basis}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function format(value: number | null | undefined): string {
  if (value === null || value === undefined) return "unknown";
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e6)) return value.toExponential(3);
  return value.toFixed(magnitude < 1 ? 4 : 3);
}
