/**
 * The part tree (architecture section 10, Inspect).
 *
 * "Selection synchronizes tree, mesh, bounded graph neighborhood and claims." Selection lives in
 * the shared context, so clicking here moves every other panel.
 *
 * Unknowns are amber and carry a text label as well as a colour, because section 10 asks for
 * "text/status icons for accessibility" rather than colour alone.
 */

import { useMemo, useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import type { PartOccurrence } from "@/lib/contracts.gen";

export function PartTree() {
  const { parts, selectedPartId, selectPart } = useWorkbench();
  const [filter, setFilter] = useState("");

  const grouped = useMemo(() => {
    const occurrences = parts?.parts.occurrences ?? [];
    const needle = filter.trim().toLowerCase();
    const matching = needle
      ? occurrences.filter(
          (occurrence) =>
            occurrence.name.toLowerCase().includes(needle) ||
            occurrence.part_id.toLowerCase().includes(needle) ||
            (occurrence.role ?? "").toLowerCase().includes(needle),
        )
      : occurrences;

    const byRole = new Map<string, PartOccurrence[]>();
    for (const occurrence of matching) {
      const role = occurrence.role ?? "unknown";
      const bucket = byRole.get(role) ?? [];
      bucket.push(occurrence);
      byRole.set(role, bucket);
    }
    return [...byRole.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [parts, filter]);

  const unknownCount = Object.keys(parts?.unknown_claims ?? {}).length;

  if (!parts) return <p className="muted">No revision loaded.</p>;

  return (
    <div className="parttree">
      <header>
        <h2>Parts</h2>
        <span className="muted">{parts.parts.occurrences.length} installed</span>
      </header>

      <input
        type="search"
        placeholder="Filter by name, id, or role"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        aria-label="Filter parts"
      />

      {unknownCount > 0 ? (
        <p className="unknown-banner">
          <span className="chip unknown">unknown</span>
          {unknownCount} occurrence{unknownCount === 1 ? "" : "s"} have no mass evidence. Every
          weight-dependent check stays unknown until a value with provenance is entered.
        </p>
      ) : null}

      {grouped.map(([role, occurrences]) => (
        <section key={role}>
          <h3>{role.replace(/_/g, " ")}</h3>
          <ul>
            {occurrences.map((occurrence) => {
              const massKnown = occurrence.mass_kg.value !== null;
              const capabilities = parts.capabilities[occurrence.part_id] ?? [];
              return (
                <li key={occurrence.part_id}>
                  <button
                    type="button"
                    className={occurrence.part_id === selectedPartId ? "part selected" : "part"}
                    onClick={() => selectPart(occurrence.part_id)}
                    aria-current={occurrence.part_id === selectedPartId}
                  >
                    <span className="name">{occurrence.name}</span>
                    <span className={massKnown ? "mass" : "mass unknown"}>
                      {massKnown
                        ? `${(occurrence.mass_kg.value as number).toFixed(3)} kg`
                        : "mass unknown"}
                    </span>
                    {occurrence.locked ? (
                      <span className="chip locked" title="Mission payload; cannot be edited">
                        locked
                      </span>
                    ) : null}
                    {occurrence.mirror_of ? (
                      <span className="chip" title={`mirrors ${occurrence.mirror_of}`}>
                        mirrored
                      </span>
                    ) : null}
                    {capabilities.length ? (
                      <span className="chip editable" title={capabilities.join(", ")}>
                        editable
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
