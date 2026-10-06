"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Bot, Send } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn, formatDateTime, statusTone, titleCase } from "@/lib/utils";
import type { TicketDetail } from "@/types/api";

export default function TicketDetailPage() {
  const params = useParams<{ id: string }>();
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const t = await api.getTicket(params.id);
      setTicket(t);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this ticket.");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function onReply(e: React.FormEvent) {
    e.preventDefault();
    if (!reply.trim()) return;
    setSending(true);
    try {
      await api.addTicketMessage(params.id, reply.trim());
      setReply("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send message.");
    } finally {
      setSending(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <Link href="/tickets" className="mb-4 flex items-center gap-1 text-sm text-stone-500 hover:text-stone-900">
          <ArrowLeft className="h-4 w-4" /> Back to tickets
        </Link>

        {error && <Card className="p-6 text-sm text-red-600">{error}</Card>}
        {!error && !ticket && (
          <div className="flex justify-center py-16">
            <Spinner className="h-6 w-6 text-stone-400" />
          </div>
        )}

        {ticket && (
          <div className="space-y-5">
            <div>
              <div className="flex items-center gap-2 text-xs text-stone-400">
                <span>#{ticket.ticket_number}</span>
                {ticket.created_by_ai && (
                  <span className="flex items-center gap-1 text-stone-500">
                    <Bot className="h-3 w-3" /> Opened by AI assistant
                  </span>
                )}
              </div>
              <h2 className="mt-1 text-lg font-semibold text-stone-900">{ticket.subject}</h2>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge tone={statusTone(ticket.status)}>{titleCase(ticket.status)}</Badge>
                <Badge tone={statusTone(ticket.priority)}>{titleCase(ticket.priority)} priority</Badge>
                <Badge tone="neutral">{titleCase(ticket.category)}</Badge>
              </div>
              {ticket.handoff_reason && (
                <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  <strong>Why a human was looped in:</strong> {ticket.handoff_reason}
                </p>
              )}
            </div>

            <Card className="divide-y divide-stone-100">
              {ticket.messages.map((m) => (
                <div key={m.id} className="p-4">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-medium text-stone-500">
                      {m.author_role === "customer" ? "You" : m.author_role === "support_agent" ? "Support agent" : "System"}
                    </span>
                    <span className="text-xs text-stone-400">{formatDateTime(m.created_at)}</span>
                  </div>
                  <p className={cn("whitespace-pre-wrap text-sm", m.author_role === "system" && "text-stone-500")}>{m.content}</p>
                </div>
              ))}
            </Card>

            {!["resolved", "closed"].includes(ticket.status) && (
              <form onSubmit={onReply} className="flex gap-2">
                <input
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Add a message…"
                  className="flex-1 rounded-lg border border-stone-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-stone-400"
                />
                <Button type="submit" disabled={sending || !reply.trim()}>
                  <Send className="h-4 w-4" />
                </Button>
              </form>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
