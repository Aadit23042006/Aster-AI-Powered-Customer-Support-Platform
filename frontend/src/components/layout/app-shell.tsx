"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Spinner } from "@/components/ui/primitives";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);

  if (loading || !user) return <div className="flex h-screen items-center justify-center bg-[#f5f7fb]"><Spinner className="h-7 w-7 text-indigo-600" /></div>;

  return (
    <div className="flex min-h-screen bg-[#f5f7fb] text-slate-900">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="app-grid-bg flex-1 overflow-y-auto px-4 py-5 md:px-7 md:py-7 lg:px-9">{children}</main>
      </div>
    </div>
  );
}
