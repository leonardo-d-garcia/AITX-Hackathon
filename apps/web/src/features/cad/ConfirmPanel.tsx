/**
 * ConfirmPanel — the human gate between "we read some STLs" and "we may publish a metric".
 *
 * Until a person confirms units, axes, the nose datum, the mirror plane and one variant per
 * group, `packages/ingest` returns UNITS_UNCONFIRMED / ASSEMBLY_UNCONFIRMED and nothing
 * downstream may quote a number. This panel presents the proposal from `propose_frame` /
 * `detect_variants` and emits the `ConfirmPayload` that `confirm(...)` takes.
 *
 * Nothing is pre-selected on the user's behalf: a variant group with no selection blocks submit.
 */
import { useMemo, useState } from 'react';

import type { ConfirmPayload, DesignManifest, FrameConfirmation, VariantGroup } from './types';

export interface ConfirmPanelProps {
  manifest: DesignManifest;
  /** Unconfirmed proposal from `propose_frame`; defaults to `manifest.frame`. */
  proposal?: FrameConfirmation;
  variants?: VariantGroup[];
  /** Who is confirming — recorded in the revision, so it must be a real identity. */
  confirmedBy: string;
  /** Preview the mirrored assembly in the viewport before committing. */
  onPreviewMirror?: (enabled: boolean) => void;
  /** Preview one variant option in the viewport. */
  onPreviewVariant?: (groupId: string, sourcePath: string) => void;
  onSubmit: (payload: ConfirmPayload) => void;
  busy?: boolean;
}

/** The three axis conventions A1 can propose, as 3x3 proper rotations (det +1). */
const AXIS_PRESETS: Array<{ id: string; label: string; matrix: number[][]; note: string }> = [
  {
    id: 'native_y_nose_forward',
    label: 'Native −Y is forward, native −X is right, native −Z is down',
    matrix: [[0, -1, 0], [-1, 0, 0], [0, 0, -1]],
    note: 'The candidate in tasks/a.md: x = −(Y − Y_nose), y = −X, z = −Z.',
  },
  {
    id: 'native_x_forward',
    label: 'Native +X is forward, +Y is right, −Z is down',
    matrix: [[1, 0, 0], [0, 1, 0], [0, 0, -1]],
    note: 'Use when the exporter already wrote a nose-forward X axis.',
  },
  {
    id: 'identity',
    label: 'Native axes already FRD',
    matrix: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    note: 'Only if the source is known to be FRD; verify the nose in the viewport first.',
  },
];

function det3(m: number[][]): number {
  return (
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  );
}

export function ConfirmPanel({
  manifest, proposal, variants, confirmedBy,
  onPreviewMirror, onPreviewVariant, onSubmit, busy = false,
}: ConfirmPanelProps) {
  const frame = proposal ?? manifest.frame;
  const groups = variants ?? manifest.variants;

  const [units, setUnits] = useState<'mm' | 'm' | 'in'>(frame.units);
  const [axisId, setAxisId] = useState<string>(
    AXIS_PRESETS.find((p) => JSON.stringify(p.matrix) === JSON.stringify(frame.native_to_frd))?.id
      ?? AXIS_PRESETS[0].id,
  );
  const [mirror, setMirror] = useState<boolean>(Boolean(frame.mirror_plane_native));
  const [massModel, setMassModel] = useState<'none' | 'shell_estimate'>(manifest.mass_model ?? 'none');
  const [selection, setSelection] = useState<Record<string, string>>(() => {
    // pre-fill only what a human already chose in a previous revision
    const seeded: Record<string, string> = {};
    for (const g of groups) if (g.selected) seeded[g.group_id] = g.selected;
    return seeded;
  });
  const [note, setNote] = useState('');

  const axis = AXIS_PRESETS.find((p) => p.id === axisId)!;
  const unanswered = groups.filter((g) => !selection[g.group_id]);
  const properRotation = Math.abs(det3(axis.matrix) - 1) < 1e-9;
  const canSubmit = !busy && unanswered.length === 0 && properRotation && confirmedBy.trim().length > 0;

  const payload: ConfirmPayload = useMemo(() => ({
    design_id: manifest.design_id,
    revision_id: manifest.revision_id,
    units,
    native_to_frd: axis.matrix,
    nose_datum_native: frame.nose_datum_native,
    mirror_plane_native: mirror ? (frame.mirror_plane_native ?? 'x=0') : null,
    variant_selection: selection,
    mass_model: massModel,
    confirmed_by: confirmedBy,
    notes: note.trim() ? [note.trim()] : [],
  }), [manifest, units, axis, frame, mirror, selection, massModel, confirmedBy, note]);

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (canSubmit) onSubmit(payload); }}
      style={{ display: 'grid', gap: 16 }}
    >
      <header>
        <h2 style={{ margin: 0, fontSize: 16 }}>Confirm the frame before any metric is published</h2>
        <p style={{ margin: '4px 0 0', fontSize: 13, opacity: 0.8 }}>
          {frame.confirmed
            ? `Already confirmed by ${frame.confirmed_by ?? 'someone'}; re-confirming writes a new revision.`
            : 'Until this is confirmed, every derived number is a hypothesis and the API returns UNITS_UNCONFIRMED.'}
        </p>
      </header>

      <fieldset>
        <legend>Units of the source files</legend>
        {(['mm', 'm', 'in'] as const).map((u) => (
          <label key={u} style={{ marginRight: 12 }}>
            <input type="radio" name="units" value={u} checked={units === u}
                   onChange={() => setUnits(u)} />{' '}
            {u}
          </label>
        ))}
        <p style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 0' }}>
          Proposed: {frame.units} (scale {frame.scale_to_m} to metres). Filenames and folders are
          evidence, not instructions.
        </p>
      </fieldset>

      <fieldset>
        <legend>Axis convention (native → FRD)</legend>
        {AXIS_PRESETS.map((p) => (
          <label key={p.id} style={{ display: 'block', marginBottom: 4 }}>
            <input type="radio" name="axis" value={p.id} checked={axisId === p.id}
                   onChange={() => setAxisId(p.id)} />{' '}
            {p.label}
            <div style={{ fontSize: 12, opacity: 0.7, marginLeft: 22 }}>{p.note}</div>
          </label>
        ))}
        <p style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 0' }}>
          Nose datum (native): [{frame.nose_datum_native.join(', ')}]
          {properRotation ? '' : ' · this matrix is not a proper rotation and cannot be confirmed'}
        </p>
      </fieldset>

      <fieldset>
        <legend>Mirror plane</legend>
        <label>
          <input type="checkbox" checked={mirror}
                 onChange={(e) => { setMirror(e.target.checked); onPreviewMirror?.(e.target.checked); }} />{' '}
          Mirror one-sided parts about {frame.mirror_plane_native ?? 'x=0'} to build the other side
        </label>
        <p style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 0' }}>
          Each mirrored instance gets its own part_id and <code>mirror_of</code>, a mirrored
          definition with repaired winding, and a rigid placement — never a reflecting transform.
          Preview it in the viewport before confirming.
        </p>
      </fieldset>

      <fieldset>
        <legend>Variants — pick exactly one per group, never load two</legend>
        {groups.length === 0 && <p style={{ fontSize: 13, opacity: 0.7 }}>No variant groups detected.</p>}
        {groups.map((g) => (
          <div key={g.group_id} style={{ marginBottom: 10 }}>
            <strong style={{ fontSize: 13 }}>{g.group_id}</strong>
            {g.options.map((opt) => (
              <label key={opt} style={{ display: 'block', marginLeft: 12 }}>
                <input
                  type="radio"
                  name={`variant-${g.group_id}`}
                  value={opt}
                  checked={selection[g.group_id] === opt}
                  onChange={() => {
                    setSelection((s) => ({ ...s, [g.group_id]: opt }));
                    onPreviewVariant?.(g.group_id, opt);
                  }}
                />{' '}
                {opt}
              </label>
            ))}
            {!selection[g.group_id] && (
              <div style={{ fontSize: 12, marginLeft: 12, opacity: 0.85 }}>
                unanswered — the unselected options go to <code>excluded_sources</code>, and their
                mass is never counted.
              </div>
            )}
          </div>
        ))}
      </fieldset>

      <fieldset>
        <legend>Printed-part mass model</legend>
        <label style={{ display: 'block' }}>
          <input type="radio" name="mass" checked={massModel === 'none'}
                 onChange={() => setMassModel('none')} />{' '}
          none — printed-part mass stays <strong>unknown</strong> (default)
        </label>
        <label style={{ display: 'block' }}>
          <input type="radio" name="mass" checked={massModel === 'shell_estimate'}
                 onChange={() => setMassModel('shell_estimate')} />{' '}
          shell_estimate — estimated mass with the wall thickness and density assumptions listed
        </label>
        <p style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 0' }}>
          Several meshes are not watertight, so volume-based mass is invalid for them — and volume
          is not evidence of mass in any case.
        </p>
      </fieldset>

      <label>
        Note for the revision record (optional)
        <input value={note} onChange={(e) => setNote(e.target.value)} style={{ width: '100%' }} />
      </label>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button type="submit" disabled={!canSubmit}>
          {busy ? 'Confirming…' : `Confirm as ${confirmedBy || '…'}`}
        </button>
        {unanswered.length > 0 && (
          <span style={{ fontSize: 12 }}>
            Waiting on: {unanswered.map((g) => g.group_id).join(', ')}
          </span>
        )}
      </div>
    </form>
  );
}

export default ConfirmPanel;
