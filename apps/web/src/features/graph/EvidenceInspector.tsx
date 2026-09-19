/**
 * The evidence panel.
 *
 * Every claim on the selected occurrence with its status, source, evidence ids, and assumptions —
 * and, when a mass is unknown, a way to supply one. A value entered here is recorded as `manual`
 * evidence against a real evidence id. There is deliberately no path to record one as inferred,
 * because geometry does not determine mass.
 */

import { useEffect, useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import { api, isFittingAlternatives, type FittingAlternatives } from "@/lib/api";
import type { Claim, ExplanationPath } from "@/lib/contracts.gen";

type Answer = ExplanationPath | FittingAlternatives | null;

const QUESTIONS = [
  { id: "mass_evidence", label: "Mass evidence" },
  { id: "what_fails_if_moved", label: "If it moves" },
  { id: "affected_by_edit", label: "If it changes" },
  { id: "fitting_alternatives", label: "Alternatives" },
] as const;

export function EvidenceInspector() {
  const { parts, selectedPartId, revisionId, confirmDesign, busy } = useWorkbench();
  const [question, setQuestion] = useState<string>("mass_evidence");
  const [answer, setAnswer] = useState<Answer>(null);
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState("");

  const occurrence = parts?.parts.occurrences.find((item) => item.part_id === selectedPartId);

  useEffect(() => {
    setAnswer(null);
    setDraft("");
    if (!revisionId || !selectedPartId) return;
    setLoading(true);
    void api
      .explain(revisionId, selectedPartId, question)
      .then(setAnswer)
      .catch(() => setAnswer(null))
      .finally(() => setLoading(false));
  }, [revisionId, selectedPartId, question]);

  if (!occurrence) {
    return (
      <div className="inspector">
        <h2>Evidence</h2>
        <p className="muted">
          Select a part in the schematic or the list to see what is known about it, and what is not.
        </p>
      </div>
    );
  }

  const massUnknown = occurrence.mass_kg.value === null || occurrence.mass_kg.value === undefined;
  const value = Number.parseFloat(draft);
  const valid = Number.isFinite(value) && value > 0;

  const submit = async () => {
    if (!valid) return;
    await confirmDesign({
      // Carry the current decision forward; entering a mass is not a place to change it.
      reconstruction: parts?.geometry_features.reconstruction_confirmed ?? false,
      claims: [
        { part_id: occurrence.part_id, value, unit: "kg", evidence_id: "ev_fixture-spec" },
      ],
    });
  };

  return (
    <div className="inspector">
      <header>
        <h2>{occurrence.name}</h2>
        <p className="inspector-id">
          {occurrence.part_id} · {occurrence.role}
          {occurrence.mirror_of ? ` · mirrors ${occurrence.mirror_of}` : ""}
        </p>
      </header>

      <div>
        <ClaimRow name="mass_kg" claim={occurrence.mass_kg} />
        {Object.entries(occurrence.claims?.claims ?? {}).map(([name, claim]) => (
          <ClaimRow key={name} name={name} claim={claim} />
        ))}
      </div>

      {massUnknown ? (
        <form
          className="enter-value"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label htmlFor="mass-entry">
            Enter a measured mass. It is recorded as <strong>manual</strong> evidence against the
            fixture specification, and creates a new revision.
          </label>
          <div className="row">
            <input
              id="mass-entry"
              type="number"
              step="0.001"
              min="0"
              inputMode="decimal"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="kg"
            />
            <button type="submit" className="primary" disabled={!valid || Boolean(busy)}>
              {busy ? "Recording…" : "Record"}
            </button>
          </div>
        </form>
      ) : null}

      <section>
        <div className="tabs">
          {QUESTIONS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={entry.id === question ? "tab is-active" : "tab"}
              onClick={() => setQuestion(entry.id)}
              aria-pressed={entry.id === question}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {loading ? <p className="muted">Tracing…</p> : null}
        {!loading && answer === null ? (
          <p className="muted">Nothing to trace for this part yet.</p>
        ) : null}
        {!loading && answer !== null
          ? isFittingAlternatives(answer)
            ? <FitTable answer={answer} />
            : <PathView path={answer} />
          : null}
      </section>
    </div>
  );
}

function ClaimRow({ name, claim }: { name: string; claim: Claim }) {
  const known = claim.value !== null && claim.value !== undefined;
  return (
    <div className={known ? "claim" : "claim is-unknown"}>
      <span className="claim-name">{name}</span>
      <span className="claim-value">
        {known ? `${claim.value} ${claim.unit}` : "unknown"}
      </span>
      <span className="claim-meta">
        <span>{claim.status}</span>
        <span>·</span>
        <span>{claim.source_kind}</span>
        {claim.evidence_ids?.length ? (
          <>
            <span>·</span>
            <span>{claim.evidence_ids.join(", ")}</span>
          </>
        ) : null}
      </span>
      {claim.assumptions?.length ? (
        <ul className="claim-assumptions">
          {claim.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PathView({ path }: { path: ExplanationPath }) {
  return (
    <div className="path">
      {path.steps.length ? (
        <ol>
          {path.steps.map((step, index) => (
            <li key={`${step.from_id}-${step.relation}-${step.to_id}-${index}`}>
              <span className="node">{step.from_label}</span>
              <span className={`relation status-${step.status}`}>{step.relation}</span>
              <span className="node">{step.to_label}</span>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="conclusion">{path.conclusion}</p>
      {path.missing_evidence?.length ? (
        <p className="missing">Missing: {path.missing_evidence.join("; ")}</p>
      ) : null}
    </div>
  );
}

function FitTable({ answer }: { answer: FittingAlternatives }) {
  if (!answer.results.length) return <p className="muted">{answer.note}</p>;
  return (
    <div className="fit">
      <table>
        <thead>
          <tr>
            <th scope="col">Catalog item</th>
            <th scope="col">Mass</th>
            <th scope="col">Fits</th>
          </tr>
        </thead>
        <tbody>
          {answer.results.map((row) => (
            <tr key={row.catalog_item_id} className={row.fits ? "" : "no-fit"}>
              <td>
                {row.display_name}
                {row.reasons.length ? (
                  <div className="muted">{row.reasons.join("; ")}</div>
                ) : null}
              </td>
              <td className="num">{row.mass_kg === null ? "unknown" : row.mass_kg.toFixed(3)}</td>
              <td className={row.fits ? "verdict-yes" : "verdict-no"}>
                {row.fits ? "yes" : "no"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{answer.note}</p>
    </div>
  );
}
