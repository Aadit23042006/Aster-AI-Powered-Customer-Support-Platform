"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/primitives";

/** Turn an API failure into a short, useful message. `action` reads like "create personas". */
export function describeError(e: unknown, action: string): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "Your session has expired. Please sign in again.";
    if (e.status === 403) return `You don't have permission to ${action}. Organization admin access is required.`;
    if (e.status === 404) return "That item no longer exists. The list has been refreshed.";
    if (e.status === 422) return "The server rejected some of the values. Check the fields and try again.";
    if (e.status >= 500) return "The server hit an error. Please try again in a moment.";
    return e.message || `Could not ${action}.`;
  }
  return `Could not ${action}. Check your connection and try again.`;
}

/** Success/error banner state with auto-dismissing success messages. */
export function useNotice() {
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function showSuccess(msg: string) {
    setError(null);
    setSuccess(msg);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setSuccess(null), 6000);
  }
  function showError(msg: string) {
    setSuccess(null);
    setError(msg);
  }
  function clear() {
    setSuccess(null);
    setError(null);
  }
  return { success, error, showSuccess, showError, clear };
}

export function NoticeBanner({ success, error }: { success: string | null; error: string | null }) {
  if (!success && !error) return null;
  return (
    <div
      role={error ? "alert" : "status"}
      className={
        error
          ? "mt-3 rounded-lg bg-red-50 p-2.5 text-xs text-red-700"
          : "mt-3 rounded-lg bg-emerald-50 p-2.5 text-xs text-emerald-700"
      }
    >
      {error || success}
    </div>
  );
}

export function CompactEmpty({ title, action }: { title: string; action: React.ReactNode }) {
  return (
    <div className="mt-3 flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-stone-300 px-4 py-6 text-center">
      <p className="text-sm text-stone-600">{title}</p>
      {action}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  busy,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
  children: React.ReactNode;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 p-0 sm:items-center sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-xl sm:rounded-2xl ${wide ? "sm:max-w-3xl" : "sm:max-w-lg"}`}
      >
        <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3">
          <h3 className="font-semibold">{title}</h3>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy} aria-label="Close">
            ✕
          </Button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-stone-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}
