/**
 * Hand-written mirror of `packages/contracts/dronebench_contracts/models.py` (schema 0.1.0).
 *
 * TEMPORARY. Architecture §11 says TypeScript types are generated from the contract's JSON
 * Schema and that B owns that generation. Replace this file with the generated module and
 * re-export the same names; nothing else in `features/cad` should need to change.
 *
 * Conventions that the components rely on:
 * - FRD frame: x forward, y right, z down, origin at the confirmed nose datum. SI units.
 * - Unknown values are `null`, never 0. Every engineering number is a `Claim`.
 * - `T_parent_from_local` is row-major 4x4 applied to column vectors; mirroring is never a
 *   placement, it is a separate definition.
 */

export const SCHEMA_VERSION = '0.1.0';

export type Status = 'known' | 'estimated' | 'unknown' | 'conflicted';

export type SourceKind =
  | 'cad' | 'bom' | 'manual' | 'catalog' | 'computed' | 'inferred' | 'assumed' | 'user';

export type Representation =
  | 'reference_mesh' | 'reconstruction' | 'envelope' | 'component_export';

export type EditCapability =
  | 'none' | 'translate_component' | 'resize_spar'
  | 'set_wing_tip_extension' | 'replace_catalog_component';

export type EditOperation =
  | 'translate_component' | 'resize_spar'
  | 'set_wing_tip_extension' | 'replace_catalog_component';

export type ErrorCode =
  | 'UNITS_UNCONFIRMED' | 'ASSEMBLY_UNCONFIRMED' | 'MISSING_EVIDENCE' | 'UNSUPPORTED_EDIT'
  | 'STALE_REVISION' | 'GEOMETRY_INVALID' | 'CONSTRAINT_FAILED' | 'SOLVER_UNAVAILABLE'
  | 'SOLVER_TIMEOUT' | 'ARTIFACT_MISMATCH' | 'INPUT_REJECTED';

export interface Evidence {
  evidence_id: string;
  uri: string;
  sha256?: string | null;
  locator?: string | null;
  method: string;
  accessed_at?: string | null;
  note?: string | null;
}

export interface Claim<T = unknown> {
  /** null whenever `status === 'unknown'`; never substitute 0. */
  value: T | null;
  unit?: string | null;
  status: Status;
  source_kind?: SourceKind | null;
  evidence_ids: string[];
  confidence?: number | null;
  assumptions: string[];
}

export interface ErrorEnvelope {
  code: ErrorCode;
  message: string;
  revision_id?: string | null;
  details: Record<string, unknown>;
  retryable: boolean;
}

export interface Artifact {
  path: string;
  sha256: string;
  media_type: string;
  representation?: Representation | null;
  part_ids: string[];
}

export interface MeshQA {
  triangles: number;
  finite: boolean;
  watertight: boolean;
  components: number;
  degenerate_faces: number;
  consistent_winding: boolean;
  bounds_native: number[][];
}

export interface SourceFile {
  source_path: string;
  sha256: string;
  size_bytes: number;
  qa: MeshQA;
  folder_hint?: string | null;
}

export interface VariantGroup {
  group_id: string;
  options: string[];
  /** null until a human confirms: never auto-selected. */
  selected?: string | null;
  reason?: string | null;
}

export interface FrameConfirmation {
  units: 'mm' | 'm' | 'in';
  /** 3x3 proper rotation (det +1) applied after scaling. */
  native_to_frd: number[][];
  scale_to_m: number;
  nose_datum_native: number[];
  mirror_plane_native?: string | null;
  confirmed: boolean;
  confirmed_by?: string | null;
  notes: string[];
}

export interface PartOccurrence {
  part_id: string;
  definition_id: string;
  name: string;
  category: string;
  side?: 'left' | 'right' | 'center' | null;
  mirror_of?: string | null;
  representation: Representation;
  source?: string | null;
  T_parent_from_local: number[][];
  mass_kg: Claim<number>;
  local_com_m: Claim<number[]>;
  material: Claim<string>;
  function: Claim<string>;
  edit_capabilities: EditCapability[];
  allowed_overlap_with: string[];
  locked: boolean;
  labels: Record<string, string>;
}

export interface DesignManifest {
  schema_version: string;
  design_id: string;
  revision_id: string;
  title: string;
  frame: FrameConfirmation;
  sources_root?: string | null;
  mass_model?: 'none' | 'shell_estimate';
  sources: SourceFile[];
  variants: VariantGroup[];
  excluded_sources: string[];
  parts: PartOccurrence[];
  evidence: Evidence[];
  warnings: string[];
}

export interface WingStation {
  span_y_m: number;
  leading_edge_x_m: number;
  chord_m: number;
  z_m: number;
  twist_rad: number;
  thickness_ratio?: number | null;
}

export interface LiftingSurface {
  surface_id: string;
  part_ids: string[];
  stations: WingStation[];
  symmetric: boolean;
  cant_rad?: number | null;
  span_m: Claim<number>;
  area_m2: Claim<number>;
  mac_m: Claim<number>;
  x_mac_le_m: Claim<number>;
  aspect_ratio: Claim<number>;
  sweep_le_rad: Claim<number>;
  dihedral_rad: Claim<number>;
  airfoil: Claim<string>;
  control_surfaces: string[];
  fit_rms_m?: number | null;
}

export interface FuselageStation {
  x_m: number;
  width_m: number;
  height_m: number;
  z_center_m: number;
}

export interface GeometryFeatures {
  schema_version: string;
  design_id: string;
  revision_id: string;
  frame: 'FRD';
  reference_area_m2: Claim<number>;
  reference_span_m: Claim<number>;
  reference_chord_m: Claim<number>;
  surfaces: LiftingSurface[];
  fuselage: FuselageStation[];
  fuselage_length_m: Claim<number>;
  mass_kg: Claim<number>;
  cg_m: Claim<number[]>;
  quality: Record<string, unknown>;
}

export interface RoundTripCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface CadEditChange {
  part_id: string;
  field: string;
  before: unknown;
  after: unknown;
  unit?: string | null;
}

export interface CadEditRequest {
  base_revision_id: string;
  operation: EditOperation;
  target_part_ids: string[];
  parameters: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface CadEditResult {
  schema_version: string;
  base_revision_id: string;
  preview_revision_id?: string | null;
  operation: EditOperation;
  status: 'ok' | 'blocked' | 'failed';
  affected_part_ids: string[];
  changes: CadEditChange[];
  checks: RoundTripCheck[];
  artifacts: Artifact[];
  error?: ErrorEnvelope | null;
}

/* ---------------------------------------------------------------- viewer-local types */

/** Which geometry representation the viewport is showing. Never let these blur (§2). */
export type ViewMode = 'reference' | 'reconstruction' | 'overlay';

export const VIEW_MODE_LABEL: Record<ViewMode, string> = {
  reference: 'Original mesh reference',
  reconstruction: 'Editable reconstruction',
  overlay: 'Overlay — reconstruction over reference',
};

export type ColourBy = 'status' | 'category' | 'neutral';

/** Resolves a revision-relative artifact path to something the browser can fetch. */
export type ArtifactResolver = (path: string) => string;

/** What the user confirmed in `ConfirmPanel`; matches `confirm(...)` in packages/ingest. */
export interface ConfirmPayload {
  design_id: string;
  revision_id: string;
  units: 'mm' | 'm' | 'in';
  /** 3x3 proper rotation, as offered by `propose_frame` or edited by the axis picker. */
  native_to_frd: number[][];
  nose_datum_native: number[];
  mirror_plane_native: string | null;
  /** group_id -> chosen source_path. Every group must be answered. */
  variant_selection: Record<string, string>;
  mass_model: 'none' | 'shell_estimate';
  confirmed_by: string;
  notes: string[];
}

export interface FitReportPart {
  part_id: string;
  rms_m?: number | null;
  max_m?: number | null;
  note?: string | null;
}

export interface FitReport {
  rms_m?: number | null;
  max_m?: number | null;
  method?: string | null;
  per_part: FitReportPart[];
  note?: string | null;
}

/* ---------------------------------------------------------------- helpers */

export const STATUS_ORDER: Status[] = ['conflicted', 'unknown', 'estimated', 'known'];

/** Status colours. Colour is never the only signal — always pair with a text chip. */
export const STATUS_COLOR: Record<Status, string> = {
  known: '#0f7a52',
  estimated: '#1d4ed8',
  unknown: '#d08300',
  conflicted: '#b3261e',
};

export const CATEGORY_COLOR: Record<string, string> = {
  wing: '#3b82f6', aileron: '#60a5fa', fuselage: '#94a3b8', canopy: '#cbd5e1', hatch: '#a3adbb',
  vtail: '#8b5cf6', ruddervator: '#a78bfa', mount: '#64748b', spar: '#ef8f3c', battery: '#14b8a6',
  motor: '#e05252', prop: '#f472b6', servo: '#22c55e', esc: '#84cc16', fc: '#06b6d4', rx: '#0ea5e9',
  gps: '#38bdf8', payload: '#fbbf24', other: '#9ca3af',
};

export const NEUTRAL_COLOR = '#9aa3ad';

export function isUnknown(claim?: Claim<unknown> | null): boolean {
  return !claim || claim.status === 'unknown' || claim.value === null || claim.value === undefined;
}

/** The worst status across a part's claims: conflicted > unknown > estimated > known. */
export function partStatus(part: PartOccurrence): Status {
  const seen = [part.mass_kg, part.local_com_m, part.material, part.function]
    .map((c) => (c ? c.status : 'unknown'));
  return STATUS_ORDER.find((s) => seen.includes(s)) ?? 'unknown';
}

export function partColor(part: PartOccurrence, colourBy: ColourBy): string {
  if (colourBy === 'neutral') return NEUTRAL_COLOR;
  if (colourBy === 'category') return CATEGORY_COLOR[part.category] ?? CATEGORY_COLOR.other;
  return STATUS_COLOR[partStatus(part)];
}

/** Render a claim for display. Unknown is words, never a number. */
export function formatClaim(claim?: Claim<unknown> | null): string {
  if (isUnknown(claim)) return 'unknown — needs evidence';
  const v = claim!.value;
  const text = Array.isArray(v) ? `[${v.join(', ')}]` : String(v);
  return claim!.unit ? `${text} ${claim!.unit}` : text;
}
