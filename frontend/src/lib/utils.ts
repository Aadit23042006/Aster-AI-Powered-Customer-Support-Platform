import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function statusTone(status: string): "neutral" | "success" | "warning" | "danger" | "info" {
  const map: Record<string, "neutral" | "success" | "warning" | "danger" | "info"> = {
    pending: "neutral",
    processing: "info",
    shipped: "info",
    in_transit: "info",
    delivered: "success",
    cancelled: "neutral",
    returned: "neutral",
    exception: "danger",
    open: "warning",
    in_progress: "info",
    waiting_for_customer: "warning",
    resolved: "success",
    closed: "neutral",
    low: "neutral",
    medium: "info",
    high: "warning",
    urgent: "danger",
  };
  return map[status] || "neutral";
}

export function titleCase(s: string): string {
  return s
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
