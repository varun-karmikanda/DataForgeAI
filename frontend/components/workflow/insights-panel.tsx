"use client";

import { useMemo } from "react";
import type { ExtractedRecord } from "@/lib/types";

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "unknown";
  }
}

type Row = { label: string; value: number; max: number };

function Bars({ title, rows, suffix = "" }: { title: string; rows: Row[]; suffix?: string }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-elevated/40 p-4">
      <p className="text-[10px] font-mono uppercase tracking-wider text-text-muted mb-3">{title}</p>
      <div className="flex flex-col gap-2">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex justify-between text-xs text-text-secondary mb-1">
              <span className="truncate pr-2">{r.label}</span>
              <span className="font-mono">
                {r.value}
                {suffix}
              </span>
            </div>
            <div className="h-1.5 rounded bg-card-solid">
              <div
                className="h-1.5 rounded bg-cyan"
                style={{ width: `${r.max ? (r.value / r.max) * 100 : 0}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function InsightsPanel({ records }: { records: ExtractedRecord[] }) {
  const stats = useMemo(() => {
    const cols: string[] = [];
    for (const r of records) for (const k of Object.keys(r.data)) if (!cols.includes(k)) cols.push(k);

    const completeness: Row[] = cols.map((c) => ({
      label: c.replace(/_/g, " "),
      value: Math.round((records.filter((r) => r.data[c]).length / records.length) * 100),
      max: 100,
    }));

    const srcCounts: Record<string, number> = {};
    for (const r of records) {
      const h = hostOf(r.citation_url || r.source_url);
      srcCounts[h] = (srcCounts[h] || 0) + 1;
    }
    const srcSorted = Object.entries(srcCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const bySource: Row[] = srcSorted.map(([label, value]) => ({ label, value, max: srcSorted[0][1] }));

    const catKey = cols.find((c) => /city|state|location|country|category|type|industry|sector/i.test(c));
    let topValues: Row[] = [];
    if (catKey) {
      const counts: Record<string, { label: string; n: number }> = {};
      for (const r of records) {
        const v = (r.data[catKey] || "").trim();
        if (!v) continue;
        const k = v.toLowerCase();
        counts[k] = { label: counts[k]?.label ?? v, n: (counts[k]?.n ?? 0) + 1 };
      }
      const sorted = Object.values(counts).sort((a, b) => b.n - a.n).slice(0, 5);
      topValues = sorted.map((s) => ({ label: s.label, value: s.n, max: sorted[0].n }));
    }
    return { completeness, bySource, topValues, catKey };
  }, [records]);

  if (records.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
      <Bars title="Column completeness" rows={stats.completeness} suffix="%" />
      <Bars title="Records per source" rows={stats.bySource} />
      {stats.topValues.length > 0 && (
        <Bars title={`Top ${(stats.catKey || "").replace(/_/g, " ")}`} rows={stats.topValues} />
      )}
    </div>
  );
}