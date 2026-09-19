/**
 * Mount point for Team A's CAD viewport.
 *
 * `apps/web/src/features/cad/` belongs to Team A (architecture section 11). Team B owns the shell,
 * so this file exists to define the boundary between them: A replaces the body of this component
 * with the React Three Fiber viewport, and reads the revision and selection from the shared
 * workbench context rather than keeping its own.
 *
 * Until then it renders what is genuinely known about the geometry, which is more useful during
 * integration than an empty box - and it claims no rendering it cannot do.
 */

import { useWorkbench } from "@/app/WorkbenchContext";
import type { Claim } from "@/lib/contracts.gen";

export function CadViewportMount() {
  const { parts, selectedPartId, revisionId } = useWorkbench();
  const features = parts?.geometry_features;
  const selected = parts?.parts.occurrences.find((item) => item.part_id === selectedPartId);

  return (
    <div className="viewport-mount">
      <header>
        <h2>Geometry</h2>
        <span className="chip pending">features/cad — Team A</span>
      </header>

      <p className="muted">
        The 3D viewport mounts here. It is Team A&apos;s component and is not installed yet, so no
        rendering is claimed. The quantities below come from <code>geometry_features.json</code>,
        the same source the evaluator reads - there is no second copy of the wing dimensions.
      </p>

      {features ? (
        <dl className="features">
          <div>
            <dt>Revision</dt>
            <dd>
              <code>{revisionId?.slice(0, 12)}</code>
            </dd>
          </div>
          <div>
            <dt>Wing span</dt>
            <dd>{renderClaim(features.wing_span_m)}</dd>
          </div>
          <div>
            <dt>Reference area</dt>
            <dd>{renderClaim(features.wing_reference_area_m2)}</dd>
          </div>
          <div>
            <dt>MAC</dt>
            <dd>{renderClaim(features.wing_mac_m)}</dd>
          </div>
          <div>
            <dt>V-tail panels</dt>
            <dd>{features.vtail_panels?.length ?? 0}</dd>
          </div>
          <div>
            <dt>Frame</dt>
            <dd className={features.frame_confirmed ? "" : "warn"}>
              {features.frame_confirmed ? "confirmed" : "unconfirmed"}
            </dd>
          </div>
        </dl>
      ) : null}

      {features?.quality_limits?.length ? (
        <div className="limits">
          <h3>Stated limits of this geometry</h3>
          <ul>
            {features.quality_limits.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {selected ? (
        <p className="selection">
          Selected: <strong>{selected.name}</strong> at x ={" "}
          {(selected.transform?.matrix?.[0]?.[3] ?? 0).toFixed(3)} m — canonical FRD, X forward, so a
          station aft of the nose is negative.
        </p>
      ) : null}
    </div>
  );
}

function renderClaim(claim: Claim | undefined): string {
  if (!claim || claim.value === null || claim.value === undefined) return "unknown";
  return `${claim.value} ${claim.unit}`;
}
