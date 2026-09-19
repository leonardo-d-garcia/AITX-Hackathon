/**
 * PartInspector — the right-hand evidence panel for one selected part.
 *
 * Every engineering number is shown as a claim: value, unit, status chip, source kind, evidence
 * and assumptions. Unknown reads "unknown — needs evidence" and offers a provenance-carrying
 * way to supply the value (architecture §10: "unknown mass is actionable"). Colour is never the
 * only signal; the status chip always carries text.
 */
import { useMemo, useState } from 'react';

import {
  type Claim,
  type DesignManifest,
  type Evidence,
  type FitReport,
  type PartOccurrence,
  type SourceKind,
  type Status,
  STATUS_COLOR,
  formatClaim,
  isUnknown,
  partStatus,
} from './types';

export interface ClaimEdit {
  part_id: string;
  field: 'mass_kg' | 'material' | 'function' | 'local_com_m';
  value: string;
  unit?: string | null;
  source_kind: SourceKind;
  note: string;
}

export interface PartInspectorProps {
  manifest: DesignManifest;
  partId: string | null;
  /** Measured axis-aligned bounds of the rendered geometry, from CadViewport.onMeasure. */
  measured?: { length_x_m: number; width_y_m: number; height_z_m: number } | null;
  fitReport?: FitReport | null;
  /** Called when the user supplies a value for an unknown claim. Omit to hide the form. */
  onProvideClaim?: (edit: ClaimEdit) => void;
  /** Called when the user starts an edit this part declares it supports. */
  onStartEdit?: (partId: string, capability: string) => void;
}

export function StatusChip({ status }: { status: Status }) {
  return (
    <span
      role="status"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, borderRadius: 999,
        padding: '1px 9px', fontSize: 11.5, fontWeight: 650,
        color: STATUS_COLOR[status], border: `1px solid ${STATUS_COLOR[status]}`,
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'currentColor' }} />
      {status}
    </span>
  );
}

function ClaimBlock({
  label, claim, evidence, onProvide,
}: {
  label: string;
  claim: Claim<unknown>;
  evidence: Map<string, Evidence>;
  onProvide?: () => void;
}) {
  const unknown = isUnknown(claim);
  return (
    <section
      aria-label={`${label}: ${claim.status}`}
      style={{ border: '1px solid var(--line, #d3d7de)', borderRadius: 9, padding: '8px 10px', marginBottom: 8 }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13 }}>{label}</strong>
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: unknown ? 650 : 400 }}>
          {formatClaim(claim)}
        </span>
        <StatusChip status={claim.status} />
      </div>
      <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
        source: {claim.source_kind ?? 'no source kind'}
        {typeof claim.confidence === 'number' ? ` · confidence ${claim.confidence}` : ''}
      </div>
      <div style={{ fontSize: 12, opacity: 0.75 }}>
        evidence:{' '}
        {claim.evidence_ids.length
          ? claim.evidence_ids.map((id) => {
              const e = evidence.get(id);
              return e ? `${e.evidence_id} (${e.method}${e.uri ? ` · ${e.uri}` : ''})` : id;
            }).join('; ')
          : <em>none recorded</em>}
      </div>
      {claim.assumptions.length > 0 && (
        <ul style={{ margin: '4px 0 0 16px', padding: 0, fontSize: 12, opacity: 0.8 }}>
          {claim.assumptions.map((a) => <li key={a}>assumes {a}</li>)}
        </ul>
      )}
      {unknown && onProvide && (
        <button type="button" onClick={onProvide} style={{ marginTop: 6, fontSize: 12 }}>
          Provide a value with provenance
        </button>
      )}
    </section>
  );
}

function ProvideForm({
  part, field, unit, onSubmit, onCancel,
}: {
  part: PartOccurrence;
  field: ClaimEdit['field'];
  unit?: string | null;
  onSubmit: (edit: ClaimEdit) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState('');
  const [sourceKind, setSourceKind] = useState<SourceKind>('manual');
  const [note, setNote] = useState('');
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!value.trim() || !note.trim()) return;      // provenance is mandatory
        onSubmit({ part_id: part.part_id, field, value: value.trim(), unit, source_kind: sourceKind, note: note.trim() });
      }}
      style={{ display: 'grid', gap: 6, marginBottom: 10 }}
    >
      <label>
        Value{unit ? ` (${unit})` : ''}
        <input value={value} onChange={(e) => setValue(e.target.value)} required />
      </label>
      <label>
        Source
        <select value={sourceKind} onChange={(e) => setSourceKind(e.target.value as SourceKind)}>
          {(['manual', 'bom', 'catalog', 'user', 'computed'] as SourceKind[]).map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
      </label>
      <label>
        Where this came from (required)
        <input value={note} onChange={(e) => setNote(e.target.value)} required
               placeholder="e.g. weighed on a kitchen scale, 2026-09-19" />
      </label>
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="submit">Record claim</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export function PartInspector({
  manifest, partId, measured, fitReport, onProvideClaim, onStartEdit,
}: PartInspectorProps) {
  const [providing, setProviding] = useState<ClaimEdit['field'] | null>(null);
  const evidence = useMemo(
    () => new Map(manifest.evidence.map((e) => [e.evidence_id, e] as const)),
    [manifest],
  );
  const part = useMemo(
    () => manifest.parts.find((p) => p.part_id === partId) ?? null,
    [manifest, partId],
  );
  const fit = useMemo(
    () => fitReport?.per_part.find((r) => r.part_id === partId) ?? null,
    [fitReport, partId],
  );

  if (!part) {
    return <p style={{ opacity: 0.7, fontStyle: 'italic' }}>Select a part to inspect its claims.</p>;
  }

  const claims: Array<[string, ClaimEdit['field'], Claim<unknown>]> = [
    ['Mass', 'mass_kg', part.mass_kg],
    ['Local CoM', 'local_com_m', part.local_com_m],
    ['Material', 'material', part.material],
    ['Function', 'function', part.function],
  ];

  return (
    <div>
      <h2 style={{ fontSize: 17, margin: '0 0 6px' }}>{part.name}</h2>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
        <StatusChip status={partStatus(part)} />
        <span>{part.category}</span>
        {part.locked && <span>locked</span>}
      </div>

      <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px', margin: 0, fontSize: 13 }}>
        <dt>part_id</dt><dd style={{ margin: 0 }}>{part.part_id}</dd>
        <dt>definition</dt><dd style={{ margin: 0 }}>{part.definition_id}</dd>
        <dt>side</dt><dd style={{ margin: 0 }}>{part.side ?? 'unspecified'}</dd>
        <dt>mirror_of</dt>
        <dd style={{ margin: 0 }}>{part.mirror_of ? `${part.mirror_of} (mirrored instance)` : '—'}</dd>
        <dt>representation</dt>
        <dd style={{ margin: 0 }}>
          {part.representation === 'reference_mesh'
            ? 'reference_mesh — original geometry, no topology edits'
            : part.representation}
        </dd>
        <dt>source file</dt>
        <dd style={{ margin: 0 }}>{part.source ?? <em>none (not from the archive)</em>}</dd>
      </dl>

      {measured && (
        <>
          <h3 style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px', marginTop: 16 }}>
            Measured bounding box
          </h3>
          <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px', margin: 0, fontSize: 13 }}>
            <dt>length (x fwd)</dt><dd style={{ margin: 0 }}>{measured.length_x_m.toFixed(4)} m</dd>
            <dt>width (y right)</dt><dd style={{ margin: 0 }}>{measured.width_y_m.toFixed(4)} m</dd>
            <dt>height (z)</dt><dd style={{ margin: 0 }}>{measured.height_z_m.toFixed(4)} m</dd>
          </dl>
          <p style={{ fontSize: 12, opacity: 0.7 }}>
            Axis-aligned extent of the rendered mesh, not a design dimension.
          </p>
        </>
      )}

      {fit && (
        <>
          <h3 style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px', marginTop: 16 }}>
            Reconstruction fit
          </h3>
          <p style={{ fontSize: 13, margin: 0 }}>
            RMS {fit.rms_m ?? '—'} m · max {fit.max_m ?? '—'} m{fit.note ? ` · ${fit.note}` : ''}
          </p>
        </>
      )}

      <h3 style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px', marginTop: 16 }}>
        Claims
      </h3>
      {claims.map(([label, field, claim]) => (
        <div key={field}>
          <ClaimBlock
            label={label}
            claim={claim}
            evidence={evidence}
            onProvide={onProvideClaim ? () => setProviding(field) : undefined}
          />
          {providing === field && onProvideClaim && (
            <ProvideForm
              part={part}
              field={field}
              unit={claim.unit}
              onSubmit={(edit) => { onProvideClaim(edit); setProviding(null); }}
              onCancel={() => setProviding(null)}
            />
          )}
        </div>
      ))}

      <h3 style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px', marginTop: 16 }}>
        Edit capabilities
      </h3>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {part.edit_capabilities.length === 0 || part.edit_capabilities[0] === 'none' ? (
          <span style={{ fontSize: 12, opacity: 0.7 }}>
            none — reference mesh, no topology edits
          </span>
        ) : (
          part.edit_capabilities.map((c) => (
            <button key={c} type="button" disabled={!onStartEdit || part.locked}
                    onClick={() => onStartEdit?.(part.part_id, c)}>
              {c}
            </button>
          ))
        )}
      </div>

      {part.allowed_overlap_with.length > 0 && (
        <p style={{ fontSize: 12, opacity: 0.75, marginTop: 12 }}>
          Declared overlaps: {part.allowed_overlap_with.join(', ')}
        </p>
      )}
    </div>
  );
}

export default PartInspector;
