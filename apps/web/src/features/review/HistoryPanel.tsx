/**
 * The revision timeline (architecture section 10, Improve).
 *
 * "After commit, highlight changed parts and advance the revision timeline."
 *
 * This lists only the states the design was actually in. Previews are absent because they were
 * never active, and so is any commit whose compare-and-swap lost the race - showing either would
 * imply an edit that never took effect.
 */

import { useWorkbench } from "@/app/WorkbenchContext";

const CAUSE_LABEL: Record<string, string> = {
  import: "imported",
  confirm: "confirmed units, frame, and evidence",
  manual_edit: "manual edit",
  proposal_preview: "preview",
  proposal_commit: "accepted proposal",
  undo: "returned to an earlier state",
};

export function HistoryPanel() {
  const { history, revisionId, undo, busy } = useWorkbench();

  return (
    <div className="history">
      <header>
        <h2>History</h2>
        <button
          type="button"
          onClick={() => void undo()}
          disabled={history.length < 2 || Boolean(busy)}
          title="Switch back to the previous state this design was in"
        >
          Undo
        </button>
      </header>

      {!history.length ? <p className="muted">No revisions yet.</p> : null}

      <ol className="timeline">
        {history.map((revision) => (
          <li
            key={revision.revision_id}
            className={revision.revision_id === revisionId ? "entry active" : "entry"}
          >
            <span className="dot" aria-hidden="true" />
            <div>
              <div className="entry-title">
                {revision.label || CAUSE_LABEL[revision.created_cause] || revision.created_cause}
              </div>
              <div className="muted">
                <code>{revision.revision_id.slice(0, 12)}</code> · {revision.stage} ·{" "}
                {CAUSE_LABEL[revision.created_cause] ?? revision.created_cause}
              </div>
            </div>
            {revision.revision_id === revisionId ? <span className="chip">active</span> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
