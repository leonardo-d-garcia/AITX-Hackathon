/**
 * The audit strip (architecture section 7).
 *
 * "Every mutation emits an auditable event, but events never expose chain-of-thought. They show
 * tool name, inputs summary, artifact references, status and elapsed time."
 *
 * There is nothing to render here but those fields, because the event model carries nothing else.
 */

import { useState } from "react";

import { useWorkbench } from "./WorkbenchContext";

export function AuditRail() {
  const { events } = useWorkbench();
  const [open, setOpen] = useState(false);

  const latest = events[events.length - 1];

  return (
    <footer className={open ? "audit is-open" : "audit"}>
      <button type="button" className="audit-toggle" onClick={() => setOpen(!open)}>
        Audit log
        <span className="muted">
          {latest ? ` · #${latest.sequence} ${latest.kind}` : " · nothing yet"}
        </span>
      </button>

      {open ? (
        <ol className="events">
          {[...events].reverse().map((event) => (
            <li key={event.event_id} className={event.status === "error" ? "row error" : "row"}>
              <span className="seq">#{event.sequence}</span>
              <span className="kind">{event.kind}</span>
              <span className="tool">{event.tool_name}</span>
              <span className="summary">
                {Object.entries(event.inputs_summary ?? {})
                  .map(([key, value]) => `${key}=${value}`)
                  .join("  ")}
              </span>
              {event.artifact_ids?.length ? (
                <span className="muted">{event.artifact_ids.length} artifact(s)</span>
              ) : null}
              {event.error_code ? <span className="err">{event.error_code}</span> : null}
              <span className="muted">{(event.elapsed_s ?? 0).toFixed(2)}s</span>
            </li>
          ))}
        </ol>
      ) : null}
    </footer>
  );
}
