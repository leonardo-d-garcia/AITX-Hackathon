/**
 * EditPreview — the ghost diff for a proposed CAD edit.
 *
 * Shows the base revision solid and the preview revision as a translucent ghost, plus the change
 * ledger and the export acceptance checks. Acceptance is disabled while the preview is
 * incomplete, stale or blocked; declining is always available (architecture §10).
 */
import { useMemo } from 'react';

import { CadViewport } from './CadViewport';
import { StatusChip } from './PartInspector';
import type { CadEditResult, DesignManifest, ViewMode } from './types';

export interface EditPreviewProps {
  manifest: DesignManifest;
  /** GLB of the revision the edit was based on. */
  baseGlbUrl: string;
  /** GLB of the preview revision; null while A3 is still generating it. */
  previewGlbUrl?: string | null;
  result?: CadEditResult | null;
  /** Revision the app is currently on — a mismatch means the preview is stale. */
  currentRevisionId: string;
  onAccept?: (previewRevisionId: string) => void;
  onDecline?: () => void;
  busy?: boolean;
}

function valueText(v: unknown): string {
  if (v === null || v === undefined) return 'unknown';
  if (Array.isArray(v)) return `[${v.join(', ')}]`;
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function EditPreview({
  manifest, baseGlbUrl, previewGlbUrl, result, currentRevisionId,
  onAccept, onDecline, busy = false,
}: EditPreviewProps) {
  const stale = Boolean(result && result.base_revision_id !== currentRevisionId);
  const failedChecks = result?.checks.filter((c) => !c.passed) ?? [];
  const complete = Boolean(result && previewGlbUrl && result.status === 'ok' && result.preview_revision_id);
  const canAccept = Boolean(onAccept && complete && !stale && !busy && failedChecks.length === 0);

  // the ghost diff is the same overlay machinery: base solid, preview translucent
  const mode: ViewMode = previewGlbUrl ? 'overlay' : 'reference';
  const affected = useMemo(() => new Set(result?.affected_part_ids ?? []), [result]);

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'minmax(280px, 1fr) auto', gap: 12, height: '100%' }}>
      <CadViewport
        manifest={manifest}
        referenceUrl={baseGlbUrl}
        reconstructionUrl={previewGlbUrl ?? null}
        mode={mode}
        colourBy="status"
        selectedPartId={result?.affected_part_ids[0] ?? null}
      />

      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 14 }}>
            {result ? result.operation : 'No edit proposed'}
          </strong>
          {result && (
            <StatusChip
              status={result.status === 'ok' ? 'known' : result.status === 'blocked' ? 'unknown' : 'conflicted'}
            />
          )}
          <span style={{ fontSize: 12, opacity: 0.75 }}>
            base {result?.base_revision_id ?? '—'}
            {result?.preview_revision_id ? ` → preview ${result.preview_revision_id}` : ''}
          </span>
          {!previewGlbUrl && result && (
            <span style={{ fontSize: 12 }}>preview geometry is still building</span>
          )}
          {stale && (
            <span style={{ fontSize: 12 }}>
              STALE_REVISION — this preview was built on {result!.base_revision_id}, the app is on{' '}
              {currentRevisionId}. Re-run the edit.
            </span>
          )}
        </div>

        {result?.error && (
          <p style={{ fontSize: 13, marginTop: 8 }}>
            <strong>{result.error.code}</strong>: {result.error.message}
          </p>
        )}

        {result && result.changes.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginTop: 10 }}>
            <caption style={{ textAlign: 'left', fontSize: 11, textTransform: 'uppercase', opacity: 0.7 }}>
              Change ledger
            </caption>
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>Part</th>
                <th style={{ textAlign: 'left' }}>Field</th>
                <th style={{ textAlign: 'right' }}>Before</th>
                <th style={{ textAlign: 'right' }}>After</th>
              </tr>
            </thead>
            <tbody>
              {result.changes.map((c, i) => (
                <tr key={`${c.part_id}-${c.field}-${i}`}
                    style={{ fontWeight: affected.has(c.part_id) ? 650 : 400 }}>
                  <td>{c.part_id}</td>
                  <td>{c.field}</td>
                  <td style={{ textAlign: 'right' }}>{valueText(c.before)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {valueText(c.after)}{c.unit ? ` ${c.unit}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {result && result.checks.length > 0 && (
          <ul style={{ listStyle: 'none', padding: 0, margin: '10px 0 0', fontSize: 12 }}>
            {result.checks.map((c) => (
              <li key={c.name} style={{ marginBottom: 3 }}>
                <StatusChip status={c.passed ? 'known' : 'conflicted'} /> {c.name}
                {c.detail ? ` — ${c.detail}` : ''}
              </li>
            ))}
          </ul>
        )}

        <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
          <button type="button" disabled={!canAccept}
                  onClick={() => onAccept?.(result!.preview_revision_id!)}>
            {busy ? 'Committing…' : 'Accept and commit revision'}
          </button>
          <button type="button" onClick={() => onDecline?.()}>Decline</button>
          {!canAccept && result && (
            <span style={{ fontSize: 12, opacity: 0.8, alignSelf: 'center' }}>
              {failedChecks.length > 0
                ? `Blocked by ${failedChecks.length} failed check${failedChecks.length === 1 ? '' : 's'}`
                : stale ? 'Blocked: stale base revision'
                : 'Blocked: preview incomplete'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default EditPreview;
