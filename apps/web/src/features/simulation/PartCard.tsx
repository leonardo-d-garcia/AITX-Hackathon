export function PartCard({ partId }: { partId: string | null }) {
  if (partId === null) return null;

  return (
    <div
      style={{
        background: "var(--panel)",
        color: "var(--ink)",
        border: "1px solid var(--line)",
        padding: "10px 12px",
        fontSize: 12,
        minWidth: 180,
      }}
    >
      <div style={{ color: "var(--muted)", fontSize: 11 }}>part id</div>
      <div>{partId}</div>
      <div style={{ color: "var(--muted)", marginTop: 8 }}>mass unknown</div>
      <div style={{ color: "var(--muted)" }}>material unknown</div>
      <div style={{ color: "var(--muted)", marginTop: 8 }}>not from a BOM</div>
    </div>
  );
}
