"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { useWorkflowStore } from "@/hooks/use-workflow-state";

export function SourcesPanel() {
  const resolved = useWorkflowStore((s) => s.resolvedSpec);
  const results = useWorkflowStore((s) => s.extractionResults);
  const [open, setOpen] = useState(false);

  if (!resolved || resolved.sources.length === 0) return null;

  const totalUrls = resolved.sources.reduce((a, s) => a + s.resolved.length, 0);

  return (
    <div className="mt-6 rounded-xl border border-border-subtle bg-elevated/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-text-primary"
      >
        <span className="inline-flex items-center gap-2 font-heading font-semibold">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Sources inspected
        </span>
        <span className="text-xs font-mono text-text-muted">
          {resolved.sources.length} queries · {totalUrls} pages
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 flex flex-col gap-4">
          {resolved.sources.map((src, i) => {
            const result = results[i];
            return (
              <div key={i}>
                <p className="text-xs font-mono text-cyan mb-1">
                  [{src.type}] {src.query_or_url}
                </p>
                <div className="flex flex-col gap-1">
                  {src.resolved.map((r) => {
                    const count = result?.records.filter((rec) => rec.source_url === r.url).length ?? 0;
                    const error = result?.fetch_errors.find((e) => e.startsWith(r.url));
                    return (
                      <div
                        key={r.url}
                        className="flex items-center justify-between gap-3 rounded-lg px-3 py-1.5 bg-card/60 border border-border-subtle/60"
                      >
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1.5 min-w-0 text-xs text-text-secondary hover:text-cyan"
                        >
                          <ExternalLink className="h-3 w-3 shrink-0" />
                          <span className="truncate">{r.url}</span>
                        </a>
                        <span className="shrink-0 text-[10px] font-mono">
                          {error ? (
                            <span className="inline-flex items-center gap-1 text-amber" title={error}>
                              <AlertTriangle className="h-3 w-3" />
                              {error.includes("robots") ? "robots.txt" : "failed"}
                            </span>
                          ) : (
                            <span className={count > 0 ? "text-emerald" : "text-text-muted"}>
                              {count} {count === 1 ? "record" : "records"}
                            </span>
                          )}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}