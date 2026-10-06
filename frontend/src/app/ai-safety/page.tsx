"use client";
import { AppShell } from "@/components/layout/app-shell";
import { EmptyState } from "@/components/ui/primitives";
export default function AISafetyPage() {
  return (
    <AppShell>
      <EmptyState title="AI safety dashboard — coming in Phase 2" description="A view onto the existing injection-flagging and conflict-watchlist logic in app/safety.py and app/retriever.py." />
    </AppShell>
  );
}
