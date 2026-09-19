/**
 * The part list.
 *
 * Selection is shared state, so picking here moves the schematic, the inspector, and the graph.
 * An occurrence with no mass evidence is amber *and* says "mass unknown" — colour alone is not a
 * signal every viewer can read, and this is the state the whole product turns on.
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
      byRole.set(role, [...(byRole.get(role) ?? []), occurrence]);
    }
    return [...byRole.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [parts, filter]);

  if (!parts) return <p className="muted">No revision loaded.</p>;

  const unknown = Object.keys(parts.unknown_claims ?? {});
  const total = parts.parts.occurrences.length;
  const matched = grouped.reduce((sum, [, list]) => sum + list.length, 0);

  return (
    <div className="parttree">
      <header>
        <h2>Parts</h2>
        <span className="muted num">
          {filter ? `${matched} of ${total}` : total}
        </span>
      </header>

      <input
        type="search"
        placeholder="Filter by name, id, or role"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        aria-label="Filter parts"
      />

      {unknown.length > 0 ? (
        <p className="unknown-callout">
          <strong>
            {unknown.length} part{unknown.length === 1 ? " has" : "s have"} no mass evidence.
          </strong>
          Mass, centre of gravity, and every weight-dependent check stay unknown until a value with
          provenance is entered.
        </p>
      ) : null}

      {matched === 0 ? (
        <p className="muted">Nothing matches “{filter}”.</p>
      ) : null}

      {grouped.map(([role, occurrences]) => (
        <section key={role}>
          <h3>{role.replace(/_/g, " ")}</h3>
          <ul>
            {occurrences.map((occurrence) => {
              const mass = occurrence.mass_kg.value;
              const known = mass !== null && mass !== undefined;
              const capabilities = parts.capabilities[occurrence.part_id] ?? [];
              const selected = occurrence.part_id === selectedPartId;
              return (
                <li key={occurrence.part_id}>
                  <button
                    type="button"
                    className={selected ? "part is-selected" : "part"}
                    onClick={() => selectPart(selected ? null : occurrence.part_id)}
                    aria-pressed={selected}
                  >
                    <span className="name">{occurrence.name}</span>
                    <span className={known ? "mass" : "mass is-unknown"}>
                      {known ? `${(mass as number).toFixed(3)} kg` : "mass unknown"}
                    </span>
                    {occurrence.locked || occurrence.mirror_of || capabilities.length ? (
                      <span className="flags">
                        {capabilities.length ? (
                          <span className="flag is-editable" title={capabilities.join(", ")}>
                            editable
                          </span>
                        ) : null}
                        {occurrence.locked ? (
                          <span className="flag is-locked" title="Mission payload">
                            locked
                          </span>
                        ) : null}
                        {occurrence.mirror_of ? (
                          <span className="flag" title={`mirrors ${occurrence.mirror_of}`}>
                            mirrored
                          </span>
                        ) : null}
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
