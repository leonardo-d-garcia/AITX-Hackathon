/**
 * The one shared store (architecture section 11).
 *
 * "Feature components consume a shared `revision_id`, selected `part_id`, artifact resolver and
 * event interface; they do not own separate revision stores."
 *
 * That is why this file exists and why it is the only place revision state lives. A `features/cad`
 * or `features/simulation` panel that kept its own idea of the current revision would eventually
 * render one revision's geometry next to another revision's numbers, which is precisely the
 * traceability failure the product exists to prevent.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type {
  AuditEvent,
  Evaluation,
  RecommendationSet,
  Revision,
} from "@/lib/contracts.gen";
import {
  ApiError,
  api,
  localEnvelope,
  subscribeEvents,
  type DoctorReport,
  type PartsResponse,
} from "@/lib/api";

export type Mode = "inspect" | "improve" | "simulate";

export interface WorkbenchState {
  /** The design being worked on, or null before an import. */
  designId: string | null;
  /** The active revision. Every panel renders this and nothing else. */
  revisionId: string | null;
  /** The occurrence the user selected. Selection is synchronised across all panels. */
  selectedPartId: string | null;
  mode: Mode;

  parts: PartsResponse | null;
  evaluation: Evaluation | null;
  recommendations: RecommendationSet | null;
  history: Revision[];
  events: AuditEvent[];
  doctor: DoctorReport | null;

  busy: string | null;
  error: ApiError | null;
}

export interface WorkbenchActions {
  setMode: (mode: Mode) => void;
  selectPart: (partId: string | null) => void;
  importFixture: () => Promise<void>;
  confirmDesign: (options: {
    reconstruction: boolean;
    claims: { part_id: string; value: number; unit: string; evidence_id: string }[];
  }) => Promise<void>;
  refresh: () => Promise<void>;
  evaluate: () => Promise<void>;
  recommend: () => Promise<void>;
  decide: (
    proposalId: string,
    decision: "accept" | "decline",
    previewHash?: string,
    reason?: string,
  ) => Promise<void>;
  undo: () => Promise<void>;
  clearError: () => void;
  artifactUrl: (artifactId: string) => string;
}

const WorkbenchContext = createContext<(WorkbenchState & WorkbenchActions) | null>(null);

/** How many events the timeline keeps in memory. The full log stays on the server. */
const EVENT_WINDOW = 200;

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [designId, setDesignId] = useState<string | null>(null);
  const [revisionId, setRevisionId] = useState<string | null>(null);
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("inspect");

  const [parts, setParts] = useState<PartsResponse | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationSet | null>(null);
  const [history, setHistory] = useState<Revision[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const lastSequence = useRef(0);

  const run = useCallback(
    async <T,>(label: string, work: () => Promise<T>): Promise<T | undefined> => {
      setBusy(label);
      setError(null);
      try {
        return await work();
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught);
        } else {
          setError(
            new ApiError(
              localEnvelope(caught instanceof Error ? caught.message : String(caught)),
              0,
            ),
          );
        }
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  /** Reload everything that describes the active revision, in one place. */
  const loadRevision = useCallback(async (design: string) => {
    const historyResponse = await api.history(design);
    const active = historyResponse.active_revision_id;
    setHistory(historyResponse.revisions);
    setRevisionId(active);

    const partsResponse = await api.parts(active);
    setParts(partsResponse);

    // An evaluation may not exist yet; that is not an error, it is a state the UI shows.
    try {
      const evaluated = await api.evaluate(active);
      setEvaluation(evaluated.evaluation);
    } catch (caught) {
      if (caught instanceof ApiError && caught.isDesignResult) {
        setEvaluation(null);
      } else {
        throw caught;
      }
    }
    setRecommendations(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!designId) return;
    await run("refreshing", () => loadRevision(designId));
  }, [designId, loadRevision, run]);

  const importFixture = useCallback(async () => {
    await run("importing", async () => {
      const started = await api.importFixture("b");
      // Long work returns a job; poll it rather than guessing a duration.
      for (let attempt = 0; attempt < 200; attempt += 1) {
        const job = await api.job(started.job_id);
        if (job.status === "succeeded") break;
        if (job.status === "failed" || job.status === "cancelled") {
          throw new ApiError(localEnvelope(job.error_message ?? `import ${job.status}`), 500);
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      const designs = await api.listDesigns();
      const first = designs.designs[0];
      if (!first) throw new Error("the import produced no design");
      setDesignId(first.design_id);
      await loadRevision(first.design_id);
    });
  }, [loadRevision, run]);

  const confirmDesign = useCallback<WorkbenchActions["confirmDesign"]>(
    async ({ reconstruction, claims }) => {
      if (!designId) return;
      await run("confirming", async () => {
        await api.confirm(designId, {
          units_confirmed: true,
          frame_confirmed: true,
          reconstruction_confirmed: reconstruction,
          claim_entries: claims.map((claim) => ({
            part_id: claim.part_id,
            quantity: "mass_kg",
            value: claim.value,
            unit: claim.unit,
            source_kind: "manual",
            evidence_id: claim.evidence_id,
          })),
        });
        await loadRevision(designId);
      });
    },
    [designId, loadRevision, run],
  );

  const evaluate = useCallback(async () => {
    if (!revisionId) return;
    await run("evaluating", async () => {
      const result = await api.evaluate(revisionId);
      setEvaluation(result.evaluation);
    });
  }, [revisionId, run]);

  const recommend = useCallback(async () => {
    if (!revisionId) return;
    await run("generating and previewing proposals", async () => {
      setRecommendations(await api.recommend(revisionId, true));
    });
  }, [revisionId, run]);

  const decide = useCallback<WorkbenchActions["decide"]>(
    async (proposalId, decision, previewHash, reason) => {
      if (!designId || !revisionId) return;
      await run(decision === "accept" ? "committing" : "recording the decision", async () => {
        await api.decide(proposalId, {
          proposal_id: proposalId,
          decision,
          expected_active_revision_id: revisionId,
          preview_hash: decision === "accept" ? (previewHash ?? null) : null,
          // One key per decision, so a double-click cannot commit twice.
          idempotency_key: `${proposalId}:${decision}:${revisionId}`,
          reason: reason ?? null,
        });
        await loadRevision(designId);
      });
    },
    [designId, revisionId, loadRevision, run],
  );

  const undo = useCallback(async () => {
    if (!designId) return;
    await run("undoing", async () => {
      await api.undo(designId);
      await loadRevision(designId);
    });
  }, [designId, loadRevision, run]);

  // -- startup and the event stream --------------------------------------------------------

  useEffect(() => {
    void api
      .doctor()
      .then(setDoctor)
      .catch(() => setDoctor(null));
    void api
      .listDesigns()
      .then(async (response) => {
        const first = response.designs[0];
        if (first?.active_revision_id) {
          setDesignId(first.design_id);
          await loadRevision(first.design_id);
        }
      })
      .catch(() => undefined);
  }, [loadRevision]);

  useEffect(() => {
    if (!designId) return undefined;
    void api.recentEvents(designId).then((response) => {
      setEvents(response.events.slice(-EVENT_WINDOW));
      lastSequence.current = response.last_sequence;
    });
    return subscribeEvents(
      designId,
      (event) => {
        lastSequence.current = Math.max(lastSequence.current, event.sequence);
        setEvents((previous) => [...previous, event].slice(-EVENT_WINDOW));
      },
      lastSequence.current,
    );
  }, [designId]);

  const value = useMemo(
    () => ({
      designId,
      revisionId,
      selectedPartId,
      mode,
      parts,
      evaluation,
      recommendations,
      history,
      events,
      doctor,
      busy,
      error,
      setMode,
      selectPart: setSelectedPartId,
      importFixture,
      confirmDesign,
      refresh,
      evaluate,
      recommend,
      decide,
      undo,
      clearError: () => setError(null),
      artifactUrl: api.artifactUrl,
    }),
    [
      designId,
      revisionId,
      selectedPartId,
      mode,
      parts,
      evaluation,
      recommendations,
      history,
      events,
      doctor,
      busy,
      error,
      importFixture,
      confirmDesign,
      refresh,
      evaluate,
      recommend,
      decide,
      undo,
    ],
  );

  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

export function useWorkbench() {
  const value = useContext(WorkbenchContext);
  if (!value) throw new Error("useWorkbench must be used inside a WorkbenchProvider");
  return value;
}
