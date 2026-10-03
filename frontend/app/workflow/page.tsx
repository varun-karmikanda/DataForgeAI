"use client";

import { Suspense, useEffect, useState, useRef, useCallback, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowUp, Download, Copy, Check, Terminal, XCircle, RotateCcw } from "lucide-react";
import { ResultsTable } from "@/components/workflow/results-table";
import { InsightsPanel } from "@/components/workflow/insights-panel";
import { SourcesPanel } from "@/components/workflow/sources-panel";
import { PipelineGraph } from "@/components/workflow/pipeline-graph";
import { LiveLogFeed } from "@/components/workflow/live-log-feed";
import { AgentStatusStrip } from "@/components/workflow/agent-status-strip";
import { GradientText } from "@/components/shared/gradient-text";
import { AnimatedCounter } from "@/components/shared/animated-counter";
import { useWorkflowStore } from "@/hooks/use-workflow-state";
import { cancelTask, connectPipelineStream, getTask } from "@/lib/api";
import { cn } from "@/lib/utils";
import { downloadCsv, recordsToCsv } from "@/lib/csv";
import type { WorkflowSpec, ResolvedWorkflowSpec, SourceExtractionResult, ValidatedResult } from "@/lib/types";

export default function WorkflowPage() {
  return (
    <Suspense>
      <WorkflowPageInner />
    </Suspense>
  );
}

function WorkflowPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const prompt = searchParams.get("prompt") || "";
  const taskId = searchParams.get("task_id") || "";
  const store = useWorkflowStore();
  const [showResults, setShowResults] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [followup, setFollowup] = useState("");
  const abortRef = useRef<(() => void) | null>(null);
  const liveTaskIdRef = useRef<string | null>(taskId || null);

  // Redirect if neither a live prompt nor a saved task_id is present
  useEffect(() => {
    if (!prompt && !taskId) {
      router.push("/");
    }
  }, [prompt, taskId, router]);

  // Reopening a saved run from History/Datasets: fetch it once, skip the live SSE pipeline.
  useEffect(() => {
    if (!taskId) return;
    useWorkflowStore.getState().reset();
    getTask(taskId)
      .then((task) => {
        const s = useWorkflowStore.getState();
        s.setPrompt(task.prompt);
        s.setSpec(task.spec);
        s.setValidatedResult(task.validated_result);
        s.setStage("complete");
        s.setProgress(100);
      })
      .catch((err) => setLoadError(err.message || "Could not load this workflow"));
  }, [taskId]);

  // Show results after pipeline completes
  useEffect(() => {
    if (store.stage === "complete") {
      setTimeout(() => setShowResults(true), 800);
    }
  }, [store.stage]);

  // SSE event handler — uses getState() to avoid stale closure issues
  const handleEvent = useCallback(
    (event: string, data: Record<string, unknown>) => {
      const s = useWorkflowStore.getState();
      switch (event) {
        case "pipeline:start":
          liveTaskIdRef.current = data.task_id as string;
          s.setTaskId(data.task_id as string);
          break;
        case "planner:start":
          s.setStage("planning");
          s.setProgress(10);
          s.addLog({ stage: "planning", agent: "Planner", message: "Generating workflow spec...", level: "info" });
          break;
        case "planner:done": {
          const spec = data.spec as WorkflowSpec;
          s.setSpec(spec);
          s.addLog({ stage: "planning", agent: "Planner", message: `Generated workflow spec with ${spec.sources.length} sources`, level: "success" });
          break;
        }
        case "discovery:start":
          s.setStage("discovering");
          s.setProgress(25);
          s.addLog({ stage: "discovering", agent: "Source Discovery", message: `Resolving ${(data.source_count as number) || 0} sources...`, level: "info" });
          break;
        case "discovery:done": {
          const resolvedSpec = data.resolved_spec as ResolvedWorkflowSpec;
          s.setResolvedSpec(resolvedSpec);
          const totalUrls = resolvedSpec.sources.reduce((acc: number, src: { resolved?: unknown[] }) => acc + (src.resolved?.length || 0), 0);
          s.addLog({ stage: "discovering", agent: "Source Discovery", message: `Resolved ${totalUrls} URLs from ${resolvedSpec.sources.length} queries`, level: "success" });
          break;
        }
        case "extraction:start":
          s.setStage("extracting");
          s.setProgress(45);
          s.addLog({ stage: "extracting", agent: "Extraction", message: `Processing ${(data.source_count as number) || 0} sources...`, level: "info" });
          break;
        case "extraction:done": {
          const results = data.extraction_results as SourceExtractionResult[];
          s.setExtractionResults(results);
          s.setRecordCount((data.total_records as number) || 0);
          for (const r of results) {
            if (r.fetch_errors.length > 0) {
              for (const err of r.fetch_errors) {
                s.addLog({ stage: "extracting", agent: "Extraction", message: `Fetch error: ${err.length > 80 ? err.slice(0, 80) + "..." : err}`, level: "warning" });
              }
            }
            if (r.records.length > 0) {
              s.addLog({ stage: "extracting", agent: "Extraction", message: `Extracted ${r.records.length} records from ${r.query_or_url}`, level: "success" });
            }
          }
          break;
        }
        case "critic:start":
          s.setStage("critiquing");
          s.setProgress(70);
          s.addLog({ stage: "critiquing", agent: "Critic", message: "Analyzing extraction quality...", level: "info" });
          break;
        case "critic:done":
          s.addLog({ stage: "critiquing", agent: "Critic", message: "Quality check passed", level: "success" });
          break;
        case "validator:start":
          s.setStage("validating");
          s.setProgress(85);
          s.addLog({ stage: "validating", agent: "Validator", message: "Validating and deduplicating records...", level: "info" });
          break;
        case "validator:done": {
          const validated = data.validated_result as ValidatedResult;
          s.setValidatedResult(validated);
          s.setRecordCount(validated.clean_records.length);
          s.addLog({ stage: "validating", agent: "Validator", message: `${validated.clean_records.length} clean records, ${validated.issues.length} issues, ${validated.merges.length} duplicates merged`, level: "success" });
          break;
        }
        case "pipeline:complete":
          s.setStage("complete");
          s.setProgress(100);
          s.addLog({ stage: "complete", agent: "Pipeline", message: "Pipeline complete!", level: "success" });
          break;
        case "pipeline:cancelled":
          s.setError("Workflow cancelled");
          s.addLog({ stage: "error", agent: "Pipeline", message: "Workflow cancelled", level: "warning" });
          break;
        case "pipeline:error":
          s.setError(data.error as string);
          s.addLog({ stage: "error", agent: "Pipeline", message: (data.error as string) || "Unknown error", level: "error" });
          break;
      }
    },
    []
  );

  const handleError = useCallback((err: Error) => {
    const s = useWorkflowStore.getState();
    s.setError(err.message);
    s.addLog({ stage: "error", agent: "Pipeline", message: err.message, level: "error" });
  }, []);

  // Connect to SSE stream on mount (skipped when reopening a saved task via task_id)
  useEffect(() => {
    if (!prompt || taskId) return;

    useWorkflowStore.getState().setPrompt(prompt);
    // Delay so React StrictMode's dev-only mount/unmount/mount only opens one connection.
    const t = setTimeout(() => {
      abortRef.current = connectPipelineStream(prompt, handleEvent, () => {}, handleError, taskId || undefined);
    }, 0);

    return () => { clearTimeout(t); abortRef.current?.(); };
  }, [prompt, taskId, retryKey, handleEvent, handleError]);

  // "missing" just means a page didn't publish that field (e.g. posted date) - not a failure.
  const allIssues = store.validatedResult?.issues ?? [];
  const emptyFieldCount = allIssues.filter((i) => i.reason === "missing").length;
  const realIssueCount = allIssues.length - emptyFieldCount;

  const isRunning = ["planning", "discovering", "extracting", "critiquing", "validating"].includes(store.stage);

  const handleCancel = async () => {
    const activeTaskId = liveTaskIdRef.current;
    if (activeTaskId) {
      try {
        await cancelTask(activeTaskId);
      } catch (err) {
        useWorkflowStore.getState().addLog({ stage: "error", agent: "Pipeline", message: err instanceof Error ? err.message : "Could not cancel workflow", level: "error" });
      }
    }
    abortRef.current?.();
    abortRef.current = null;
    const s = useWorkflowStore.getState();
    s.setError("Workflow cancelled");
    s.addLog({ stage: "error", agent: "Pipeline", message: "Workflow cancelled", level: "warning" });
  };

  const handleRetry = () => {
    abortRef.current?.();
    abortRef.current = null;
    useWorkflowStore.getState().reset();
    setShowResults(false);
    setLoadError(null);
    setRetryKey((key) => key + 1);
  };

  // Conversation thread: the first turn is the original request; every later turn is a
  // "Refine:" follow-up that was appended to the same prompt.
  const fullPrompt = prompt || store.prompt;
  const turns = fullPrompt ? fullPrompt.split("\nRefine: ") : [];

  const handleFollowup = (e: FormEvent) => {
    e.preventDefault();
    const text = followup.trim();
    if (!text || isRunning || !fullPrompt) return;
    // Same page, same thread: add the follow-up to the original prompt and re-run in place.
    const combined = `${fullPrompt}\nRefine: ${text}`;
    abortRef.current?.();
    abortRef.current = null;
    useWorkflowStore.getState().reset();
    setShowResults(false);
    setLoadError(null);
    setFollowup("");
    router.replace(`/workflow?prompt=${encodeURIComponent(combined)}`);
  };

  const handleCopyJson = () => {
    if (store.validatedResult) {
      navigator.clipboard.writeText(
        JSON.stringify(store.validatedResult.clean_records, null, 2)
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <main className="min-h-screen bg-void flex flex-col">
      {/* Top bar */}
      <motion.header
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between px-6 py-4 border-b border-border-subtle bg-void/80 backdrop-blur-xl sticky top-0 z-50"
      >
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.back()}
            aria-label="Go back"
            title="Go back"
            className="rounded-lg p-2 text-text-secondary hover:bg-elevated hover:text-cyan transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            onClick={() => router.push("/")}
            className="text-sm text-text-secondary hover:text-cyan transition-colors"
          >
            New Query
          </button>
          <div className="h-4 w-px bg-border-subtle" />
          <h1 className="text-sm font-heading font-semibold">
            <GradientText>DataForge</GradientText>{" "}
            <span className="text-text-primary">Pipeline</span>
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {isRunning && (
            <button
              onClick={handleCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-rose border border-rose/20 hover:bg-rose/10 transition-all"
            >
              <XCircle className="h-3.5 w-3.5" />
              Stop
            </button>
          )}
          {store.stage === "error" && prompt && !taskId && (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-amber border border-amber/20 hover:bg-amber/10 transition-all"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Retry
            </button>
          )}
          {store.stage === "complete" && (
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex items-center gap-3"
            >
              <button
                onClick={handleCopyJson}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-elevated border border-border-subtle hover:border-cyan/30 transition-all"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? "Copied!" : "Copy JSON"}
              </button>
              <button
                onClick={() => downloadCsv(recordsToCsv(store.validatedResult?.clean_records || []), "dataforge-results.csv")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-cyan/10 border border-cyan/20 text-cyan hover:bg-cyan/20 transition-all"
              >
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </button>
            </motion.div>
          )}
        </div>
      </motion.header>

      {/* Conversation thread */}
      {turns.length > 0 && (
        <div className="px-6 flex flex-col gap-2 items-end">
          {turns.map((turn, i) => (
            <div
              key={i}
              className="max-w-2xl rounded-2xl rounded-br-sm border border-border-subtle bg-elevated px-4 py-2 text-sm text-text-primary"
            >
              {i > 0 && (
                <span className="mr-2 text-[10px] font-mono uppercase tracking-wider text-cyan">refine</span>
              )}
              {turn}
            </div>
          ))}
        </div>
      )}

      {/* Agent status strip + pipeline graph — only while the run is in progress */}
      <AnimatePresence>
        {store.stage !== "complete" && (
          <motion.div
            key="pipeline-in-progress"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.4 }}
            className="overflow-hidden"
          >
            <div className="px-6 py-3">
              <AgentStatusStrip />
            </div>
            <div className="flex flex-col gap-4 px-6 pb-6">
              {loadError && (
                <div className="text-sm text-rose bg-rose/10 border border-rose/20 rounded-lg px-4 py-3">
                  Couldn&apos;t load this workflow: {loadError}
                </div>
              )}
              <motion.div
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.5 }}
                className="h-[420px]"
              >
                <PipelineGraph />
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stat cards — shown once the pipeline completes */}
      <div className="px-6">
        <AnimatePresence>
          {store.stage === "complete" && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              className="grid grid-cols-4 gap-3 max-w-xl pb-6"
            >
              <StatCard label="Records" value={store.validatedResult?.clean_records.length || 0} color="cyan" />
              <StatCard label="Real issues" value={realIssueCount} color="amber" />
              <StatCard label="Empty fields" value={emptyFieldCount} color="slate" />
              <StatCard label="Duplicates merged" value={store.validatedResult?.merges.length || 0} color="violet" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {/* Results preview overlay */}
      <AnimatePresence>
        {showResults && store.validatedResult && (
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 40 }}
            className="px-6 pb-8"
          >
            <div className="rounded-2xl border border-border-subtle bg-card-solid/80 backdrop-blur-sm p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-heading font-semibold">
                  <GradientText>Extracted Records</GradientText>
                </h2>
                <span className="text-xs font-mono text-text-muted">
                  Showing all{" "}
                  {store.validatedResult.clean_records.length}
                </span>
              </div>

              <InsightsPanel records={store.validatedResult.clean_records} />
              <ResultsTable records={store.validatedResult.clean_records} />
              <SourcesPanel />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {/* Follow-up box: refine the same search instead of starting a new task */}
      {(store.stage === "complete" || store.stage === "error") && (
        <form
          onSubmit={handleFollowup}
          className="sticky bottom-0 z-40 mt-auto bg-gradient-to-t from-void via-void/95 to-transparent px-6 pb-4 pt-6 pr-36"
        >
          <div className="flex items-center gap-2 rounded-2xl border border-border-subtle bg-elevated px-4 py-2 focus-within:border-cyan/40">
            <input
              value={followup}
              onChange={(e) => setFollowup(e.target.value)}
              placeholder="Refine this search, e.g. only in Bangalore, 0-1 years experience..."
              maxLength={500}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
            />
            <button
              type="submit"
              disabled={!followup.trim()}
              aria-label="Send follow-up"
              className="rounded-full bg-cyan/10 p-2 text-cyan transition-colors hover:bg-cyan/20 disabled:opacity-40"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </div>
        </form>
      )}

      {/* Log popup */}
      <button
        onClick={() => setShowLogs((v) => !v)}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-full text-xs font-mono bg-elevated border border-border-subtle hover:border-cyan/30 transition-all"
      >
        <Terminal className="h-3.5 w-3.5" />
        Logs ({store.logs.length})
      </button>
      <AnimatePresence>
        {showLogs && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="fixed bottom-16 right-4 z-50 w-[380px] max-w-[calc(100vw-2rem)] h-[420px]"
          >
            <LiveLogFeed />
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: "cyan" | "amber" | "violet" | "slate";
}) {
  const colors = {
    cyan: "border-cyan/20 text-cyan",
    amber: "border-amber/20 text-amber",
    violet: "border-violet/20 text-violet",
    slate: "border-border-subtle text-text-secondary",
  };

  return (
    <div
      className={cn(
        "rounded-xl border bg-elevated/50 p-3 text-center",
        colors[color].split(" ")[0]
      )}
    >
      <AnimatedCounter
        value={value}
        className={cn("text-xl font-bold", colors[color].split(" ")[1])}
      />
      <p className="text-[10px] font-mono text-text-muted mt-1 uppercase tracking-wider">
        {label}
      </p>
    </div>
  );
}