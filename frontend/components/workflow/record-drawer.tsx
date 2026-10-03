"use client";

import { ExternalLink, X } from "lucide-react";
import type { ExtractedRecord } from "@/lib/types";

export function RecordDrawer({
  record,
  score,
  onClose,
}: {
  record: ExtractedRecord | null;
  score: number;
  onClose: () => void;
}) {
  if (!record) return null;
  const entries = Object.entries(record.data);
  const filled = entries.filter(([, v]) => v).length;
  const verified = record.match_status === "match";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <aside
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-md h-full overflow-y-auto bg-card-solid border-l border-border-subtle p-6 flex flex-col gap-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-text-muted">Record details</p>
            <p className="text-2xl font-bold text-cyan mt-1">{score}%</p>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">
            <X className="h-5 w-5" />
          </button>
        </div>

        <section>
          <p className="text-[10px] font-mono uppercase tracking-wider text-text-muted mb-2">Fields</p>
          <div className="flex flex-col gap-2">
            {entries.map(([k, v]) => (
              <div key={k} className="rounded-lg bg-elevated/50 border border-border-subtle px-3 py-2">
                <p className="text-[10px] font-mono uppercase text-text-muted">{k.replace(/_/g, " ")}</p>
                <p className="text-sm text-text-primary break-words">{v || "—"}</p>
              </div>
            ))}
          </div>
        </section>

        <section>
          <p className="text-[10px] font-mono uppercase tracking-wider text-text-muted mb-2">Source evidence</p>
          {record.citation_snippet ? (
            <blockquote className="text-xs text-text-secondary border-l-2 border-cyan/40 pl-3 italic whitespace-pre-wrap">
              {record.citation_snippet}
            </blockquote>
          ) : (
            <p className="text-xs text-text-muted">No quote captured.</p>
          )}
          {record.citation_url && (
            <a
              href={record.citation_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 text-xs text-cyan hover:underline break-all"
            >
              <ExternalLink className="h-3 w-3 shrink-0" />
              {record.citation_url}
            </a>
          )}
        </section>

        <section>
          <p className="text-[10px] font-mono uppercase tracking-wider text-text-muted mb-2">Score breakdown</p>
          <ul className="text-xs text-text-secondary flex flex-col gap-1">
            <li>Fields filled: {filled} of {entries.length}</li>
            <li>Checked against your request: {verified ? "yes" : "not confirmed"}</li>
            <li>Source quote captured: {record.citation_snippet ? "yes" : "no"}</li>
            <li>Warnings: {record.flags?.length ?? 0}</li>
          </ul>
          {!verified && record.match_reason && (
            <p className="mt-2 text-xs text-amber">{record.match_reason}</p>
          )}
          {record.flags && record.flags.length > 0 && (
            <ul className="mt-2 text-xs text-rose list-disc pl-4">
              {record.flags.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}