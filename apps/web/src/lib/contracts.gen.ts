/**
 * Generated from schema/dronebench.schema.json. Do not edit by hand.
 *
 * Regenerate with:  python scripts/generate_ts_types.py
 *
 * Architecture section 11: the web app consumes generated types, never hand-written lookalikes.
 * A field that is `| null` here is a value the backend reports as genuinely unknown - render it as
 * unknown, never as zero.
 */

export const CONTRACT_VERSION = "1.0" as const;

/** One immutable file belonging to a revision or run. */
export interface Artifact {
  "artifact_id": string;
  "media_type": "application/json" | "application/step" | "model/gltf-binary" | "text/plain" | "text/csv" | "application/octet-stream";
  "part_ids"?: string[];
  /** Owning team, so a consumer can tell a stub from a real producer. */
  "produced_by": "A" | "B" | "C";
  /** Path relative to the revision directory. Never an absolute or escaping path. */
  "relative_path": string;
  "representation"?: "reference_mesh" | "editable_reconstruction" | "catalog_envelope" | "generated" | null;
  /** design_manifest | parts | graph | evaluation | step | glb | ... */
  "role": string;
  "sha256": string;
  "size_bytes": number;
}

/** One immutable log line. There is deliberately no field for model reasoning. */
export interface AuditEvent {
  "artifact_ids"?: string[];
  "created_at"?: string;
  "design_id": string;
  "elapsed_s"?: number;
  "error_code"?: string | null;
  "event_id": string;
  /** Short scalars only. Never a payload dump. */
  "inputs_summary"?: Record<string, string>;
  "job_id"?: string | null;
  "kind": "job_queued" | "job_started" | "job_progress" | "job_succeeded" | "job_failed" | "job_cancelled" | "revision_created" | "revision_activated" | "proposal_generated" | "proposal_previewed" | "proposal_declined" | "proposal_committed" | "proposal_stale" | "evaluation_completed" | "export_completed";
  "proposal_id"?: string | null;
  "revision_id"?: string | null;
  /** Monotonic per design. The SSE last-event-id. */
  "sequence": number;
  "status"?: "ok" | "error" | "in_progress";
  /** The tool or service function that ran. */
  "tool_name": string;
}

/** Bounds in canonical FRD metres. */
export interface AxisAlignedBox {
  "max_m": [number, number, number];
  "min_m": [number, number, number];
}

/** ``cad_edit_result.json`` - A's tool, called by B, consumed by everyone. ``ok`` false means the edit did not produce valid geometry. B never promotes such a preview. */
export interface CadEditResult {
  "affected_part_ids"?: string[];
  "base_revision_id": string;
  "diagnostics"?: string[];
  "glb_artifact_id"?: string | null;
  "interference"?: InterferenceFinding[];
  "mass_delta_kg"?: Claim | null;
  "ok": boolean;
  "operation": "translate_component" | "resize_spar" | "set_wing_tip_extension" | "replace_catalog_component";
  "part_map_artifact_id"?: string | null;
  "part_signatures_after"?: PartSignature[];
  "part_signatures_before"?: PartSignature[];
  "preview_revision_id"?: string | null;
  /** B-stub marks the reference CAD port B uses until Team A's kernel lands. */
  "produced_by": "A" | "B-stub";
  "representation"?: "reference_mesh" | "editable_reconstruction" | "catalog_envelope" | "generated";
  "requested_parameters_applied"?: Record<string, number>;
  "round_trip"?: RoundTripCheck;
  "schema_version"?: "1.0";
  "step_artifact_id"?: string | null;
  "unchanged_parts_verified"?: boolean;
}

/** One catalog part: its claims, its declared interfaces, and its offers. */
export interface CatalogItem {
  "catalog_item_id": string;
  "category": "battery" | "spar" | "servo" | "motor" | "propeller" | "esc";
  "claims"?: Record<string, Claim>;
  "display_name": string;
  "evidence_ids"?: string[];
  "interfaces"?: DeclaredInterface[];
  "mass_kg": Claim;
  "offers"?: CatalogOffer[];
}

/** A purchasable offer. Synthetic entries may not name a supplier or link a product. */
export interface CatalogOffer {
  "currency"?: "USD" | "EUR" | "GBP" | null;
  "lead_time_days"?: number | null;
  "product_url"?: string | null;
  "quantity_basis"?: "each" | "pair" | "pack_of_4" | "per_metre" | null;
  "region"?: string | null;
  "source_timestamp"?: string | null;
  /** Where the figures were read, for a verified entry. */
  "source_url"?: string | null;
  "stock_known"?: boolean;
  "stock_units"?: number | null;
  "supplier_name"?: string | null;
  /** A clearly labelled demo entry with no implied real supplier offer. */
  "synthetic"?: boolean;
  "unit_price"?: number | null;
}

/** The frozen, checked-in catalog. Live supplier search is optional and never required. */
export interface CatalogSnapshot {
  /** True when every offer in the snapshot is a demo entry. */
  "all_synthetic"?: boolean;
  "captured_at": string;
  "items": CatalogItem[];
  "schema_version"?: "1.0";
  "snapshot_id": string;
}

/** The versioned set of checks a mission profile requires. Frozen by construction. */
export interface CheckRegistry {
  "checks": RequiredCheck[];
  "registry_version": string;
}

/** One check outcome. ``unknown`` is a legitimate result and must not be coerced to a pass. */
export interface CheckResult {
  "check_class": "hard_invariant" | "modeled_constraint" | "regulatory" | "informational";
  "check_id": string;
  /** Human-readable statement of the bound. */
  "limit"?: string | null;
  "missing_inputs"?: string[];
  "reason": string;
  "status": "pass" | "fail" | "unknown" | "not_applicable";
  "title": string;
  "value"?: Claim | null;
}

/** A single asserted quantity with its provenance. ``value is None`` means unknown. It does not mean zero, and it may not carry a confidence. */
export interface Claim {
  /** Declared modelling assumptions this value depends on. */
  "assumptions"?: string[];
  /** Optional and uncalibrated unless a calibration record is cited. Not a statistical probability. */
  "confidence"?: number | null;
  "evidence_ids"?: string[];
  "source_kind": "cad" | "bom" | "manual" | "catalog" | "computed" | "inferred" | "assumed";
  "status": "known" | "estimated" | "unknown" | "conflicted";
  "unit": "m" | "m^2" | "m^3" | "m^4" | "kg" | "kg*m^2" | "N" | "N*m" | "Pa" | "s" | "min" | "h" | "A" | "V" | "W" | "Wh" | "Wh/km" | "rad" | "K" | "m/s" | "km" | "km/h" | "kg/m^3" | "1" | "count" | "USD";
  "value"?: number | string | boolean | null;
}

/** Named claims for one entity, plus any preserved conflicts. */
export interface ClaimSet {
  "claims"?: Record<string, Claim>;
  "conflicts"?: ConflictSet[];
}

/** Baseline and candidate evaluated at identical conditions (architecture section 8). Construction fails if the two sides used different missions, registries, or fidelity tiers, so an analytic baseline can never be subtracted from a VSPAERO-informed candidate. */
export interface ComparisonPair {
  "baseline": Evaluation;
  "candidate": Evaluation;
  "metric": string;
}

/** Conflicting claims for one quantity, preserved with an explicit selection and rationale. Architecture section 5: never silently alter evidence. Every candidate stays; the selection and the reason for it are recorded alongside them. */
export interface ConflictSet {
  "candidates": Claim[];
  "quantity": string;
  "rationale": string;
  "selected_index": number;
}

/** What a decision did. A repeated idempotency key returns this object unchanged. */
export interface DecisionOutcome {
  /** The active revision after the decision. A decline leaves it untouched. */
  "active_revision_id": string;
  "committed_revision_id"?: string | null;
  "decision": "accept" | "decline";
  "idempotency_key": string;
  "message"?: string;
  "proposal_id": string;
  /** True when this outcome was returned from the idempotency store. */
  "replayed"?: boolean;
  "state": "proposed" | "previewing" | "review_ready" | "blocked" | "declined" | "committing" | "committed" | "stale" | "failed";
}

/** An accept or decline. The four fields on an accept are what make CAS possible. */
export interface DecisionRequest {
  "decision": "accept" | "decline";
  "expected_active_revision_id": string;
  "idempotency_key": string;
  /** Required on accept: the exact preview the user reviewed. */
  "preview_hash"?: string | null;
  "proposal_id": string;
  /** Optional note, recorded on a decline. */
  "reason"?: string | null;
}

/** A machine-checkable interface. ``compatible_with`` is computed only from these. */
export interface DeclaredInterface {
  "current_limit_a"?: number | null;
  "dimensions_m"?: Record<string, number>;
  "interface_id": string;
  "kind": "mechanical_bore" | "mechanical_bolt" | "electrical_dc" | "signal_pwm" | "mass_envelope";
  "polarity"?: "male" | "female" | "either";
  /** Inclusive (min, max) operating voltage. */
  "voltage_v"?: [number, number] | null;
}

/** ``design_manifest.json`` - A -> B/C (architecture section 5). */
export interface DesignManifest {
  "design_id": string;
  "display_name": string;
  /** Variant bodies deliberately not installed. They must not count as mass. */
  "excluded_alternatives"?: string[];
  "notes"?: string[];
  "representation_mode": "reference_mesh" | "editable_reconstruction";
  "revision_id": string;
  "schema_version"?: "1.0";
  "source_archive_sha256"?: string | null;
}

export type EditOperation = TranslateComponent | ResizeSpar | SetWingTipExtension | ReplaceCatalogComponent;

/** The single error shape every endpoint and CLI command returns. */
export interface ErrorEnvelope {
  "code": "UNITS_UNCONFIRMED" | "ASSEMBLY_UNCONFIRMED" | "MISSING_EVIDENCE" | "UNSUPPORTED_EDIT" | "STALE_REVISION" | "GEOMETRY_INVALID" | "CONSTRAINT_FAILED" | "SOLVER_UNAVAILABLE" | "SOLVER_TIMEOUT" | "ARTIFACT_MISMATCH" | "NOT_FOUND" | "INVALID_REQUEST" | "CONFLICT" | "INTERNAL";
  "details"?: Record<string, unknown>;
  "message": string;
  "retryable"?: boolean;
  "revision_id"?: string | null;
}

/** ``evaluation.json`` - C -> B/UI. */
export interface Evaluation {
  "checks"?: CheckResult[];
  "elapsed_s"?: number;
  "evaluation_id": string;
  "fidelity": "analytic" | "vspaero_informed" | "replay";
  /** Section 8: report inputs and unknowns before numbers. */
  "inputs_used"?: Record<string, Claim>;
  "metrics"?: Record<string, Claim>;
  "mission_hash": string;
  /** Openly listed. A short list here is what keeps the numbers honest. */
  "omitted_physics"?: string[];
  /** B-stub marks the reference evaluator B uses until Team C's lands. */
  "produced_by": "C" | "B-stub";
  "registry_version": string;
  "revision_id": string;
  "run_input_hash": string;
  "schema_version"?: "1.0";
  "sensitivity"?: SensitivityInterval[];
  "solver": SolverManifest;
  "unknown_inputs"?: string[];
  /** True only when nothing blocking fails and nothing blocking is unknown. Serialised deliberately. The UI must not re-derive feasibility from the check list: that would put a second definition of "verified" in the codebase, and the two would drift. */
  "verified_feasible": boolean;
}

/** One retrievable source record behind a claim. */
export interface Evidence {
  /** When the source was read. Display-only; excluded from hashes. */
  "accessed_at"?: string | null;
  /** Hash of the source bytes when the source is a retrievable file. */
  "content_sha256"?: string | null;
  "evidence_id": string;
  /** How the value was obtained: stl_bounds, manual_entry, catalog_field, ... */
  "extraction_method": string;
  /** Page, table, field, body name, or line range in the source. */
  "locator"?: string | null;
  /** Display-only; excluded from hashes. */
  "note"?: string | null;
  "source_kind": "cad" | "bom" | "manual" | "catalog" | "computed" | "inferred" | "assumed";
  /** URI or repository-relative path of the source */
  "source_uri": string;
  "valid_from"?: string | null;
  "valid_to"?: string | null;
}

/** ``graph.json`` - B -> UI/recommender. */
export interface EvidenceGraph {
  "edges": GraphEdge[];
  "evidence"?: Evidence[];
  "nodes": GraphNode[];
  "revision_id": string;
  "schema_version"?: "1.0";
  /** Relationships the source material does not determine, stated openly rather than guessed. These drive the 'what evidence is missing' answers in the UI. */
  "unknown_relationships"?: string[];
}

/** A candidate that asks for a missing fact instead of proposing an edit. Section 7 step 2 names this explicitly: "ask for missing battery mass before promising endurance." It is modelled separately from :class:`Recommendation` so the edit-operation union stays closed - the four operations in section 6 are the only things that can change geometry. */
export interface EvidenceRequest {
  "base_revision_id": string;
  "blocked_check_ids"?: string[];
  /** Dotted path of the claim to supply, e.g. prt_harness.mass_kg */
  "quantity": string;
  "request_id": string;
  /** What would count as adequate evidence. Never 'inferred' for a mass. */
  "suggested_source_kinds"?: string[];
  "target_part_id"?: string | null;
  "title": string;
  "unit": string;
  /** Which checks are unknown until this is supplied. */
  "why_it_matters": string;
}

/** A short typed path answering one of the section 7 narrow queries. */
export interface ExplanationPath {
  "conclusion": string;
  "missing_evidence"?: string[];
  "question": string;
  "steps": PathStep[];
  /** The least certain link on the path. An inferred hop caps the whole claim. */
  "weakest_status": "known" | "estimated" | "unknown" | "conflicted";
}

/** ``geometry_features.json`` - A -> C/B (architecture section 5). The single source of wing/tail dimensions. Section 8 forbids the evaluator from maintaining its own copy, so anything downstream that needs a reference area reads it from here. */
export interface GeometryFeatures {
  /** Deviation of the reconstruction from the reference silhouette. */
  "fit_error_m": Claim;
  /** False until units, axes, nose datum, and symmetry have been confirmed. */
  "frame_confirmed": boolean;
  /** Aft-positive station of the neutral point. Architecture section 8 permits a documented synthetic fixture to supply this as an assumption for illustrating the workflow, and requires the report to identify it as assumed. A wing quarter-chord guess does not qualify for a V-tail aircraft, so the validator below refuses any source kind other than 'assumed' until a real stability method produces one. */
  "neutral_point_station_m"?: Claim | null;
  "nose_datum_note": string;
  "quality_limits"?: string[];
  /** A recorded human decision. Engineering comparison is blocked until true. */
  "reconstruction_confirmed"?: boolean;
  "revision_id": string;
  "schema_version"?: "1.0";
  "units_confirmed"?: boolean;
  "vtail_panels"?: VTailPanel[];
  "wing_mac_m": Claim;
  "wing_reference_area_m2": Claim;
  "wing_span_m": Claim;
  "wing_stations"?: WingStation[];
}

/** A typed relation carrying its own evidence, status, and revision scope. */
export interface GraphEdge {
  /** Required for compatible_with. Anything other than declared_interfaces is a bug. */
  "basis"?: "declared_interfaces" | "not_computed" | null;
  "edge_id": string;
  "evidence_ids"?: string[];
  "properties"?: Record<string, unknown>;
  "relation": "instance_of" | "made_of" | "performs" | "exposes" | "mates_with" | "near" | "powers" | "controls" | "compatible_with" | "offered_by" | "constrained_by" | "applies_to" | "supported_by" | "evaluated_in";
  "revision_id": string;
  "source_id": string;
  "status"?: "known" | "estimated" | "unknown" | "conflicted";
  "target_id": string;
}

/** A typed node, scoped to one revision. */
export interface GraphNode {
  "claims"?: Record<string, Claim>;
  "evidence_ids"?: string[];
  "label": string;
  "node_id": string;
  "node_type": "PartOccurrence" | "PartDefinition" | "Material" | "Function" | "Interface" | "CatalogItem" | "Supplier" | "Constraint" | "Regulation" | "Mission" | "Evidence" | "AnalysisRun";
  "properties"?: Record<string, unknown>;
  "revision_id": string;
  "status"?: "known" | "estimated" | "unknown" | "conflicted";
}

/** An overlap that was *not* a declared mating, bonded, or nesting pair. */
export interface InterferenceFinding {
  "kind": "unintended_overlap" | "propeller_swept_volume";
  "overlap_volume_m3"?: number | null;
  "part_id_a": string;
  "part_id_b": string;
}

/** A queued unit of work. Long native work never runs inside an HTTP request thread. */
export interface JobRecord {
  "artifact_ids"?: string[];
  "cache_hit"?: boolean;
  /** Covers revision content, mission, solver version and settings, model tier, and the relevant evidence/catalog snapshot hashes. */
  "cache_key": string;
  "created_at"?: string;
  "design_id": string;
  "elapsed_s"?: number;
  "error_code"?: string | null;
  "error_message"?: string | null;
  "job_id": string;
  "kind": "import" | "confirm" | "evaluate" | "recommend" | "preview" | "simulate" | "export";
  "progress_note"?: string;
  /** Set on a cache hit so the UI can show the reused run. */
  "reused_job_id"?: string | null;
  "revision_id"?: string | null;
  "status": "queued" | "running" | "succeeded" | "failed" | "cancelled";
  /** Unique per job. Native solvers emit many same-named files, so they cannot share. */
  "work_dir": string;
}

/** The locked mission. Its hash pins every evaluation and cache key. */
export interface Mission {
  "air_density_kgm3": number;
  "altitude_m": number;
  /** Aft-positive station bounds (s = -x) for the centre of gravity. */
  "cg_envelope_station_m": [number, number];
  "cruise_speed_mps": number;
  /** Withheld before usable energy is computed. */
  "energy_reserve_fraction": number;
  "load_factor_limit": number;
  /** Mission payload occurrences that may not be removed or moved. */
  "locked_part_ids"?: string[];
  "max_takeoff_mass_kg": number;
  "mission_id": string;
  "objective"?: "max_endurance";
  "payload_mass_kg": number;
  "registry_version"?: string;
  "regulatory": RegulatoryProfile;
  "route_length_km": number;
  "schema_version"?: "1.0";
  /** Required fraction by which cruise speed exceeds stall speed. */
  "stall_margin_fraction": number;
  /** Acceptable (min, max) static margin as a fraction of MAC. Must be consistent with cg_envelope_station_m and the neutral point, or the two checks contradict each other; the validator below enforces that. */
  "static_margin_bounds"?: [number, number];
  "title": string;
}

/** A bounded subgraph. The whole graph is never sent to a model or rendered at once. */
export interface Neighborhood {
  "center_id": string;
  "edges": GraphEdge[];
  "node_budget"?: number;
  "nodes": GraphNode[];
  "radius": number;
  "revision_id": string;
  /** True when the node budget cut the traversal short. */
  "truncated"?: boolean;
}

/** Reusable geometry. Several occurrences may share one definition. */
export interface PartDefinition {
  "claims"?: ClaimSet;
  "definition_id": string;
  "name": string;
  /** Editable parameters in canonical SI, for reconstructed/generated geometry. */
  "parameters"?: Record<string, number>;
  "representation": "reference_mesh" | "editable_reconstruction" | "catalog_envelope" | "generated";
  "role"?: "wing" | "tail_panel" | "fuselage" | "spar" | "battery" | "motor" | "propeller" | "esc" | "servo" | "flight_controller" | "receiver" | "gps" | "payload" | "mount" | "fastener" | "harness" | "hatch" | "landing_gear" | "other" | "unknown";
  "source"?: SourceRef;
}

/** One installed instance of a definition, at a placement, with its own claims. */
export interface PartOccurrence {
  /** Declared mating/bonded/nesting partners. Overlap with these is intended engagement, not interference. */
  "allowed_contact_part_ids"?: string[];
  "bounds_local_m"?: AxisAlignedBox | null;
  "claims"?: ClaimSet;
  "definition_id": string;
  "edit_capabilities"?: ("translate_component" | "resize_spar" | "set_wing_tip_extension" | "replace_catalog_component")[];
  /** Centre of mass in the occurrence's own frame, with its own evidence. Absent means the mass distribution is unknown, not that it coincides with the placement datum. */
  "local_com_m"?: [Claim, Claim, Claim] | null;
  /** Mission payload or otherwise not removable/movable. */
  "locked"?: boolean;
  "mass_kg": Claim;
  /** The part_id this occurrence mirrors. Distinct identity, possibly shared asset. */
  "mirror_of"?: string | null;
  "name": string;
  "parent_part_id"?: string | null;
  "part_id": string;
  "role"?: "wing" | "tail_panel" | "fuselage" | "spar" | "battery" | "motor" | "propeller" | "esc" | "servo" | "flight_controller" | "receiver" | "gps" | "payload" | "mount" | "fastener" | "harness" | "hatch" | "landing_gear" | "other" | "unknown";
  "transform"?: Transform;
  "travel_corridor"?: TravelCorridor | null;
}

/** A semantic fingerprint used to prove an unchanged part really did not change. Section 6 export acceptance: compare semantic geometry, not STEP byte hashes, and do not require entity numbers or face ordering to remain stable. */
export interface PartSignature {
  "bounds_max_m"?: [number, number, number] | null;
  "bounds_min_m"?: [number, number, number] | null;
  "part_id": string;
  "placement_translation_m"?: [number, number, number] | null;
  "solid_count"?: number;
  "volume_m3"?: number | null;
}

/** ``parts.json`` - A -> B/C. Installed occurrences plus their definitions and evidence. */
export interface PartsDocument {
  "definitions": PartDefinition[];
  "evidence"?: Evidence[];
  "occurrences": PartOccurrence[];
  "revision_id": string;
  "schema_version"?: "1.0";
}

/** One hop of an explanation path. */
export interface PathStep {
  "evidence_ids"?: string[];
  "from_id": string;
  "from_label": string;
  "relation": "instance_of" | "made_of" | "performs" | "exposes" | "mates_with" | "near" | "powers" | "controls" | "compatible_with" | "offered_by" | "constrained_by" | "applies_to" | "supported_by" | "evaluated_in";
  "status": "known" | "estimated" | "unknown" | "conflicted";
  "to_id": string;
  "to_label": string;
}

/** The concrete, immutable child revision a proposal was actually evaluated on. ``preview_hash`` is what an acceptance must quote. Accepting anything else is refused, which is how "accept commits precisely the reviewed preview" becomes mechanical. */
export interface PreviewResult {
  "base_revision_id": string;
  "baseline_evaluation"?: Evaluation | null;
  "blocked_reasons"?: string[];
  "cad_ok": boolean;
  "change_summary"?: string[];
  "evaluation"?: Evaluation | null;
  "preview_hash": string;
  "preview_revision_id": string;
}

/** Exactly what a provider adapter is allowed to see. Section 7: compute affected constraints with typed traversals; do not send the entire graph to the model. This object is the whole input surface, and it carries no raw geometry. */
export interface ProposalContext {
  "catalog_item_ids"?: string[];
  "design_id": string;
  /** part_id -> the operations it supports. */
  "editable_parts"?: Record<string, string[]>;
  "evidence_notes"?: string[];
  "failing_checks"?: string[];
  "metrics"?: Record<string, Claim>;
  "mission_hash": string;
  "objective": string;
  /** Compact descriptors. Never triangle dumps. */
  "part_summaries"?: string[];
  "revision_id": string;
  "unknown_checks"?: string[];
}

/** One bounded proposal, with its evidence, its preview, and its tradeoffs. */
export interface Recommendation {
  "base_revision_id": string;
  "created_at"?: string;
  "design_id": string;
  "evidence_ids"?: string[];
  "evidence_path"?: ExplanationPath | null;
  /** A provider's narrative expectation, kept only as text. It is never substituted for a computed result and never ranked on. */
  "expected_gain_note"?: string | null;
  /** The specific problem this addresses, in plain language. */
  "issue": string;
  "mission_hash": string;
  "operation": TranslateComponent | ResizeSpar | SetWingTipExtension | ReplaceCatalogComponent;
  "origin"?: "deterministic" | "provider";
  /** Facts that had to be known before this was proposable. */
  "prerequisites"?: string[];
  "preview"?: PreviewResult | null;
  "proposal_id": string;
  "rationale": string;
  "schema_version"?: "1.0";
  "state"?: "proposed" | "previewing" | "review_ready" | "blocked" | "declined" | "committing" | "committed" | "stale" | "failed";
  "title": string;
  "tradeoffs"?: Tradeoff[];
}

/** ``recommendations.json`` - B -> review UI. Budgeted per section 7. */
export interface RecommendationSet {
  "base_revision_id": string;
  "budget_notes"?: string[];
  "displayed_proposal_ids"?: string[];
  /** Asked for before promising a number. These are shown above edit proposals when a required check is unknown, because an edit ranked on unknown inputs is theatre. */
  "evidence_requests"?: EvidenceRequest[];
  "generated"?: Recommendation[];
  "mission_hash": string;
  "provider_calls_used"?: number;
  "schema_version"?: "1.0";
  "unevaluated_count"?: number;
}

/** One jurisdiction and operation profile, chosen in mission setup (architecture section 7). */
export interface RegulatoryProfile {
  "beyond_visual_line_of_sight"?: boolean | null;
  "evidence_ids"?: string[];
  /** Operating within an FAA-Recognized Identification Area. */
  "in_friaa"?: boolean | null;
  "jurisdiction": "US";
  "operation": "part_107_commercial" | "recreational_44809";
  /** None means the fact was not supplied, not that it is false. */
  "over_people"?: boolean | null;
}

/** Swap an envelope/part and its BOM entry atomically. Unresolved fit or current checks block the commit; they do not merely warn. */
export interface ReplaceCatalogComponent {
  "catalog_item_id": string;
  "operation"?: "replace_catalog_component";
  "target_part_id": string;
}

/** One check the mission profile requires every evaluation to report. */
export interface RequiredCheck {
  "check_class": "hard_invariant" | "modeled_constraint" | "regulatory" | "informational";
  "check_id": string;
  "rationale": string;
  "title": string;
}

/** Regenerate a tubular spar, and any mounts included in the same reviewed transaction. Preconditions: the spar is a reconstructed tube, the material assumption is declared, and the shaft/wing-hole/connector limits are known. */
export interface ResizeSpar {
  "inner_diameter_m": number;
  "operation"?: "resize_spar";
  "outer_diameter_m": number;
  /** Compatible mounts regenerated inside the same transaction. */
  "regenerate_mount_part_ids"?: string[];
  "target_part_id": string;
}

/** An immutable design state. */
export interface Revision {
  "content_hash": string;
  "created_at"?: string;
  "created_by_proposal_id"?: string | null;
  "created_cause": "import" | "confirm" | "manual_edit" | "proposal_preview" | "proposal_commit" | "undo";
  "design_id": string;
  "label"?: string;
  /** Hash of the locked mission. Null before a mission is set. */
  "mission_hash"?: string | null;
  "parent_revision_id"?: string | null;
  "revision_id": string;
  "schema_version"?: "1.0";
  "stage": "draft" | "staged_preview" | "committed";
}

/** ``revision_manifest.json`` - B -> all. The coherent artifact set that became active atomically. A half-applied CAD/BOM/report combination cannot be represented: either the manifest lists the full set or it does not exist. */
export interface RevisionManifest {
  "affected_part_ids"?: string[];
  "artifacts"?: Artifact[];
  "change_summary"?: string[];
  "is_active"?: boolean;
  "revision": Revision;
  "schema_version"?: "1.0";
}

/** The export/reimport result. A download is refused without a successful round trip. */
export interface RoundTripCheck {
  "bounds_match"?: boolean;
  "notes"?: string[];
  "performed": boolean;
  "placements_match"?: boolean;
  /** Reimport ran in a fresh worker, not the exporting process. */
  "reimport_worker_fresh"?: boolean;
  "sidecar_identity_coverage"?: number;
  "solids_match"?: boolean;
}

/** A low/nominal/high span over declared uncertain inputs. Section 8 is explicit that this is an "assumption range", not a calibrated confidence interval. The field name and the required label keep that distinction visible downstream. */
export interface SensitivityInterval {
  "high": number;
  "label"?: "assumption range";
  "low": number;
  "metric": string;
  "nominal": number;
  "unit": string;
  "varied_inputs": string[];
}

/** Stretch a parameterised symmetric tip. Regenerates the paired surface too. */
export interface SetWingTipExtension {
  "extension_m": number;
  "operation"?: "set_wing_tip_extension";
  /** The mirrored occurrence regenerated in the same transaction. */
  "paired_part_id": string;
  "target_part_id": string;
}

/** ``simulation_run.json`` - C -> UI. Never mutates the design it analysed. */
export interface SimulationRun {
  /** Section 8: straight-and-level v1 omits maneuver loads and turn drag; animated turns are not a tested turning-flight envelope. */
  "assumptions"?: string[];
  /** False marks an energy-limited run. The route is not silently shortened. */
  "completed_route": boolean;
  "elapsed_s"?: number;
  "fidelity": "analytic" | "vspaero_informed" | "replay";
  "flight_model_tier"?: "reduced_order_mission" | "dynamics_engine";
  "log_artifact_ids"?: string[];
  "mission_hash": string;
  /** A visibly labelled 'Recorded run', not a fresh computation. */
  "recorded_fallback"?: boolean;
  "revision_id": string;
  "run_id": string;
  "samples"?: TelemetrySample[];
  "schema_version"?: "1.0";
  "solver": SolverManifest;
  "telemetry_artifact_id"?: string | null;
  "termination_reason": "route_complete" | "energy_limited" | "cancelled" | "error";
}

/** Exactly which binary produced a result. Required before a solver label may be shown. */
export interface SolverManifest {
  "binary_sha256"?: string | null;
  /** Hash of the geometry actually handed to the solver. */
  "geometry_hash"?: string | null;
  /** Analysis inputs were enumerated from the installed build, not hardcoded. */
  "inputs_discovered_at_runtime"?: boolean;
  "raw_output_artifact_ids"?: string[];
  "solver": "vspaero" | "none";
  "version": string;
}

/** Where an occurrence's geometry came from, preserved so identity survives re-import. */
export interface SourceRef {
  /** Body or occurrence path inside the source assembly. */
  "body_path"?: string | null;
  "original_filename"?: string | null;
  "source_sha256"?: string | null;
  /** Which alternative was selected, when the source offered several. */
  "variant_decision"?: string | null;
}

/** One state along the reduced-order mission model. */
export interface TelemetrySample {
  "altitude_m": number;
  "bank_rad"?: number;
  "distance_km": number;
  "position_frd_m": [number, number, number];
  "power_w": number;
  /** Energy usable after the mission reserve has already been withheld. The run terminates at zero; the display is never clamped while flight continues. */
  "remaining_energy_wh": number;
  "speed_mps": number;
  "t_s": number;
}

/** One metric that moves, in either direction. Section 10: a proposal that increases spar margin but increases mass must show both. A recommendation with only improving tradeoffs and a nonzero mass change is rejected below. */
export interface Tradeoff {
  "baseline"?: number | null;
  /** Why this direction was assigned, when it came from a check status rather than from the sign of the change. */
  "basis"?: string | null;
  "candidate"?: number | null;
  "direction": "improves" | "worsens" | "unchanged" | "informational" | "unknown";
  "metric": string;
  "unit": string;
}

/** ``T_parent_from_local``: row-major 4x4 homogeneous, applied to column vectors. Translation in metres. A rigid rotation has determinant +1; reflections are rejected here so that a mirror cannot be smuggled in as a placement. */
export interface Transform {
  "matrix"?: number[][];
}

/** Move an unlocked movable component along its declared travel corridor. Preconditions (section 6): the corridor, harness allowance, and mount positions are known. CAD effect: change the instance placement only. Geometry shapes stay identical, which the export acceptance check verifies by comparing unchanged-part signatures. */
export interface TranslateComponent {
  "axis": "x" | "y" | "z";
  "delta_m": number;
  "operation"?: "translate_component";
  "target_part_id": string;
}

/** The modelled envelope inside which a movable component may be repositioned. Architecture section 6 makes this a precondition of ``translate_component``: the corridor, harness allowance, and mount positions must be known before a move is proposable. */
export interface TravelCorridor {
  "axis": "x" | "y" | "z";
  "harness_allowance_m": Claim;
  "max_m": number;
  "min_m": number;
  "mount_positions_m"?: number[];
}

/** A canted tail panel. This airframe has no conventional horizontal-plus-vertical tail. */
export interface VTailPanel {
  "area_m2": number;
  /** Longitudinal distance from the wing quarter-chord to the panel, aft-positive. */
  "arm_m": number;
  "cant_rad": number;
  "mean_chord_m": number;
  "part_id": string;
}

/** One spanwise station of the editable parameterisation (architecture section 6). */
export interface WingStation {
  "chord_m": number;
  "leading_edge_x_m": number;
  "span_y_m": number;
  "twist_rad"?: number;
  "z_m"?: number;
}

