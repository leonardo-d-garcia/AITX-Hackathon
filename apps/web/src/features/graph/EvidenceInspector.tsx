/**
 * The evidence inspector (architecture section 10, Inspect).
 *
 * Shows every claim on the selected occurrence with its status, source kind, evidence, and
 * assumptions - and makes an unknown mass actionable: "make it possible to enter a value with
 * provenance".
 *
 * A value entered here is `manual` evidence. There is deliberately no way to record one as
 * inferred, because section 5 says geometry does not determine mass.
 */

import { useEffect, useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import { api, isFittingAlternatives, type FittingAlternatives } from "@/lib/api";
import type { Claim, ExplanationPath } from "@/lib/contracts.gen";

type Answer = ExplanationPath | FittingAlternatives | null;

const QUESTIONS = [
  { id: "mass_evidence", label: "What supports this mass?" },
  { id: "what_fails_if_moved", label: "What fails if this moves?" },
  { id: "affected_by_edit", label: "What does changing this affect?" },
  { id: "fitting_alternatives", label: "Which alternatives actually fit?" },
] as const;

export function EvidenceInspector() {
  const { parts, selectedPartId, revisionId, confirmDesign } = useWorkbench();
  const [question, setQuestion] = useState<string>("mass_evidence");
  const [answer, setAnswer] = useState<Answer>(null);
  const [draft, setDraft] = useState("");

  const occurrence = parts?.parts.occurrences.find((item) => item.part_id === selectedPartId);

  useEffect(() => {
    setAnswer(null);
    setDraft("");
    if (!revisionId || !selectedPartId) return;
    void api
      .explain(revisionId, selectedPartId, question)
      .then(setAnswer)
      .catch(() => setAnswer(null));
  }, [revisionId, selectedPartId, question]);

  if (!occurrence) {
    return (
      <div className="inspector">
        <h2>Evidence</h2>
        <p className="muted">Select a part to see what is known about it, and what is not.</p>
      </div>
    );
  }

  const massUnknown = occurrence.mass_kg.value === null;

  const submitMass = async () => {
    const value = Number.parseFloat(draft);
    if (!Number.isFinite(value) || value <= 0) return;
    await confirmDesign({
      reconstruction: parts?.geometry_features.reconstruction_confirmed ?? true,
      claims: [
        {
          part_id: occurrence.part_id,
          value,
          unit: "kg",
          // The fixture's own specification is the source of record for a hand-entered value.
          evidence_id: "ev_fixture-spec",
        },
      ],
    });
  };

  return (
    <div className="inspector">
      <h2>{occurrence.name}</h2>
      <p className="muted">
        {occurrence.part_id} · {occurrence.role}
        {occurrence.mirror_of ? ` · mirrors ${occurrence.mirror_of}` : ""}
      </p>

      <ClaimRow name="mass_kg" claim={occurrence.mass_kg} />
      {Object.entries(occurrence.claims?.claims ?? {}).map(([name, claim]) => (
        <ClaimRow key={name} name={name} claim={claim} />
      ))}

      {massUnknown ? (
        <form
          className="enter-value"
          onSubmit={(event) => {
            event.preventDefault();
            void submitMass();
          }}
        >
          <label htmlFor="mass-entry">
            Enter a measured mass (kg). It is recorded as <strong>manual</strong> evidence against
            the fixture specification, not inferred from geometry.
          </label>
          <div className="row">
            <input
              id="mass-entry"
              type="number"
              step="0.001"
              min="0"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="0.045"
            />
            <button type="submit" disabled={!draft}>
              Record with provenance
            </button>
          </div>
        </form>
      ) : null}

      <section className="questions">
        <h3>Trace</h3>
        <div className="tabs">
          {QUESTIONS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={entry.id === question ? "tab active" : "tab"}
              onClick={() => setQuestion(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {answer === null ? (
          <p className="muted">No answer for this question on this part.</p>
        ) : isFittingAlternatives(answer) ? (
          <FitTable answer={answer} />
        ) : (
          <PathView path={answer} />
        )}
      </section>
    </div>
  );
}

function ClaimRow({ name, claim }: { name: string; claim: Claim }) {
  const known = claim.value !== null;
  return (
    <div className={known ? "claim" : "claim unknown"}>
      <span className="claim-name">{name}</span>
      <span className="claim-value">
        {known ? `${claim.value} ${claim.unit}` : "unknown"}
      </span>
      <span className={`chip status-${claim.status}`}>{claim.status}</span>
      <span className="chip source">{claim.source_kind}</span>
      {claim.evidence_ids?.length ? (
        <span className="muted">{claim.evidence_ids.join(", ")}</span>
      ) : null}
      {claim.assumptions?.length ? (
        <ul className="assumptions">
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
      <p className="question">{path.question}</p>
      <ol>
        {path.steps.map((step, index) => (
          <li key={`${step.from_id}-${step.relation}-${step.to_id}-${index}`}>
            <span className="node">{step.from_label}</span>
            <span className={`relation status-${step.status}`}>{step.relation}</span>
            <span className="node">{step.to_label}</span>
          </li>
        ))}
      </ol>
      <p className="conclusion">{path.conclusion}</p>
      <p className="muted">
        Weakest link on this path: <strong>{path.weakest_status}</strong>
      </p>
      {path.missing_evidence?.length ? (
        <div className="missing">
          <strong>Missing:</strong>
          <ul>
            {path.missing_evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function FitTable({ answer }: { answer: FittingAlternatives }) {
  if (!answer.results.length) {
    return <p className="muted">{answer.note}</p>;
  }
  return (
    <div className="fit">
      <table>
        <thead>
          <tr>
            <th>Catalog item</th>
            <th>Mass</th>
            <th>Fits</th>
            <th>Why not</th>
          </tr>
        </thead>
        <tbody>
          {answer.results.map((row) => (
            <tr key={row.catalog_item_id} className={row.fits ? "" : "no-fit"}>
              <td>
                {row.display_name}
                <span className="chip synthetic">synthetic</span>
              </td>
              <td>{row.mass_kg === null ? "unknown" : `${row.mass_kg.toFixed(3)} kg`}</td>
              <td>{row.fits ? "yes" : "no"}</td>
              <td className="muted">{row.reasons.join("; ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{answer.note}</p>
    </div>
  );
}
