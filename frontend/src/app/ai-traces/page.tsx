"use client";

import { useCallback, useEffect, useState } from "react";
import { Search, AlertTriangle, ShieldAlert, CheckCircle2, XCircle, Clock } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Card, Input, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { TraceDetail, TraceSummary } from "@/types/api";

function statusBadge(status: TraceSummary["status"]) {
  const map: Record<TraceSummary["status"], { tone: "neutral" | "success" | "warning" | "danger" | "info"; label: string }> = {
    answered: { tone: "success", label: "Answered" },
    handoff: { tone: "warning", label: "Handoff" },
    insufficient_information: { tone: "neutral", label: "Insufficient info" },
    error: { tone: "danger", label: "Error" },
  };
  const { tone, label } = map[status];
  return <Badge tone={tone}>{label}</Badge>;
}

export default function AITracesPage() {
  const [items, setItems] = useState<TraceSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [conversationId, setConversationId] = useState("");
  const [status, setStatus] = useState("");
  const [handoffOnly, setHandoffOnly] = useState(false);
  const [safetyOnly, setSafetyOnly] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await api.listTraces({
        conversationId: conversationId || undefined,
        status: status || undefined,
        handoff: handoffOnly || undefined,
        safetyEvent: safetyOnly || undefined,
      });
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load traces.");
    }
  }, [conversationId, status, handoffOnly, safetyOnly]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
  }, [load]);

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6">
        <div>
          <h1 className="text-lg font-semibold text-stone-900">AI Traces</h1>
          <p className="text-sm text-stone-500">Per-turn execution metadata: retrieval, tools, safety, handoff, latency — never hidden reasoning or the system prompt.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <Input placeholder="Conversation ID…" className="pl-9" value={conversationId} onChange={(e) => setConversationId(e.target.value)} />
          </div>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm">
            <option value="">All statuses</option>
            <option value="answered">Answered</option>
            <option value="handoff">Handoff</option>
            <option value="insufficient_information">Insufficient info</option>
            <option value="error">Error</option>
          </select>
          <label className="flex items-center gap-1.5 text-xs text-stone-600">
            <input type="checkbox" checked={handoffOnly} onChange={(e) => setHandoffOnly(e.target.checked)} /> Handoff only
          </label>
          <label className="flex items-center gap-1.5 text-xs text-stone-600">
            <input type="checkbox" checked={safetyOnly} onChange={(e) => setSafetyOnly(e.target.checked)} /> Safety events only
          </label>
        </div>

        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        {items === null && (
          <div className="flex justify-center py-12">
            <Spinner className="h-5 w-5 text-stone-400" />
          </div>
        )}

        {items && (
          <Card className="divide-y divide-stone-100">
            <div className="px-4 py-2 text-xs text-stone-400">{total} trace{total !== 1 ? "s" : ""}</div>
            {items.map((t) => (
              <button
                key={t.trace_id}
                onClick={() => setSelected(t.trace_id)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-stone-50"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-mono text-xs text-stone-500">{t.trace_id.slice(0, 8)}</span>
                    {statusBadge(t.status)}
                    {t.safety_event && <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />}
                  </div>
                  <p className="mt-0.5 text-xs text-stone-400">
                    {t.timestamp_iso ? new Date(t.timestamp_iso).toLocaleString() : ""} · {t.retrieval_count} retrieved · {t.tool_calls} tool call{t.tool_calls !== 1 ? "s" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1 text-xs text-stone-500">
                  <Clock className="h-3.5 w-3.5" /> {t.duration_ms?.toFixed(0) ?? "—"} ms
                </div>
              </button>
            ))}
            {items.length === 0 && <div className="px-4 py-10 text-center text-sm text-stone-400">No traces match these filters.</div>}
          </Card>
        )}
      </div>

      {selected && <TraceDrawer traceId={selected} onClose={() => setSelected(null)} />}
    </AppShell>
  );
}

function TraceDrawer({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [trace, setTrace] = useState<TraceDetail | null>(null);

  useEffect(() => {
    api.getTrace(traceId).then(setTrace);
  }, [traceId]);

  if (!trace) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
        <Spinner className="h-5 w-5 text-white" />
      </div>
    );
  }

  const maxOffset = trace.timeline[trace.timeline.length - 1]?.offset_ms || 1;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="font-mono text-sm font-semibold text-stone-900">{trace.trace_id}</h2>
            <p className="text-xs text-stone-400">{trace.timestamp_iso ? new Date(trace.timestamp_iso).toLocaleString() : ""}</p>
          </div>
          {statusBadge(trace.status)}
        </div>

        <div className="mb-4 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Total latency</span><div className="font-medium">{trace.duration_ms?.toFixed(0)} ms</div></div>
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Model</span><div className="font-medium">{trace.model}</div></div>
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Retrieval</span><div className="font-medium">{trace.durations_ms.retrieval_ms?.toFixed(1)} ms · {trace.retrieval_count} sources</div></div>
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Tool calls</span><div className="font-medium">{trace.durations_ms.tool_ms?.toFixed(1)} ms · {trace.tool_calls}</div></div>
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Generation</span><div className="font-medium">{trace.durations_ms.generation_ms?.toFixed(1)} ms</div></div>
          <div className="rounded-lg bg-stone-50 p-2"><span className="text-stone-400">Other</span><div className="font-medium">{trace.durations_ms.other_ms?.toFixed(1)} ms</div></div>
        </div>

        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Timeline</h3>
        <div className="mb-4 space-y-1.5">
          {trace.timeline.map((step) => (
            <div key={step.stage} className="flex items-center gap-2 text-xs">
              <span className="w-40 shrink-0 text-stone-500">{step.stage.replace(/_/g, " ")}</span>
              <div className="h-1.5 flex-1 rounded bg-stone-100">
                <div className="h-full rounded bg-stone-900" style={{ width: `${Math.min(100, (step.offset_ms / maxOffset) * 100)}%` }} />
              </div>
              <span className="w-14 shrink-0 text-right text-stone-400">{step.offset_ms.toFixed(0)} ms</span>
            </div>
          ))}
        </div>

        {(trace.injection_patterns_flagged.length > 0 || trace.conflict_detected) && (
          <div className="mb-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
            <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-3.5 w-3.5" /> Safety signals</div>
            {trace.injection_patterns_flagged.length > 0 && <p className="mt-1">Injection patterns flagged: {trace.injection_patterns_flagged.join(", ")}</p>}
            {trace.conflict_detected && <p className="mt-1">Source conflict detected.</p>}
          </div>
        )}

        {trace.handoff && (
          <div className="mb-4 rounded-lg bg-stone-50 p-3 text-xs text-stone-700">
            <span className="font-medium">Handoff:</span> {trace.handoff_reason || "—"}
          </div>
        )}

        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Retrieved sources</h3>
        <div className="mb-4 space-y-1">
          {trace.retrieved_sources.map((s, i) => (
            <div key={i} className="flex items-center justify-between text-xs text-stone-600">
              <span className="truncate">{s.source_file} — {s.heading}</span>
              <span className={cn("shrink-0", s.is_active_official ? "text-emerald-600" : "text-stone-400")}>{s.score.toFixed(3)}</span>
            </div>
          ))}
          {trace.retrieved_sources.length === 0 && <p className="text-xs text-stone-400">No sources retrieved.</p>}
        </div>

        {trace.tool_call_details.length > 0 && (
          <>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Tool calls</h3>
            <div className="mb-4 space-y-1">
              {trace.tool_call_details.map((tc, i) => (
                <div key={i} className="flex items-center gap-1.5 text-xs text-stone-600">
                  {tc.success ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : <XCircle className="h-3.5 w-3.5 text-red-500" />}
                  {tc.name}
                </div>
              ))}
            </div>
          </>
        )}

        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Conversation</h3>
        <div className="space-y-2 text-xs">
          <div className="rounded-lg bg-stone-100 p-2 text-stone-800">{trace.user_message}</div>
          <div className="rounded-lg bg-stone-50 p-2 text-stone-700">{trace.final_response}</div>
        </div>
      </div>
    </div>
  );
}
