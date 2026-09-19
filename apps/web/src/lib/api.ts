/**
 * The typed API client. One place that knows about HTTP.
 *
 * Every failure comes back as the shared error envelope, so the UI can key off `code` rather than
 * parsing messages. A `CONSTRAINT_FAILED` is a design result, not a crash, and the panels render
 * it as such.
 */

import type {
  AuditEvent,
  CadEditResult,
  DecisionOutcome,
  DecisionRequest,
  ErrorEnvelope,
  Evaluation,
  EvidenceGraph,
  ExplanationPath,
  GeometryFeatures,
  JobRecord,
  Neighborhood,
  PartsDocument,
  Recommendation,
  RecommendationSet,
  Revision,
  RevisionManifest,
  SimulationRun,
} from "@/lib/contracts.gen";

export class ApiError extends Error {
  readonly envelope: ErrorEnvelope;
  readonly status: number;

  constructor(envelope: ErrorEnvelope, status: number) {
    super(`${envelope.code}: ${envelope.message}`);
    this.name = "ApiError";
    this.envelope = envelope;
    this.status = status;
  }

  /** True when the design failed a check, as opposed to the request or the server failing. */
  get isDesignResult(): boolean {
    return (
      this.envelope.code === "CONSTRAINT_FAILED" || this.envelope.code === "MISSING_EVIDENCE"
    );
  }

  /** True when the world moved underneath the user and the view needs regenerating. */
  get isStale(): boolean {
    return this.envelope.code === "STALE_REVISION" || this.envelope.code === "CONFLICT";
  }
}

/** An envelope for a failure that never reached the service layer. Same shape, so the UI has
 *  exactly one error type to handle. */
export function localEnvelope(message: string): ErrorEnvelope {
  return { code: "INTERNAL", message, revision_id: null, details: {}, retryable: false };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    let envelope: ErrorEnvelope;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      envelope = localEnvelope(`${response.status} ${response.statusText}`);
    }
    throw new ApiError(envelope, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface DesignSummary {
  design_id: string;
  display_name: string;
  active_revision_id: string | null;
  mission_hash: string | null;
  created_at: string;
}

export interface PartsResponse {
  parts: PartsDocument;
  geometry_features: GeometryFeatures;
  capabilities: Record<string, string[]>;
  unknown_claims: Record<string, string[]>;
}

export interface HistoryResponse {
  design_id: string;
  active_revision_id: string;
  revisions: Revision[];
}

export interface DoctorReport {
  contract_version: string;
  storage_root: string;
  designs: number;
  ports: {
    cad: { owner: string; real_kernel: boolean };
    evaluate: { owner: string; available_tiers: string[] };
    simulate: { owner: string };
  };
  provider: string;
  catalog: { snapshot_id: string; items: number; all_synthetic: boolean };
  capabilities_absent: string[];
}

export interface ComparisonResponse {
  metric: string;
  baseline_revision_id: string;
  candidate_revision_id: string;
  delta: number | null;
  feasibility_changed: boolean;
  fidelity: string;
  ui_claim: string;
  baseline: Evaluation;
  candidate: Evaluation;
}

export interface ClaimEntryInput {
  part_id: string;
  quantity?: string;
  value: number;
  unit: string;
  source_kind: "bom" | "manual" | "catalog" | "cad";
  evidence_id: string;
  note?: string;
}

export const api = {
  health: () => get<{ status: string; contract_version: string }>("/api/health"),
  doctor: () => get<DoctorReport>("/api/doctor"),

  listDesigns: () => get<{ designs: DesignSummary[] }>("/api/designs"),
  importFixture: (fixture = "b") =>
    post<{ job_id: string; job: JobRecord }>("/api/designs/import", { fixture }),
  job: (jobId: string) => get<JobRecord & { artifact_links: string[] }>(`/api/jobs/${jobId}`),

  confirm: (
    designId: string,
    body: {
      units_confirmed: boolean;
      frame_confirmed: boolean;
      reconstruction_confirmed: boolean;
      variant_decisions?: Record<string, string>;
      claim_entries?: ClaimEntryInput[];
    },
  ) => post<RevisionManifest>(`/api/designs/${designId}/confirm`, body),

  history: (designId: string) => get<HistoryResponse>(`/api/designs/${designId}/history`),
  undo: (designId: string, toRevisionId?: string) =>
    post<{ design_id: string; active_revision_id: string }>(
      `/api/designs/${designId}/undo${toRevisionId ? `?to_revision_id=${toRevisionId}` : ""}`,
    ),

  revision: (revisionId: string) => get<RevisionManifest>(`/api/revisions/${revisionId}`),
  parts: (revisionId: string) => get<PartsResponse>(`/api/revisions/${revisionId}/parts`),
  graph: (revisionId: string) => get<EvidenceGraph>(`/api/revisions/${revisionId}/graph`),
  neighborhood: (revisionId: string, partId: string, radius = 2) =>
    get<Neighborhood>(
      `/api/revisions/${revisionId}/graph?part_id=${partId}&radius=${radius}`,
    ),
  explain: (revisionId: string, partId: string, question: string) =>
    get<ExplanationPath | FittingAlternatives>(
      `/api/revisions/${revisionId}/explain?part_id=${partId}&question=${question}`,
    ),

  evaluate: (revisionId: string, fidelity = "analytic") =>
    post<{ job_id: string; job: JobRecord; evaluation: Evaluation }>(
      `/api/revisions/${revisionId}/evaluate`,
      { fidelity },
    ),

  recommend: (revisionId: string, preview = true) =>
    post<RecommendationSet>(`/api/revisions/${revisionId}/recommendations`, { preview }),
  listRecommendations: (revisionId: string) =>
    get<{ proposals: Recommendation[] }>(`/api/revisions/${revisionId}/recommendations`),
  preview: (proposalId: string) =>
    post<Recommendation>(`/api/recommendations/${proposalId}/preview`),
  decide: (proposalId: string, body: DecisionRequest) =>
    post<DecisionOutcome>(`/api/recommendations/${proposalId}/decision`, body),

  simulate: (revisionId: string) =>
    post<{ job_id: string; job: JobRecord; run: SimulationRun }>(
      `/api/revisions/${revisionId}/simulate`,
    ),
  compare: (candidateRevisionId: string, againstRevisionId: string, metric = "endurance_min") =>
    get<ComparisonResponse>(
      `/api/revisions/${candidateRevisionId}/compare?against=${againstRevisionId}&metric=${metric}`,
    ),
  exportStep: (revisionId: string) => post<CadEditResult>(`/api/revisions/${revisionId}/export`),

  recentEvents: (designId: string, after = 0) =>
    get<{ design_id: string; last_sequence: number; events: AuditEvent[] }>(
      `/api/events/recent?design_id=${designId}&after=${after}`,
    ),

  /** Server-resolved download. The UI never constructs a filesystem path. */
  artifactUrl: (artifactId: string) => `/api/artifacts/${artifactId}`,
};

export interface FittingAlternative {
  catalog_item_id: string;
  display_name: string;
  fits: boolean;
  reasons: string[];
  mass_kg: number | null;
  synthetic: boolean;
}

export interface FittingAlternatives {
  part_id: string;
  category: string | null;
  results: FittingAlternative[];
  note: string;
}

export function isFittingAlternatives(
  value: ExplanationPath | FittingAlternatives,
): value is FittingAlternatives {
  return "results" in value;
}

/**
 * Subscribe to the audit stream.
 *
 * Reconnect resumes from the last sequence seen, which is what `Last-Event-ID` is for. Progress
 * arrives as structured tool events; there is no percentage to interpolate and the UI does not
 * invent one.
 */
export function subscribeEvents(
  designId: string,
  onEvent: (event: AuditEvent) => void,
  afterSequence = 0,
): () => void {
  const source = new EventSource(`/api/events?design_id=${designId}&after=${afterSequence}`);
  const handler = (message: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(message.data) as AuditEvent);
    } catch {
      /* a malformed frame is dropped rather than tearing down the stream */
    }
  };
  // Every event kind arrives under its own name, so listen broadly.
  source.onmessage = handler;
  for (const kind of [
    "job_queued",
    "job_started",
    "job_progress",
    "job_succeeded",
    "job_failed",
    "job_cancelled",
    "revision_created",
    "revision_activated",
    "proposal_generated",
    "proposal_previewed",
    "proposal_declined",
    "proposal_committed",
    "proposal_stale",
    "evaluation_completed",
    "export_completed",
  ]) {
    source.addEventListener(kind, handler as EventListener);
  }
  return () => source.close();
}
