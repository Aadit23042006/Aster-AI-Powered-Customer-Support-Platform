"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bot, Plus, Ticket as TicketIcon } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, EmptyState, Input, SkeletonLine, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { formatDate, statusTone, titleCase } from "@/lib/utils";
import type { Ticket, TicketCategory } from "@/types/api";

const CATEGORIES: { value: TicketCategory; label: string }[] = [
  { value: "order_issue", label: "Order Issue" },
  { value: "shipping", label: "Shipping" },
  { value: "return", label: "Return" },
  { value: "refund", label: "Refund" },
  { value: "damaged_product", label: "Damaged Product" },
  { value: "product_question", label: "Product Question" },
  { value: "payment", label: "Payment" },
  { value: "account", label: "Account" },
  { value: "other", label: "Other" },
];

export default function TicketsPage() {
  const router = useRouter();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<TicketCategory>("other");
  const [priority, setPriority] = useState("medium");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.listTickets().then(setTickets).catch(() => setTickets([]));
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const ticket = await api.createTicket({ subject, description, category, priority });
      router.push(`/tickets/${ticket.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create ticket.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-stone-900">Support Tickets</h2>
          <Button size="sm" onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-4 w-4" /> New ticket
          </Button>
        </div>

        {showForm && (
          <Card className="p-5">
            <form onSubmit={onCreate} className="space-y-3">
              {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
              <Input placeholder="Subject" required value={subject} onChange={(e) => setSubject(e.target.value)} />
              <Textarea placeholder="Describe the issue…" required rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
              <div className="flex gap-3">
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value as TicketCategory)}
                  className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-32 rounded-lg border border-stone-300 px-3 py-2 text-sm">
                  {["low", "medium", "high", "urgent"].map((p) => (
                    <option key={p} value={p}>
                      {titleCase(p)}
                    </option>
                  ))}
                </select>
              </div>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Creating…" : "Create ticket"}
              </Button>
            </form>
          </Card>
        )}

        {tickets === null && (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <SkeletonLine key={i} className="h-16 w-full" />
            ))}
          </div>
        )}

        {tickets?.length === 0 && (
          <EmptyState
            title="No support tickets"
            description="When you need extra help, a ticket will show up here — including any the AI assistant opens for you."
            action={
              <Button variant="secondary" onClick={() => setShowForm(true)}>
                Create your first ticket
              </Button>
            }
          />
        )}

        <div className="space-y-2">
          {tickets?.map((t) => (
            <Link key={t.id} href={`/tickets/${t.id}`}>
              <Card className="flex items-center justify-between p-4 hover:border-stone-300">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-stone-100">
                    {t.created_by_ai ? <Bot className="h-5 w-5 text-stone-500" /> : <TicketIcon className="h-5 w-5 text-stone-500" />}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-stone-900">#{t.ticket_number} · {t.subject}</p>
                    <p className="text-xs text-stone-500">
                      {titleCase(t.category)} · Updated {formatDate(t.updated_at)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={statusTone(t.priority)}>{titleCase(t.priority)}</Badge>
                  <Badge tone={statusTone(t.status)}>{titleCase(t.status)}</Badge>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
