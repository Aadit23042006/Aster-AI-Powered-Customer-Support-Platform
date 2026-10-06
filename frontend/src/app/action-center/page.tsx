"use client";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { AIActionItem, EnterpriseTool } from "@/types/api";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";
const STATUS_TONE: Record<string, Tone> = {
  success: "success", approval_required: "warning", pending: "info", failed: "danger", denied: "danger", rejected: "danger",
};
const STATUS_LABEL: Record<string, string> = {
  success: "COMPLETED", approval_required: "APPROVAL REQUIRED", pending: "PENDING", failed: "FAILED", denied: "DENIED", rejected: "REJECTED",
};
const CATEGORY_LABEL: Record<string, string> = { read_only: "Read only", mutating: "Mutating", external: "External" };

const FILTERS = [
  { key: "", label: "All" },
  { key: "pending", label: "Awaiting approval" },
] as const;

export default function ActionCenter() {
  const [tools, setTools] = useState<EnterpriseTool[]>([]);
  const [actions, setActions] = useState<AIActionItem[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [t, a] = await Promise.all([
        api.enterpriseTools(),
        api.enterpriseActions(filter ? { approval_status: filter } : undefined),
      ]);
      setTools(t.tools);
      setActions(a);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load Action Center.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  async function decide(id: string, decision: "approve" | "reject") {
    setBusyId(id);
    setError("");
    setNotice("");
    try {
      if (decision === "approve") await api.approveEnterpriseAction(id);
      else await api.rejectEnterpriseAction(id);
      setNotice(decision === "approve" ? "Action approved and executed." : "Action rejected. Nothing was executed.");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update the action.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Action Center</h1>
          <p className="text-sm text-stone-500">
            Every AI tool call, its permission and approval status, and a sanitized execution audit trail.
          </p>
        </div>

        {error && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        {notice && <div role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>}

        <Card className="p-5">
          <h2 className="mb-4 font-semibold">Available tools</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {tools.map((t) => (
              <div key={t.name} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b>{t.name}</b>
                  <span className="flex gap-1.5">
                    {t.category && <Badge tone={t.category === "read_only" ? "success" : "warning"}>{CATEGORY_LABEL[t.category] ?? t.category}</Badge>}
                    <Badge>{t.risk_level}</Badge>
                  </span>
                </div>
                <p className="text-sm text-stone-500">{t.description}</p>
                <p className="mt-1 text-xs text-stone-400">Permission: {t.permission}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">AI actions</h2>
            <div className="flex gap-2" role="tablist" aria-label="Action filter">
              {FILTERS.map((f) => (
                <Button key={f.key} role="tab" aria-selected={filter === f.key} size="sm"
                  variant={filter === f.key ? "primary" : "secondary"} onClick={() => setFilter(f.key)}>
                  {f.label}
                </Button>
              ))}
            </div>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-stone-500" role="status"><Spinner className="h-4 w-4" /> Loading actions…</div>
          ) : actions.length === 0 ? (
            <EmptyState title={filter ? "Nothing is awaiting approval" : "No actions yet"}
              description="AI tool calls appear here with their permission, approval and execution status." />
          ) : (
            <ul className="space-y-2">
              {actions.map((a) => {
                const awaiting = a.approval_status === "pending" && a.execution_status === "approval_required";
                return (
                  <li key={a.id} className="rounded-lg border p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <b>{a.tool_name}</b>
                      <span className="flex flex-wrap gap-1.5">
                        {a.category && <Badge>{CATEGORY_LABEL[a.category] ?? a.category}</Badge>}
                        {a.origin && <Badge tone="info">{a.origin === "ai" ? "AI proposed" : "Staff"}</Badge>}
                        <Badge tone={STATUS_TONE[a.execution_status] ?? "neutral"}>{STATUS_LABEL[a.execution_status] ?? a.execution_status}</Badge>
                      </span>
                    </div>
                    {a.reason && <p className="mt-1 text-stone-600">Reason: {a.reason}</p>}
                    <div className="mt-1 text-xs text-stone-500">
                      Permission: {a.permission_result}
                      {a.approval_status ? ` · Approval: ${a.approval_status.replace("_", " ")}` : ""}
                      {a.order_number ? ` · Order ${a.order_number}` : ""}
                      {a.ticket_id ? ` · Ticket ${a.ticket_id.slice(0, 8)}` : ""}
                      {` · ${a.duration_ms ?? "—"} ms · ${new Date(a.created_at).toLocaleString()}`}
                    </div>
                    {a.error && <div className="mt-1 text-red-600">{a.error}</div>}
                    {awaiting && (
                      <div className="mt-3 flex gap-2">
                        <Button size="sm" disabled={busyId === a.id} onClick={() => decide(a.id, "approve")}>
                          {busyId === a.id ? <Spinner className="h-4 w-4" /> : null} Approve &amp; run
                        </Button>
                        <Button size="sm" variant="secondary" disabled={busyId === a.id} onClick={() => decide(a.id, "reject")}>Reject</Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
