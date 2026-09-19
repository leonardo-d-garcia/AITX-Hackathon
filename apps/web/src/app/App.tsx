/**
 * The workbench shell.
 *
 * Viewport-dominant: the schematic is the page. The part list and the evidence panel are rails
 * that slide in when you need them and get out of the way when you do not, so the aircraft keeps
 * the screen.
 *
 * Architecture section 10 asks for three modes and a persistent scope line (revision, fidelity,
 * representation, export status). Those live in the status strip, which is the only permanent
 * chrome — everything else is summoned.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { EvidenceInspector } from "@/features/graph/EvidenceInspector";
import { GraphPanel } from "@/features/graph/GraphPanel";
import { PartTree } from "@/features/graph/PartTree";
import { HistoryPanel } from "@/features/review/HistoryPanel";
import { ReviewPanel } from "@/features/review/ReviewPanel";
import { GeometryFacts } from "@/app/mounts/GeometryFacts";
import { MissionRun } from "@/app/mounts/MissionRun";
import {
  Schematic,
  readPalette,
  toSchematicParts,
  type ScenePalette,
} from "@/viewport/Schematic";

import { ConfirmGate } from "./ConfirmGate";
import { StatusStrip } from "./StatusStrip";
import { AuditRail } from "./AuditRail";
import { useWorkbench, type Mode } from "./WorkbenchContext";

const MODES: { id: Mode; label: string; key: string }[] = [
  { id: "inspect", label: "Inspect", key: "1" },
  { id: "improve", label: "Improve", key: "2" },
  { id: "simulate", label: "Simulate", key: "3" },
];

export function App() {
  const workbench = useWorkbench();
  const { designId, mode, setMode, error, clearError, parts, selectedPartId, selectPart } =
    workbench;

  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  // Read from the document element, not a ref on the shell: the tokens live on :root, and before
  // a design is imported the shell is not mounted at all, so a ref would never resolve.
  const palette = useMemo<ScenePalette>(() => readPalette(document.documentElement), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      const mode = MODES.find((entry) => entry.key === event.key);
      if (mode) setMode(mode.id);
      if (event.key === "[") setLeftOpen((open) => !open);
      if (event.key === "]") setRightOpen((open) => !open);
      if (event.key === "Escape") selectPart(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setMode, selectPart]);

  const schematicParts = useMemo(
    () =>
      parts ? toSchematicParts(parts.parts.occurrences, parts.capabilities ?? {}) : [],
    [parts],
  );

  const handleSelect = useCallback((partId: string | null) => selectPart(partId), [selectPart]);

  if (!designId) return <Landing />;

  return (
    <div className="shell">
      <StatusStrip />

      <div className="stage">
        <aside
          className={leftOpen ? "rail left open" : "rail left"}
          aria-hidden={!leftOpen}
        >
          <div className="rail-body">
            {mode === "improve" ? <HistoryPanel /> : <PartTree />}
          </div>
        </aside>

        <main className="viewport">
          <Schematic
            parts={schematicParts}
            features={parts?.geometry_features ?? null}
            selectedPartId={selectedPartId}
            onSelect={handleSelect}
            palette={palette}
          />

          <div className="viewport-overlay">
            <nav className="modes" aria-label="Workbench mode">
              {MODES.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className={entry.id === mode ? "mode is-active" : "mode"}
                  onClick={() => setMode(entry.id)}
                  aria-pressed={entry.id === mode}
                >
                  {entry.label}
                </button>
              ))}
            </nav>

            <div className="rail-toggles">
              <button
                type="button"
                className="rail-toggle"
                onClick={() => setLeftOpen((open) => !open)}
                aria-expanded={leftOpen}
              >
                {leftOpen ? "Hide parts" : "Parts"}
              </button>
              <button
                type="button"
                className="rail-toggle"
                onClick={() => setRightOpen((open) => !open)}
                aria-expanded={rightOpen}
              >
                {rightOpen ? "Hide panel" : mode === "improve" ? "Proposals" : "Evidence"}
              </button>
            </div>
          </div>

          {error ? (
            <div
              className={error.isDesignResult ? "notice is-result" : "notice is-error"}
              role={error.isDesignResult ? "status" : "alert"}
            >
              <p className="notice-code">{error.envelope.code}</p>
              <p className="notice-message">{error.envelope.message}</p>
              {error.isDesignResult ? (
                <p className="notice-aside">
                  A result of the model, not a failure of the tool.
                </p>
              ) : null}
              <button type="button" onClick={clearError}>
                Dismiss
              </button>
            </div>
          ) : null}
        </main>

        <aside
          className={rightOpen ? "rail right open" : "rail right"}
          aria-hidden={!rightOpen}
        >
          <div className="rail-body">
            <ConfirmGate />
            {mode === "inspect" ? (
              <>
                <EvidenceInspector />
                <GraphPanel />
                <GeometryFacts />
              </>
            ) : null}
            {mode === "improve" ? <ReviewPanel /> : null}
            {mode === "simulate" ? <MissionRun /> : null}
          </div>
        </aside>
      </div>

      <AuditRail />
    </div>
  );
}

function Landing() {
  const { importFixture, doctor, busy } = useWorkbench();

  return (
    <main className="landing">
      <div className="landing-copy">
        <h1>
          Click a part, see why it matters, change it with evidence.
        </h1>
        <p className="landing-lede">
          DroneBench traces a design decision from the geometry that carries it, through the
          constraint it feeds, to the revision that changed it. Every number on screen names the
          revision it belongs to and the evidence behind it. Where the evidence runs out, it says
          so instead of guessing.
        </p>
        <button
          type="button"
          className="primary large"
          onClick={() => void importFixture()}
          disabled={Boolean(busy)}
        >
          {busy ? `${busy}…` : "Import a design"}
        </button>
        <p className="landing-note">
          Loads <strong>parametric_fixedwing</strong>, a synthetic demonstrator authored for this
          workbench. It is not the Titan Avenger and reconstructs no real aircraft.
        </p>
      </div>

      {doctor?.capabilities_absent?.length ? (
        <section className="landing-absent">
          <h2>Not installed on this machine</h2>
          <ul>
            {doctor.capabilities_absent.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <p>
            The workbench reports what it cannot do rather than producing a result it cannot
            stand behind.
          </p>
        </section>
      ) : null}
    </main>
  );
}
