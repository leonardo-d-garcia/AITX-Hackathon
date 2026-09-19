/**
 * The workbench shell (architecture section 10).
 *
 * "Build one workbench with three modes: Inspect, Improve, Simulate. Persistent top bar:
 * design/revision, reference-versus-reconstruction label, model fidelity, mission, and STEP export
 * status."
 *
 * The top bar is not decoration. Every claim the product makes is scoped to a revision and a
 * fidelity tier, so both are on screen at all times - a judge should never have to ask which
 * revision a number belongs to.
 */

import { useEffect } from "react";

import { GraphPanel } from "@/features/graph/GraphPanel";
import { EvidenceInspector } from "@/features/graph/EvidenceInspector";
import { PartTree } from "@/features/graph/PartTree";
import { ReviewPanel } from "@/features/review/ReviewPanel";
import { HistoryPanel } from "@/features/review/HistoryPanel";
import { CadViewportMount } from "@/features/cad/CadViewportMount";
import { SimulationMount } from "@/features/simulation/SimulationMount";

import { useWorkbench, type Mode } from "./WorkbenchContext";
import { TopBar } from "./TopBar";
import { EventLog } from "./EventLog";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "inspect", label: "Inspect", hint: "select a part, read its evidence, trace what it feeds" },
  { id: "improve", label: "Improve", hint: "review bounded proposals, accept or decline" },
  { id: "simulate", label: "Simulate", hint: "replay the mission for an exact revision" },
];

export function App() {
  const workbench = useWorkbench();
  const { designId, mode, setMode, error, clearError, busy } = workbench;

  // Keyboard mode switching: this is a desktop presentation tool, driven live.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      const index = ["1", "2", "3"].indexOf(event.key);
      if (index >= 0) setMode(MODES[index]!.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setMode]);

  return (
    <div className="shell">
      <TopBar />

      <nav className="modes" aria-label="Workbench mode">
        {MODES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={entry.id === mode ? "mode active" : "mode"}
            onClick={() => setMode(entry.id)}
            title={entry.hint}
            aria-pressed={entry.id === mode}
          >
            {entry.label}
          </button>
        ))}
        {busy ? (
          <span className="busy" role="status">
            {busy}…
          </span>
        ) : null}
      </nav>

      {error ? (
        <div
          className={error.isDesignResult ? "banner result" : "banner error"}
          role={error.isDesignResult ? "status" : "alert"}
        >
          <strong>{error.envelope.code}</strong>
          <span>{error.envelope.message}</span>
          {error.isDesignResult ? (
            <em>
              This is a result of the model, not a failure of the tool.
            </em>
          ) : null}
          <button type="button" onClick={clearError}>
            Dismiss
          </button>
        </div>
      ) : null}

      {!designId ? <EmptyState /> : null}

      {designId && mode === "inspect" ? (
        <main className="layout inspect">
          <aside className="pane left">
            <PartTree />
          </aside>
          <section className="pane centre">
            <CadViewportMount />
          </section>
          <aside className="pane right">
            <EvidenceInspector />
            <GraphPanel />
          </aside>
        </main>
      ) : null}

      {designId && mode === "improve" ? (
        <main className="layout improve">
          <section className="pane wide">
            <ReviewPanel />
          </section>
          <aside className="pane right">
            <HistoryPanel />
            <GraphPanel />
          </aside>
        </main>
      ) : null}

      {designId && mode === "simulate" ? (
        <main className="layout simulate">
          <section className="pane wide">
            <SimulationMount />
          </section>
          <aside className="pane right">
            <HistoryPanel />
          </aside>
        </main>
      ) : null}

      <EventLog />
    </div>
  );
}

function EmptyState() {
  const { importFixture, doctor } = useWorkbench();
  return (
    <main className="empty">
      <h1>DroneBench Studio</h1>
      <p>
        Import a design to begin. The checked-in fixture is{" "}
        <strong>parametric_fixedwing</strong>, a synthetic demonstrator authored for this
        workbench. It is not the Titan Avenger and is not a reconstruction of any real aircraft.
      </p>
      <button type="button" className="primary" onClick={() => void importFixture()}>
        Import the synthetic fixture
      </button>
      {doctor?.capabilities_absent?.length ? (
        <section className="absent">
          <h2>Not available on this machine</h2>
          <ul>
            {doctor.capabilities_absent.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <p className="muted">
            The workbench states what it cannot do rather than producing an unverified result.
          </p>
        </section>
      ) : null}
    </main>
  );
}
