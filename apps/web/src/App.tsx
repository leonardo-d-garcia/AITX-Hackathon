import { useEffect, useMemo, useRef, useState } from "react";
import { HeatmapLegend } from "./features/simulation/HeatmapLegend";
import { PartCard } from "./features/simulation/PartCard";
import { ReplayViewport } from "./features/simulation/ReplayViewport";
import {
  fidelityLabel,
  interpolateFrame,
  type SimulationRun,
} from "./telemetry";

async function loadRun(): Promise<SimulationRun> {
  const mod = await import("@telemetry");
  return (mod as { default?: SimulationRun } & SimulationRun).default ??
    (mod as unknown as SimulationRun);
}

export function App() {
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [t, setT] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const last = useRef<number | null>(null);

  useEffect(() => {
    loadRun()
      .then((r) => {
        setRun(r);
        setT(r.frames[0]?.t ?? 0);
      })
      .catch((e: unknown) => {
        setError(
          e instanceof Error
            ? e.message
            : "simulation_run.json not available yet (U0)",
        );
      });
  }, []);

  const tMax = run?.frames.at(-1)?.t ?? 0;

  useEffect(() => {
    if (!playing || !run) return;
    let id = 0;
    const loop = (now: number) => {
      if (last.current == null) last.current = now;
      const dt = ((now - last.current) / 1000) * rate;
      last.current = now;
      setT((prev) => {
        const next = prev + dt;
        if (next >= tMax) {
          setPlaying(false);
          return tMax;
        }
        return next;
      });
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(id);
      last.current = null;
    };
  }, [playing, rate, run, tMax]);

  const frame = useMemo(
    () => (run && run.frames.length ? interpolateFrame(run.frames, t) : null),
    [run, t],
  );

  const tier = run?.meta.fidelity_tier ?? "analytic";
  const assumptions = (run?.meta.assumptions ?? []).slice(0, 3);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr auto",
        height: "100%",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          padding: "14px 18px",
          borderBottom: "1px solid var(--line)",
          background: "var(--panel)",
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "Archivo Narrow, sans-serif",
              fontSize: 22,
              letterSpacing: 0.4,
            }}
          >
            DroneBench mission replay
          </div>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>
            R3F shipping viewport · Unreal is not the plant · print archive has
            no mass
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: "var(--phosphor)", fontSize: 13 }}>
            {fidelityLabel(tier)}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 11 }}>
            {run?.meta.revision_id ?? "no run"}
          </div>
        </div>
      </header>

      <div style={{ minHeight: 0, position: "relative" }}>
        {error ? (
          <div style={{ padding: 24, color: "var(--caution)" }}>
            Waiting on U0 fallback: {error}
          </div>
        ) : (
          <ReplayViewport
            frame={frame}
            onPartPick={(id) => setPicked(id)}
          />
        )}
        {assumptions.length > 0 ? (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: 12,
              maxWidth: 420,
              color: "var(--muted)",
              fontSize: 11,
              lineHeight: 1.45,
              pointerEvents: "none",
            }}
          >
            {assumptions.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
        ) : null}
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            display: "grid",
            gap: 8,
            pointerEvents: "none",
          }}
        >
          <PartCard partId={picked} />
        </div>
        <div
          style={{
            position: "absolute",
            bottom: 12,
            left: 12,
            pointerEvents: "none",
          }}
        >
          <HeatmapLegend />
        </div>
      </div>

      <footer
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr auto",
          gap: 16,
          alignItems: "center",
          padding: "12px 18px",
          borderTop: "1px solid var(--line)",
          background: "var(--panel)",
        }}
      >
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={() => setPlaying((p) => !p)}>
            {playing ? "pause" : "play"}
          </button>
          {([0.5, 1, 2] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRate(r)}
              style={{
                outline: rate === r ? "1px solid var(--phosphor)" : undefined,
              }}
            >
              {r}×
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={tMax || 1}
          step={run?.meta.dt_s ?? 0.02}
          value={t}
          onChange={(e) => {
            setPlaying(false);
            setT(Number(e.target.value));
          }}
        />
        <div style={{ fontSize: 12, color: "var(--muted)", minWidth: 360 }}>
          t={t.toFixed(2)}s n={frame?.load_factor_n.toFixed(2) ?? "—"}{" "}
          Va={frame?.Va.toFixed(1) ?? "—"} m/s E=
          {frame?.energy_wh_remaining.toFixed(1) ?? "—"} Wh picked=
          {picked ?? "—"}
        </div>
      </footer>
    </div>
  );
}
