"use client";

import { useState } from "react";
import { Badge, Button, Card, Input, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { Phase4Webhook, Phase4WebhookDelivery } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { CompactEmpty, describeError, Field, Modal, NoticeBanner, useNotice } from "./common";

// Mirrors WEBHOOK_EVENTS in app/phase4/__init__.py (the API has no endpoint that lists them).
const WEBHOOK_EVENTS = [
  "conversation.created",
  "conversation.completed",
  "ticket.created",
  "ticket.updated",
  "ticket.closed",
  "order.created",
  "order.updated",
  "human_handoff.created",
  "knowledge_document.indexed",
  "knowledge_document.failed",
  "evaluation.completed",
  "recommendation.created",
  "notification.created",
];

function isValidUrl(v: string): boolean {
  try {
    const u = new URL(v);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

function deliveryTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "delivered") return "success";
  if (status === "failed") return "danger";
  if (status === "retrying" || status === "pending") return "warning";
  return "neutral";
}

function WebhookFormModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (payload: { url: string; events: string[] }) => Promise<string | null>;
}) {
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (ev: string) => setEvents((cur) => (cur.includes(ev) ? cur.filter((x) => x !== ev) : [...cur, ev]));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValidUrl(url.trim())) {
      setError("Enter a valid http:// or https:// URL.");
      return;
    }
    if (events.length === 0) {
      setError("Select at least one event.");
      return;
    }
    setBusy(true);
    setError(null);
    const err = await onSubmit({ url: url.trim(), events });
    if (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title="Add webhook" onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-lg bg-red-50 p-2.5 text-xs text-red-700">
            {error}
          </div>
        )}
        <Field label="Endpoint URL">
          <Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hooks/aster-row" autoFocus disabled={busy} />
        </Field>
        <fieldset disabled={busy}>
          <legend className="flex w-full items-center justify-between text-sm">
            <span className="font-medium text-stone-700">Events</span>
            <span className="flex gap-3 text-xs">
              <button type="button" className="text-stone-500 underline" onClick={() => setEvents([...WEBHOOK_EVENTS])}>
                Select all
              </button>
              <button type="button" className="text-stone-500 underline" onClick={() => setEvents([])}>
                Clear
              </button>
            </span>
          </legend>
          <div className="mt-2 grid max-h-56 gap-1 overflow-y-auto rounded-lg border border-stone-200 p-2 sm:grid-cols-2">
            {WEBHOOK_EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-2 rounded px-1 py-1 text-xs hover:bg-stone-50">
                <input type="checkbox" checked={events.includes(ev)} onChange={() => toggle(ev)} />
                {ev}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !url.trim() || events.length === 0}>
            {busy && <Spinner className="h-4 w-4" />}
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function SecretModal({ secret, onClose }: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied("yes");
    } catch {
      setCopied("no");
    }
  }
  return (
    <Modal title="Webhook signing secret" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
          <b>Copy this secret now.</b> It is shown only once and cannot be retrieved again. Use it to verify webhook signatures on your server.
        </div>
        <code className="block break-all rounded-lg bg-stone-100 p-3 text-xs">{secret}</code>
        {copied === "no" && <p className="text-xs text-red-700">Could not copy automatically. Select the text above and copy it manually.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={copy}>
            {copied === "yes" ? "Copied" : "Copy"}
          </Button>
          <Button onClick={onClose}>I&apos;ve saved it</Button>
        </div>
      </div>
    </Modal>
  );
}

function DeliveriesModal({
  deliveries,
  loading,
  error,
  onRefresh,
  onClose,
}: {
  deliveries: Phase4WebhookDelivery[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title="Webhook deliveries" onClose={onClose} wide>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-stone-500">Most recent deliveries across all endpoints (up to 100).</p>
        <Button size="sm" variant="secondary" onClick={onRefresh} disabled={loading}>
          {loading && <Spinner className="h-4 w-4" />}
          Refresh
        </Button>
      </div>
      {error && (
        <div role="alert" className="mt-3 rounded-lg bg-red-50 p-2.5 text-xs text-red-700">
          {error}
        </div>
      )}
      {loading && deliveries.length === 0 ? (
        <div className="flex justify-center p-8">
          <Spinner className="h-5 w-5 text-stone-400" />
        </div>
      ) : deliveries.length === 0 && !error ? (
        <p className="mt-4 rounded-xl border border-dashed border-stone-300 p-6 text-center text-sm text-stone-500">No deliveries yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead className="text-stone-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Event</th>
                <th className="py-2 pr-3 font-medium">Event ID</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Attempts</th>
                <th className="py-2 pr-3 font-medium">HTTP</th>
                <th className="py-2 pr-3 font-medium">Time</th>
                <th className="py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((d) => (
                <tr key={d.id} className="border-t border-stone-100">
                  <td className="py-2 pr-3">{d.event}</td>
                  <td className="py-2 pr-3 font-mono" title={d.event_id}>
                    {d.event_id.slice(0, 8)}
                  </td>
                  <td className="py-2 pr-3">
                    <Badge tone={deliveryTone(d.status)}>{d.status}</Badge>
                  </td>
                  <td className="py-2 pr-3">{d.retry_count}</td>
                  <td className="py-2 pr-3">{d.status_code ?? "—"}</td>
                  <td className="py-2 pr-3">{d.response_time_ms != null ? `${Math.round(d.response_time_ms)} ms` : "—"}</td>
                  <td className="py-2">{formatDateTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

export function WebhooksPanel({
  webhooks,
  setWebhooks,
}: {
  webhooks: Phase4Webhook[];
  setWebhooks: (w: Phase4Webhook[]) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showDeliveries, setShowDeliveries] = useState(false);
  const [deliveries, setDeliveries] = useState<Phase4WebhookDelivery[]>([]);
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [deliveriesError, setDeliveriesError] = useState<string | null>(null);
  const notice = useNotice();

  async function refresh(): Promise<boolean> {
    try {
      setWebhooks(await api.phase4Webhooks());
      return true;
    } catch (e) {
      notice.showError(describeError(e, "refresh webhooks"));
      return false;
    }
  }

  async function create(payload: { url: string; events: string[] }): Promise<string | null> {
    try {
      const created = await api.phase4CreateWebhook(payload);
      setCreating(false);
      setSecret(created.secret); // held in memory only; cleared when the dialog closes
      if (await refresh()) notice.showSuccess("Webhook endpoint created.");
      return null;
    } catch (e) {
      return describeError(e, "create webhooks");
    }
  }

  async function remove(w: Phase4Webhook) {
    setDeletingId(w.id);
    notice.clear();
    try {
      await api.phase4DeleteWebhook(w.id);
      setConfirmId(null);
      if (await refresh()) notice.showSuccess("Webhook endpoint deleted.");
    } catch (e) {
      notice.showError(describeError(e, "delete webhooks"));
      setConfirmId(null);
      await refresh();
    } finally {
      setDeletingId(null);
    }
  }

  async function loadDeliveries() {
    setDeliveriesLoading(true);
    setDeliveriesError(null);
    try {
      setDeliveries(await api.phase4WebhookDeliveries());
    } catch (e) {
      setDeliveriesError(describeError(e, "view deliveries"));
    } finally {
      setDeliveriesLoading(false);
    }
  }

  function openDeliveries() {
    setShowDeliveries(true);
    setDeliveries([]);
    void loadDeliveries();
  }

  const addButton = (
    <Button size="sm" onClick={() => setCreating(true)}>
      + Add Webhook
    </Button>
  );

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Webhooks</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-stone-500">{webhooks.length} endpoints</span>
          <Button size="sm" variant="secondary" onClick={openDeliveries}>
            View Deliveries
          </Button>
          {addButton}
        </div>
      </div>
      <NoticeBanner success={notice.success} error={notice.error} />
      {webhooks.length === 0 ? (
        <CompactEmpty title="No webhook endpoints configured." action={addButton} />
      ) : (
        <div className="mt-3 space-y-2">
          {webhooks.map((w) => {
            const busy = deletingId === w.id;
            return (
              <div key={w.id} className="rounded-lg bg-stone-50 p-3 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all font-medium">{w.url}</span>
                      <Badge tone={w.active ? "success" : "neutral"}>{w.active ? "Active" : "Inactive"}</Badge>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1" title={w.events.join(", ")}>
                      {w.events.slice(0, 4).map((ev) => (
                        <Badge key={ev}>{ev}</Badge>
                      ))}
                      {w.events.length > 4 && <Badge>+{w.events.length - 4} more</Badge>}
                      {w.events.length === 0 && <span className="text-xs text-stone-500">No events selected</span>}
                    </div>
                    <div className="mt-1 text-xs text-stone-500">Created {formatDateTime(w.created_at)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button size="sm" variant="secondary" onClick={openDeliveries} disabled={busy}>
                      View Deliveries
                    </Button>
                    {confirmId === w.id ? (
                      <>
                        <Button size="sm" variant="danger" onClick={() => remove(w)} disabled={busy}>
                          {busy && <Spinner className="h-4 w-4" />}
                          Confirm delete
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)} disabled={busy}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <Button size="sm" variant="ghost" className="text-red-600" onClick={() => setConfirmId(w.id)} disabled={deletingId !== null}>
                        Delete
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {creating && <WebhookFormModal onClose={() => setCreating(false)} onSubmit={create} />}
      {secret && <SecretModal secret={secret} onClose={() => setSecret(null)} />}
      {showDeliveries && (
        <DeliveriesModal
          deliveries={deliveries}
          loading={deliveriesLoading}
          error={deliveriesError}
          onRefresh={loadDeliveries}
          onClose={() => setShowDeliveries(false)}
        />
      )}
    </Card>
  );
}
