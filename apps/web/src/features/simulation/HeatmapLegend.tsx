const VIRIDIS =
  "linear-gradient(to right, #440154, #482878, #3e4989, #31688e, #26828e, #1f9e89, #35b779, #6ece58, #b5de2b, #fde725)";

export function HeatmapLegend() {
  return (
    <div
      style={{
        background: "var(--panel)",
        color: "var(--ink)",
        border: "1px solid var(--line)",
        padding: "10px 12px",
        fontSize: 12,
        minWidth: 220,
      }}
    >
      <div>load factor n</div>
      <div
        style={{
          height: 10,
          marginTop: 8,
          borderRadius: 2,
          border: "1px solid var(--line)",
          background: VIRIDIS,
        }}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          marginTop: 4,
          color: "var(--muted)",
          fontSize: 11,
        }}
      >
        <span>1.0</span>
        <span>~1.15 (coordinated 30 deg turn)</span>
      </div>
      <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 8 }}>
        colour is n, not MPa. Stress unknown without spar inner diameter.
      </div>
    </div>
  );
}
