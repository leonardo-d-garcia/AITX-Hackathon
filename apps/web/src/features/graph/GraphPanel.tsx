/**
 * The bounded dependency panel (architecture sections 7 and 10).
 *
 * Section 10's third "looks coolest" item is "a short dependency path that lights up from part to
 * constraint". This renders exactly that: a radial layout of the selected part's neighbourhood,
 * with relation type and certainty visible on every edge.
 *
 * It asks the API for a neighbourhood, never for the whole graph. That is not a performance
 * decision - section 7 says useful queries are narrow, and a panel that fetched everything would
 * quietly become the thing that gets handed to a model later.
 *
 * Drawn as inline SVG rather than a graph library: the layout is a single ring, the whole
 * behaviour is sixty lines, and it has no dependency to pin at bootstrap.
 */

import { useEffect, useMemo, useState } from "react";

import { useWorkbench } from "@/app/WorkbenchContext";
import { api } from "@/lib/api";
import type { GraphNode, Neighborhood } from "@/lib/contracts.gen";

const RADIUS_OPTIONS = [1, 2, 3] as const;

/** Colour by what the node *is*, and label it too - colour alone is not an accessible signal. */
const NODE_CLASS: Record<string, string> = {
  PartOccurrence: "n-part",
  PartDefinition: "n-def",
  Constraint: "n-constraint",
  Regulation: "n-reg",
  Evidence: "n-evidence",
  CatalogItem: "n-catalog",
  Supplier: "n-supplier",
  Interface: "n-interface",
  Material: "n-material",
  Function: "n-function",
  Mission: "n-mission",
  AnalysisRun: "n-run",
};

export function GraphPanel() {
  const { revisionId, selectedPartId, selectPart } = useWorkbench();
  const [radius, setRadius] = useState<number>(2);
  const [data, setData] = useState<Neighborhood | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setNote(null);
    if (!revisionId || !selectedPartId) return;
    void api
      .neighborhood(revisionId, selectedPartId, radius)
      .then(setData)
      .catch(() => setNote("no neighbourhood for this part in this revision"));
  }, [revisionId, selectedPartId, radius]);

  const layout = useMemo(() => (data ? place(data) : null), [data]);

  if (!selectedPartId) {
    return (
      <div className="graphpanel">
        <h2>Dependencies</h2>
        <p className="muted">Select a part to see what it touches.</p>
      </div>
    );
  }

  return (
    <div className="graphpanel">
      <header>
        <h2>Dependencies</h2>
        <div className="radius">
          {RADIUS_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={option === radius ? "chip active" : "chip"}
              onClick={() => setRadius(option)}
            >
              {option} hop{option === 1 ? "" : "s"}
            </button>
          ))}
        </div>
      </header>

      {note ? <p className="muted">{note}</p> : null}
      {!data || !layout ? <p className="muted">Loading…</p> : null}

      {data && layout ? (
        <>
          <svg viewBox="0 0 320 320" className="graph" role="img" aria-label="Dependency graph">
            {data.edges.map((edge) => {
              const from = layout.get(edge.source_id);
              const to = layout.get(edge.target_id);
              if (!from || !to) return null;
              return (
                <g key={edge.edge_id} className={`edge r-${edge.relation} status-${edge.status}`}>
                  <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
                  <title>
                    {`${edge.relation} (${edge.status})`}
                    {edge.properties?.basis ? ` — ${String(edge.properties.basis)}` : ""}
                  </title>
                </g>
              );
            })}
            {data.nodes.map((node) => {
              const point = layout.get(node.node_id);
              if (!point) return null;
              const isCentre = node.node_id === data.center_id;
              return (
                <g
                  key={node.node_id}
                  className={`node ${NODE_CLASS[node.node_type] ?? "n-other"} ${
                    isCentre ? "centre" : ""
                  } status-${node.status}`}
                  onClick={() => {
                    if (node.node_type === "PartOccurrence") {
                      selectPart(node.node_id.replace("n:part:", ""));
                    }
                  }}
                >
                  <circle cx={point.x} cy={point.y} r={isCentre ? 9 : 5} />
                  <title>{`${node.node_type}: ${node.label} (${node.status})`}</title>
                </g>
              );
            })}
          </svg>

          <ul className="legend">
            {[...new Set(data.nodes.map((node) => node.node_type))].sort().map((type) => (
              <li key={type}>
                <span className={`swatch ${NODE_CLASS[type] ?? "n-other"}`} />
                {type}
              </li>
            ))}
          </ul>

          <p className="muted">
            {data.nodes.length} nodes within {data.radius} hop{data.radius === 1 ? "" : "s"}
            {data.truncated ? ` · truncated at the ${data.node_budget}-node budget` : ""}
          </p>

          <RelationSummary data={data} />
        </>
      ) : null}
    </div>
  );
}

function RelationSummary({ data }: { data: Neighborhood }) {
  const counts = new Map<string, number>();
  for (const edge of data.edges) {
    counts.set(edge.relation, (counts.get(edge.relation) ?? 0) + 1);
  }
  const inferred = data.edges.filter((edge) => edge.relation === "near").length;

  return (
    <div className="relations">
      <ul>
        {[...counts.entries()].sort().map(([relation, count]) => (
          <li key={relation}>
            <code>{relation}</code> × {count}
          </li>
        ))}
      </ul>
      {inferred > 0 ? (
        <p className="muted">
          {inferred} <code>near</code> edge{inferred === 1 ? "" : "s"} are geometric proximity only.
          They do not imply a joint or any load transfer.
        </p>
      ) : null}
    </div>
  );
}

/** A ring per hop distance from the centre. Deterministic, so the picture does not jump. */
function place(data: Neighborhood): Map<string, { x: number; y: number }> {
  const depth = bfsDepth(data);
  const byDepth = new Map<number, GraphNode[]>();
  for (const node of data.nodes) {
    const level = depth.get(node.node_id) ?? data.radius;
    const bucket = byDepth.get(level) ?? [];
    bucket.push(node);
    byDepth.set(level, bucket);
  }

  const points = new Map<string, { x: number; y: number }>();
  const centre = { x: 160, y: 160 };
  for (const [level, nodes] of byDepth) {
    if (level === 0) {
      for (const node of nodes) points.set(node.node_id, centre);
      continue;
    }
    const ringRadius = 45 * level + 20;
    const sorted = [...nodes].sort((a, b) => a.node_id.localeCompare(b.node_id));
    sorted.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / sorted.length - Math.PI / 2;
      points.set(node.node_id, {
        x: centre.x + ringRadius * Math.cos(angle),
        y: centre.y + ringRadius * Math.sin(angle),
      });
    });
  }
  return points;
}

function bfsDepth(data: Neighborhood): Map<string, number> {
  const adjacency = new Map<string, string[]>();
  for (const edge of data.edges) {
    adjacency.set(edge.source_id, [...(adjacency.get(edge.source_id) ?? []), edge.target_id]);
    adjacency.set(edge.target_id, [...(adjacency.get(edge.target_id) ?? []), edge.source_id]);
  }
  const depth = new Map<string, number>([[data.center_id, 0]]);
  const queue = [data.center_id];
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of adjacency.get(current) ?? []) {
      if (!depth.has(next)) {
        depth.set(next, (depth.get(current) ?? 0) + 1);
        queue.push(next);
      }
    }
  }
  return depth;
}
