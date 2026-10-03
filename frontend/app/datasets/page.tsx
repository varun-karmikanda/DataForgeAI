"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Database, Download, Loader2, ExternalLink } from "lucide-react";
import { listTasks, getTask } from "@/lib/api";
import { recordsToCsv, downloadCsv } from "@/lib/csv";
import type { TaskSummary } from "@/lib/types";

function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function DatasetsPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);

  useEffect(() => {
    listTasks()
      .then((all) => setTasks(all.filter((t) => t.record_count > 0)))
      .catch((err) => setError(err.message || "Failed to load datasets"));
  }, []);

  const handleExport = async (task: TaskSummary) => {
    setExportingId(task.task_id);
    try {
      const detail = await getTask(task.task_id);
      const csv = recordsToCsv(detail.validated_result.clean_records);
      const safePrompt = task.prompt.slice(0, 40).replace(/[^a-z0-9]+/gi, "-");
      downloadCsv(csv, `dataforge-${safePrompt}-${task.task_id.slice(0, 8)}.csv`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExportingId(null);
    }
  };

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="flex items-center gap-2 mb-2">
        <Database className="h-5 w-5 text-violet" />
        <h1 className="font-heading text-xl font-semibold text-text-primary">
          Datasets
        </h1>
      </div>
      <p className="text-sm text-text-muted mb-6">
        Every completed collection with data, ready to inspect or export.
      </p>

      {error && (
        <div className="text-sm text-rose bg-rose/10 border border-rose/20 rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {!tasks && !error && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-12 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading datasets...
        </div>
      )}

      {tasks && tasks.length === 0 && (
        <div className="text-center text-text-muted text-sm py-16 border border-dashed border-border-subtle rounded-xl">
          No datasets yet — a workflow needs to finish with at least one record.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {tasks?.map((task) => (
          <div
            key={task.task_id}
            className="flex items-center justify-between gap-4 px-4 py-3 rounded-xl bg-card border border-border-subtle"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm text-text-primary truncate">{task.prompt}</p>
              <p className="text-xs text-text-muted font-mono mt-1">
                {formatDate(task.created_at)} · {task.record_count}{" "}
                {task.record_count === 1 ? "record" : "records"}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => router.push(`/workflow?task_id=${task.task_id}`)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-text-secondary border border-border-subtle hover:border-cyan/30 hover:text-cyan transition-all"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                View
              </button>
              <button
                onClick={async () => {
                  const detail = await getTask(task.task_id);
                  const blob = new Blob([JSON.stringify(detail.validated_result.clean_records, null, 2)], { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `dataforge-${task.task_id.slice(0, 8)}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-text-secondary border border-border-subtle hover:border-cyan/30 hover:text-cyan transition-all"
              >
                <Download className="h-3.5 w-3.5" />
                JSON
              </button>
              <button
                onClick={() => handleExport(task)}
                disabled={exportingId === task.task_id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-cyan/10 border border-cyan/20 text-cyan hover:bg-cyan/20 transition-all disabled:opacity-50"
              >
                {exportingId === task.task_id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Export CSV
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}