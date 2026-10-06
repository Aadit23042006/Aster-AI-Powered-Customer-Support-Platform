"use client";

import { useCallback, useEffect, useState } from "react";
import { MessageSquare, ThumbsUp, Zap, ShieldAlert, Search } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Card, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AnalyticsDashboard } from "@/types/api";

const RANGES = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

function BarRow({ label, value, max, color = "bg-stone-900" }: { label: string; value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.max((value / max) * 100, value > 0 ? 3 : 0) : 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 shrink-0 text-stone-400">{label}</span>
      <div className="h-4 flex-1 overflow-hidden rounded bg-stone-100">
        <div className={cn("h-full rounded", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-6 shrink-0 text-right font-medium text-stone-600">{value}</span>
    </div>
  );
}

function TrendChart({ title, days, series }: { title: string; days: string[]; series: { name: string; values: number[]; color: string }[] }) {
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-stone-900">{title}</h3>
        <div className="flex gap-3">
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1 text-[11px] text-stone-500">
              <span className={cn("h-2 w-2 rounded-full", s.color)} /> {s.name}
            </span>
          ))}
        </div>
      </div>
      <div className="flex h-28 items-end gap-1">
        {days.map((day, i) => (
          <div key={day} className="flex flex-1 flex-col items-center gap-0.5">
            <div className="flex h-24 w-full items-end justify-center gap-0.5">
              {series.map((s) => (
                <div
                  key={s.name}
                  className={cn("w-full rounded-t", s.color)}
                  style={{ height: `${Math.max((s.values[i] / max) * 100, s.values[i] > 0 ? 4 : 0)}%` }}
                  title={`${s.name}: ${s.values[i]}`}
                />
              ))}
            </div>
            <span className="text-[9px] text-stone-400">{day.slice(5)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [range, setRange] = useState("7d");
  const [data, setData] = useState<AnalyticsDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.analyticsDashboard(range);
      setData(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load analytics.");
    }
  }, [range]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
  }, [load]);

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-stone-900">AI Analytics</h1>
            <p className="text-sm text-stone-500">Live metrics from real conversations, feedback, and the AI trace log.</p>
          </div>
          <div className="flex gap-1 rounded-lg border border-stone-200 bg-white p-1">
            {RANGES.map((r) => (
              <button
                key={r.value}
                onClick={() => setRange(r.value)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium",
                  range === r.value ? "bg-stone-900 text-white" : "text-stone-600 hover:bg-stone-100"
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        {!data && !error && (
          <div className="flex justify-center py-16">
            <Spinner className="h-5 w-5 text-stone-400" />
          </div>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KPI icon={MessageSquare} label="Conversations" value={data.summary.conversations.total} sub={`${data.summary.conversations.active} active`} />
              <KPI icon={Zap} label="AI resolved" value={data.summary.resolution.ai_resolved} sub={`${data.summary.resolution.human_handoff} handed off`} />
              <KPI
                icon={ThumbsUp}
                label="Satisfaction"
                value={data.summary.feedback.satisfaction_rate !== null ? `${Math.round(data.summary.feedback.satisfaction_rate * 100)}%` : "—"}
                sub={`${data.summary.feedback.positive}👍 / ${data.summary.feedback.negative}👎`}
              />
              <KPI
                icon={ShieldAlert}
                label="Policy conflicts"
                value={data.summary.safety.policy_conflicts}
                sub={`${data.summary.safety.prompt_injection_attempts} injection flags`}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <TrendChart
                title="Conversations over time"
                days={data.timeseries.days}
                series={[{ name: "Conversations", values: data.timeseries.conversations, color: "bg-stone-900" }]}
              />
              <TrendChart
                title="AI vs. human resolution"
                days={data.timeseries.days}
                series={[
                  { name: "AI resolved", values: data.timeseries.ai_resolved, color: "bg-emerald-500" },
                  { name: "Handoff", values: data.timeseries.human_handoff, color: "bg-amber-500" },
                ]}
              />
              <TrendChart
                title="Feedback trend"
                days={data.timeseries.days}
                series={[
                  { name: "Positive", values: data.timeseries.positive_feedback, color: "bg-emerald-500" },
                  { name: "Negative", values: data.timeseries.negative_feedback, color: "bg-red-500" },
                ]}
              />

              <Card className="p-4">
                <h3 className="mb-3 text-sm font-semibold text-stone-900">Performance</h3>
                <div className="space-y-2 text-xs text-stone-600">
                  <div className="flex justify-between"><span>Average response</span><span className="font-medium">{data.summary.performance.average_response_ms ?? "—"} ms</span></div>
                  <div className="flex justify-between"><span>P50 latency</span><span className="font-medium">{data.summary.performance.p50_ms ?? "—"} ms</span></div>
                  <div className="flex justify-between"><span>P95 latency</span><span className="font-medium">{data.summary.performance.p95_ms ?? "—"} ms</span></div>
                </div>
              </Card>
            </div>

            <Card className="p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-900">
                <Search className="h-4 w-4" /> Retrieval &amp; safety
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <BarRow label="Success" value={data.summary.rag.retrieval_success} max={data.summary.rag.retrieval_attempts || 1} color="bg-emerald-500" />
                  <BarRow label="Low-conf" value={data.summary.rag.low_confidence_queries} max={data.summary.rag.retrieval_attempts || 1} color="bg-amber-500" />
                  <BarRow label="No source" value={data.summary.rag.no_source_responses} max={data.summary.rag.retrieval_attempts || 1} color="bg-red-500" />
                </div>
                <div>
                  <p className="mb-1.5 text-xs font-medium text-stone-500">Top retrieved documents</p>
                  <ul className="space-y-1 text-xs text-stone-600">
                    {data.summary.rag.top_retrieved_documents.slice(0, 5).map((d) => (
                      <li key={d.source_file} className="flex justify-between">
                        <span className="truncate">{d.source_file}</span>
                        <span className="font-medium">{d.count}</span>
                      </li>
                    ))}
                    {data.summary.rag.top_retrieved_documents.length === 0 && <li className="text-stone-400">No retrievals yet.</li>}
                  </ul>
                </div>
              </div>
            </Card>
          </>
        )}
      </div>
    </AppShell>
  );
}

function KPI({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs text-stone-500">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-stone-900">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-stone-400">{sub}</div>}
    </Card>
  );
}
