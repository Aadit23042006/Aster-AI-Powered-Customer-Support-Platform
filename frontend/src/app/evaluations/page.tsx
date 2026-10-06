"use client";

import { useCallback, useEffect, useState } from "react";
import { Play, CheckCircle2, XCircle, GitCompare, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { EvaluationComparison, EvaluationRun, EvaluationRunDetail } from "@/types/api";

function statusBadge(status: EvaluationRun["status"]) {
  const map: Record<EvaluationRun["status"], { tone: "neutral" | "success" | "warning" | "danger" | "info"; label: string }> = {
    queued: { tone: "neutral", label: "Queued" },
    running: { tone: "info", label: "Running…" },
    completed: { tone: "success", label: "Completed" },
    failed: { tone: "danger", label: "Failed" },
  };
  const { tone, label } = map[status];
  return <Badge tone={tone}>{label}</Badge>;
}

export default function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationRun[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [compareWith, setCompareWith] = useState<string[]>([]);
  const [comparison, setComparison] = useState<EvaluationComparison | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await api.listEvaluationRuns();
      setRuns(resp.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load evaluation runs.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
  }, [load]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      const run = await api.runEvaluation({ use_mock_llm: true });
      await load();
      setSelected(run.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Evaluation run failed to start.");
    } finally {
      setRunning(false);
    }
  }

  function toggleCompare(id: string) {
    setCompareWith((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2);
      return next;
    });
    setComparison(null);
  }

  async function runCompare() {
    if (compareWith.length !== 2) return;
    const [a, b] = compareWith;
    const result = await api.compareEvaluationRuns(a, b);
    setComparison(result);
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-stone-900">AI Evaluation Center</h1>
            <p className="text-sm text-stone-500">Runs the real evaluation/run_eval.py harness against the live agent.</p>
          </div>
          <div className="flex gap-2">
            {compareWith.length === 2 && (
              <Button variant="secondary" size="sm" onClick={runCompare}>
                <GitCompare className="h-4 w-4" /> Compare
              </Button>
            )}
            <Button size="sm" onClick={handleRun} disabled={running}>
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run Evaluation
            </Button>
          </div>
        </div>

        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        {comparison && (
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-stone-900">
              Run #{comparison.run_a.run_number} vs Run #{comparison.run_b.run_number}
            </h3>
            <div className="space-y-1.5">
              {Object.entries(comparison.by_category).map(([cat, d]) => {
                const rateA = d.run_a.total ? Math.round((d.run_a.passed / d.run_a.total) * 100) : 0;
                const rateB = d.run_b.total ? Math.round((d.run_b.passed / d.run_b.total) * 100) : 0;
                const delta = rateB - rateA;
                return (
                  <div key={cat} className="flex items-center justify-between text-xs">
                    <span className="text-stone-600">{cat}</span>
                    <span className="font-medium">
                      {rateA}% → {rateB}%{" "}
                      <span className={cn(delta > 0 ? "text-emerald-600" : delta < 0 ? "text-red-600" : "text-stone-400")}>
                        ({delta > 0 ? "+" : ""}
                        {delta}%)
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          </Card>
        )}

        {runs === null && (
          <div className="flex justify-center py-12">
            <Spinner className="h-5 w-5 text-stone-400" />
          </div>
        )}

        {runs && (
          <Card className="divide-y divide-stone-100">
            {runs.map((r) => {
              const passRate = r.total_cases ? Math.round((r.passed_cases / r.total_cases) * 100) : null;
              return (
                <div key={r.id} className="flex items-center gap-3 px-4 py-3">
                  <input type="checkbox" checked={compareWith.includes(r.id)} onChange={() => toggleCompare(r.id)} className="shrink-0" />
                  <button onClick={() => setSelected(r.id)} className="flex flex-1 items-center justify-between gap-3 text-left">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-stone-900">Run #{r.run_number}</span>
                        {statusBadge(r.status)}
                        {r.use_mock_llm && <span className="text-[10px] text-stone-400">mock</span>}
                      </div>
                      <p className="mt-0.5 text-xs text-stone-400">
                        {r.total_cases} test cases{r.error ? ` · ${r.error}` : ""}
                      </p>
                    </div>
                    {passRate !== null && (
                      <span className={cn("text-sm font-semibold", passRate >= 90 ? "text-emerald-600" : passRate >= 60 ? "text-amber-600" : "text-red-600")}>
                        {r.passed_cases}/{r.total_cases} ({passRate}%)
                      </span>
                    )}
                  </button>
                </div>
              );
            })}
            {runs.length === 0 && <div className="px-4 py-10 text-center text-sm text-stone-400">No evaluation runs yet.</div>}
          </Card>
        )}
      </div>

      {selected && <RunDrawer runId={selected} onClose={() => setSelected(null)} />}
    </AppShell>
  );
}

function RunDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [run, setRun] = useState<EvaluationRunDetail | null>(null);

  useEffect(() => {
    api.getEvaluationRun(runId).then(setRun);
  }, [runId]);

  if (!run) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
        <Spinner className="h-5 w-5 text-white" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-sm font-semibold text-stone-900">Run #{run.run_number}</h2>
          {statusBadge(run.status)}
        </div>

        {run.category_breakdown && (
          <div className="mb-4 space-y-1.5">
            {Object.entries(run.category_breakdown).map(([cat, d]) => {
              const rate = d.total ? Math.round((d.passed / d.total) * 100) : 0;
              return (
                <div key={cat} className="flex items-center gap-2 text-xs">
                  <span className="w-32 shrink-0 text-stone-500">{cat}</span>
                  <div className="h-2 flex-1 rounded bg-stone-100">
                    <div className={cn("h-full rounded", rate >= 90 ? "bg-emerald-500" : rate >= 60 ? "bg-amber-500" : "bg-red-500")} style={{ width: `${rate}%` }} />
                  </div>
                  <span className="w-16 shrink-0 text-right text-stone-500">
                    {d.passed}/{d.total}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Test cases</h3>
        <div className="space-y-2">
          {run.results.map((r) => (
            <div key={r.id} className="rounded-lg border border-stone-100 p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-stone-700">{r.case_id}</span>
                {r.passed ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
              </div>
              <p className="mt-1 text-[11px] text-stone-400">{r.category}</p>
              {r.answer_preview && <p className="mt-1 text-xs text-stone-600">{r.answer_preview}</p>}
              {r.notes && r.notes.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-[11px] text-red-600">
                  {r.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
