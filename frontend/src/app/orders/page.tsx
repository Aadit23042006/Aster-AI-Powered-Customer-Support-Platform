"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Package, Search } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Card, EmptyState, Input, SkeletonLine } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn, formatDate, statusTone, titleCase } from "@/lib/utils";
import type { Order, OrderStatus } from "@/types/api";

const FILTERS: { label: string; value: OrderStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Processing", value: "processing" },
  { label: "Shipped", value: "shipped" },
  { label: "In Transit", value: "in_transit" },
  { label: "Delivered", value: "delivered" },
  { label: "Cancelled", value: "cancelled" },
  { label: "Returned", value: "returned" },
];

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [filter, setFilter] = useState<OrderStatus | "all">("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.listOrders().then(setOrders).catch(() => setOrders([]));
  }, []);

  const filtered = useMemo(() => {
    if (!orders) return [];
    return orders.filter((o) => {
      const matchesFilter = filter === "all" || o.status === filter;
      const q = query.trim().toLowerCase();
      const matchesQuery =
        !q || o.order_number.toLowerCase().includes(q) || o.items.some((i) => i.product_name.toLowerCase().includes(q));
      return matchesFilter && matchesQuery;
    });
  }, [orders, filter, query]);

  const counts = useMemo(() => {
    const total = orders?.length || 0;
    const active = orders?.filter((o) => ["pending", "processing", "shipped", "in_transit"].includes(o.status)).length || 0;
    const delivered = orders?.filter((o) => o.status === "delivered").length || 0;
    const returns = orders?.filter((o) => ["returned", "cancelled"].includes(o.status)).length || 0;
    return { total, active, delivered, returns };
  }, [orders]);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Total", value: counts.total },
            { label: "Active", value: counts.active },
            { label: "Delivered", value: counts.delivered },
            { label: "Returns/Cancelled", value: counts.returns },
          ].map((s) => (
            <Card key={s.label} className="p-4">
              <p className="text-2xl font-semibold text-stone-900">{orders === null ? "—" : s.value}</p>
              <p className="text-xs text-stone-500">{s.label}</p>
            </Card>
          ))}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs font-medium",
                  filter === f.value ? "bg-stone-900 text-white" : "bg-stone-100 text-stone-600 hover:bg-stone-200"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search order or product…" className="pl-9" />
          </div>
        </div>

        {orders === null && (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <SkeletonLine key={i} className="h-16 w-full" />
            ))}
          </div>
        )}

        {orders !== null && filtered.length === 0 && (
          <EmptyState
            title="No orders found"
            description={orders.length === 0 ? "You haven't placed any orders yet." : "Try a different filter or search."}
          />
        )}

        <div className="space-y-2">
          {filtered.map((o) => (
            <Link key={o.id} href={`/orders/${o.id}`}>
              <Card className="flex items-center justify-between p-4 hover:border-stone-300">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-stone-100">
                    <Package className="h-5 w-5 text-stone-500" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-stone-900">{o.order_number}</p>
                    <p className="text-xs text-stone-500">
                      {o.items[0]?.product_name}
                      {o.items.length > 1 ? ` +${o.items.length - 1} more` : ""} · {formatDate(o.placed_at)}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <Badge tone={statusTone(o.status)}>{titleCase(o.status)}</Badge>
                  {o.estimated_delivery && (
                    <p className="mt-1 text-xs text-stone-400">Est. {formatDate(o.estimated_delivery)}</p>
                  )}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
