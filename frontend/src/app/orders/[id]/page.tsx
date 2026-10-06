"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Check, Circle, MessageSquare, Ticket as TicketIcon } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn, formatDate, statusTone, titleCase } from "@/lib/utils";
import type { Order } from "@/types/api";

const TIMELINE_STEPS = ["pending", "processing", "shipped", "in_transit", "delivered"];

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getOrder(params.id)
      .then(setOrder)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load this order."));
  }, [params.id]);

  async function askAiAboutOrder() {
    const conv = await api.createConversation();
    sessionStorage.setItem(`draft:${conv.id}`, `What's the status of order ${order?.order_number}?`);
    router.push(`/chat?c=${conv.id}`);
  }

  async function createTicket() {
    const ticket = await api.createTicket({
      subject: `Issue with order ${order?.order_number}`,
      description: `I have a question about order ${order?.order_number}.`,
      category: "order_issue",
      order_id: order?.id,
    });
    router.push(`/tickets/${ticket.id}`);
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <Link href="/orders" className="mb-4 flex items-center gap-1 text-sm text-stone-500 hover:text-stone-900">
          <ArrowLeft className="h-4 w-4" /> Back to orders
        </Link>

        {error && <Card className="p-6 text-sm text-red-600">{error}</Card>}
        {!error && !order && (
          <div className="flex justify-center py-16">
            <Spinner className="h-6 w-6 text-stone-400" />
          </div>
        )}

        {order && (
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-xl font-semibold text-stone-900">{order.order_number}</h2>
                <p className="text-sm text-stone-500">Placed {formatDate(order.placed_at)}</p>
              </div>
              <Badge tone={statusTone(order.status)}>{titleCase(order.status)}</Badge>
            </div>

            <Card className="p-5">
              <h3 className="mb-4 text-sm font-semibold text-stone-900">Order timeline</h3>
              <Timeline status={order.status} />
              {order.carrier && (
                <div className="mt-5 grid grid-cols-2 gap-4 border-t border-stone-100 pt-4 text-sm">
                  <div>
                    <p className="text-xs text-stone-400">Carrier</p>
                    <p className="font-medium text-stone-900">{order.carrier}</p>
                  </div>
                  {order.tracking_number && (
                    <div>
                      <p className="text-xs text-stone-400">Tracking number</p>
                      <p className="font-medium text-stone-900">{order.tracking_number}</p>
                    </div>
                  )}
                  {order.estimated_delivery && (
                    <div>
                      <p className="text-xs text-stone-400">Estimated delivery</p>
                      <p className="font-medium text-stone-900">{formatDate(order.estimated_delivery)}</p>
                    </div>
                  )}
                </div>
              )}
            </Card>

            <Card className="p-5">
              <h3 className="mb-3 text-sm font-semibold text-stone-900">Items</h3>
              <div className="divide-y divide-stone-100">
                {order.items.map((item, i) => (
                  <div key={i} className="flex items-center justify-between py-2.5 text-sm">
                    <div>
                      <p className="font-medium text-stone-900">{item.product_name}</p>
                      <p className="text-xs text-stone-500">Qty {item.quantity}{item.final_sale ? " · Final sale" : ""}</p>
                    </div>
                    {item.price != null && <p className="text-stone-700">${item.price.toFixed(2)}</p>}
                  </div>
                ))}
              </div>
              {order.total_amount != null && (
                <div className="mt-3 flex justify-between border-t border-stone-100 pt-3 text-sm font-semibold text-stone-900">
                  <span>Total</span>
                  <span>${order.total_amount.toFixed(2)} {order.currency}</span>
                </div>
              )}
            </Card>

            <div className="flex flex-col gap-2 sm:flex-row">
              <Button variant="secondary" className="flex-1" onClick={askAiAboutOrder}>
                <MessageSquare className="h-4 w-4" /> Ask AI About This Order
              </Button>
              <Button variant="secondary" className="flex-1" onClick={createTicket}>
                <TicketIcon className="h-4 w-4" /> Create Support Ticket
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function Timeline({ status }: { status: string }) {
  if (status === "cancelled" || status === "returned" || status === "exception") {
    return (
      <div className="flex items-center gap-2 text-sm text-stone-600">
        <Badge tone={statusTone(status)}>{titleCase(status)}</Badge>
        <span className="text-stone-400">This order is not on the standard delivery timeline.</span>
      </div>
    );
  }
  const currentIndex = TIMELINE_STEPS.indexOf(status);
  return (
    <div className="flex flex-col gap-2">
      {TIMELINE_STEPS.map((step, i) => {
        const done = i < currentIndex;
        const current = i === currentIndex;
        return (
          <div key={step} className="flex items-center gap-2 text-sm">
            {done ? (
              <Check className="h-4 w-4 text-emerald-600" />
            ) : current ? (
              <Circle className="h-4 w-4 fill-stone-900 text-stone-900" />
            ) : (
              <Circle className="h-4 w-4 text-stone-300" />
            )}
            <span className={cn(done || current ? "text-stone-900" : "text-stone-400", current && "font-medium")}>
              {titleCase(step)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
