"use client";

import { useMemo, useState } from "react";
import {
  ExternalLink,
  ShieldCheck,
  ShieldQuestion,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import type { ExtractedRecord } from "@/lib/types";
import { RecordDrawer } from "./record-drawer";

function confidenceOf(r: ExtractedRecord): number {
  const vals = Object.values(r.data);
  const fill = vals.length ? vals.filter(Boolean).length / vals.length : 0;
  const match = r.match_status === "match" ? 1 : 0;
  const cite = r.citation_snippet ? 1 : 0;
  const flags = Math.min(r.flags?.length ?? 0, 3);
  const score = 0.5 * fill + 0.4 * match + 0.1 * cite - 0.1 * flags;
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

function isUrlValue(value: string | null): value is string {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "View link";
  }
}

export function ResultsTable({ records }: { records: ExtractedRecord[] }) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [statusFilter, setStatusFilter] = useState<"all" | "match" | "unconfirmed">("all");
  const [hasEmailOnly, setHasEmailOnly] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [selected, setSelected] = useState<ExtractedRecord | null>(null);

  const columns = useMemo(() => {
    const cols: string[] = [];
    for (const r of records) {
      for (const key of Object.keys(r.data)) {
        if (!cols.includes(key)) cols.push(key);
      }
    }
    return cols;
  }, [records]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = records;
    if (statusFilter !== "all") rows = rows.filter((r) => r.match_status === statusFilter);
    if (hasEmailOnly) {
      rows = rows.filter((r) =>
        Object.entries(r.data).some(([k, v]) => k.toLowerCase().includes("email") && v)
      );
    }
    if (minScore > 0) rows = rows.filter((r) => confidenceOf(r) >= minScore);
    if (q) {
      rows = rows.filter((r) => {
        const haystack = [...Object.values(r.data), r.citation_url, r.match_reason]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      });
    }
    if (sortKey) {
      rows = [...rows].sort((a, b) => {
        const av = (a.data[sortKey] || "").toLowerCase();
        const bv = (b.data[sortKey] || "").toLowerCase();
        const cmp = av.localeCompare(bv);
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
    return rows;
  }, [records, search, sortKey, sortDir, statusFilter, hasEmailOnly, minScore]);

  const toggleSort = (col: string) => {
    if (sortKey === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col);
      setSortDir("asc");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <RecordDrawer
        record={selected}
        score={selected ? confidenceOf(selected) : 0}
        onClose={() => setSelected(null)}
      />
      <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "all" | "match" | "unconfirmed")}
          className="rounded-lg bg-elevated border border-border-subtle px-2 py-1.5 text-text-primary"
        >
          <option value="all">All status</option>
          <option value="match">Verified</option>
          <option value="unconfirmed">Unconfirmed</option>
        </select>
        <select
          value={minScore}
          onChange={(e) => setMinScore(Number(e.target.value))}
          className="rounded-lg bg-elevated border border-border-subtle px-2 py-1.5 text-text-primary"
        >
          <option value={0}>Any score</option>
          <option value={40}>Score 40%+</option>
          <option value={60}>Score 60%+</option>
          <option value={80}>Score 80%+</option>
        </select>
        <label className="flex items-center gap-1.5 text-text-secondary cursor-pointer">
          <input type="checkbox" checked={hasEmailOnly} onChange={(e) => setHasEmailOnly(e.target.checked)} />
          Has email
        </label>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-muted" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search records..."
          className="w-full pl-8 pr-3 py-1.5 rounded-lg text-xs font-mono bg-elevated border border-border-subtle text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyan/40"
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-border-subtle">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border-subtle bg-elevated/60">
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-text-muted">
                {/* match status */}
              </th>
              {columns.map((col) => (
                <th
                  key={col}
                  onClick={() => toggleSort(col)}
                  className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-text-muted cursor-pointer hover:text-cyan transition-colors select-none whitespace-nowrap"
                >
                  <span className="inline-flex items-center gap-1">
                    {col.replace(/_/g, " ")}
                    {sortKey === col ? (
                      sortDir === "asc" ? (
                        <ArrowUp className="h-3 w-3" />
                      ) : (
                        <ArrowDown className="h-3 w-3" />
                      )
                    ) : (
                      <ArrowUpDown className="h-3 w-3 opacity-30" />
                    )}
                  </span>
                </th>
              ))}
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-text-muted">
                Score
              </th>
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-text-muted">
                Source
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((record, i) => (
              <tr
                key={i}
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest("a")) return;
                  setSelected(record);
                }}
                className="border-b border-border-subtle/50 last:border-0 hover:bg-elevated/40 transition-colors cursor-pointer"
              >
                <td className="px-3 py-2">
                  {record.match_status && (
                    <span
                      title={
                        (record.match_status === "unconfirmed"
                          ? record.match_reason || "Could not be fully confirmed against the source"
                          : "Every field verified against its source") +
                        (record.flags && record.flags.length > 0 ? "\n\nNotes:\n" + record.flags.join("\n") : "")
                      }
                      className="cursor-help"
                    >
                      {record.match_status === "unconfirmed" ? (
                        <span className="inline-flex items-center gap-1 rounded border border-amber/30 bg-amber/10 px-1.5 py-0.5 text-[10px] font-mono text-amber whitespace-nowrap">
                          <ShieldQuestion className="h-3 w-3" />
                          Unconfirmed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded border border-emerald/30 bg-emerald/10 px-1.5 py-0.5 text-[10px] font-mono text-emerald whitespace-nowrap">
                          <ShieldCheck className="h-3 w-3" />
                          Verified
                        </span>
                      )}
                    </span>
                  )}
                </td>
                {columns.map((col) => {
                  const value = record.data[col];
                  return (
                    <td key={col} className="px-3 py-2 max-w-[220px]">
                      {value ? (
                        isUrlValue(value) ? (
                          <a
                            href={value}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-cyan hover:underline inline-flex items-center gap-1"
                          >
                            <ExternalLink className="h-3 w-3 shrink-0" />
                            <span className="truncate">{hostnameOf(value)}</span>
                          </a>
                        ) : (
                          <span className="text-text-primary truncate block" title={value}>
                            {value}
                          </span>
                        )
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                  );
                })}
                <td className="px-3 py-2 font-mono text-text-secondary">
                  {confidenceOf(record)}%
                </td>
                <td className="px-3 py-2">
                  {record.citation_url && (
                    <a
                      href={record.citation_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan/60 hover:text-cyan transition-colors"
                      title={`Open source page${record.citation_snippet ? "\n\n“" + record.citation_snippet + "”" : ""}`}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center text-text-muted text-xs py-8">
            No records match &quot;{search}&quot;
          </div>
        )}
      </div>
    </div>
  );
}