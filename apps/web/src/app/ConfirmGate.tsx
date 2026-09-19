/**
 * The confirmation gate (architecture section 6, steps 3 and 8).
 *
 * "Show three confirmation controls: units, axes, variant selection. Guessing can initialize the
 * controls but cannot silently confirm them." And step 8: a recorded "reconstruction confirmed"
 * decision is required "before engineering comparison".
 *
 * Without this panel the rule still held — the validator rejected every proposal with "the
 * reconstruction has not been confirmed" — but the user had no way to satisfy it and no way to see
 * why. A gate the product enforces and the interface hides is worse than no gate: it looks like
 * the recommender simply has nothing to say.
 */

import { useWorkbench } from "./WorkbenchContext";

export function ConfirmGate() {
  const { parts, confirmDesign, busy } = useWorkbench();
  const features = parts?.geometry_features;
  if (!features) return null;

  const unitsOk = Boolean(features.units_confirmed);
  const frameOk = Boolean(features.frame_confirmed);
  const reconstructionOk = Boolean(features.reconstruction_confirmed);
  if (unitsOk && frameOk && reconstructionOk) return null;

  const outstanding = [
    !unitsOk ? "units" : null,
    !frameOk ? "the coordinate frame" : null,
    !reconstructionOk ? "the reconstruction" : null,
  ].filter(Boolean) as string[];

  return (
    <section className="gate">
      <h3>Unconfirmed</h3>
      <p>
        This design was imported with {outstanding.join(", ")} unconfirmed. Until you confirm,
        no edit can be proposed and no metric is treated as an engineering result.
      </p>

      <dl className="gate-items">
        <div>
          <dt>Units</dt>
          <dd>metres, kilograms, radians</dd>
        </div>
        <div>
          <dt>Frame</dt>
          <dd>{features.nose_datum_note ? "FRD, nose datum declared" : "FRD"}</dd>
        </div>
        <div>
          <dt>Fit error</dt>
          <dd>
            {features.fit_error_m.value === null
              ? "unknown"
              : `${features.fit_error_m.value} ${features.fit_error_m.unit}`}
          </dd>
        </div>
      </dl>

      {features.nose_datum_note ? <p className="gate-note">{features.nose_datum_note}</p> : null}

      <button
        type="button"
        className="primary"
        disabled={Boolean(busy)}
        onClick={() => void confirmDesign({ reconstruction: true, claims: [] })}
      >
        {busy ? "Confirming…" : "Confirm units, frame, and reconstruction"}
      </button>

      <p className="gate-note">
        Recorded as a decision on a new revision. It does not change any geometry.
      </p>
    </section>
  );
}
