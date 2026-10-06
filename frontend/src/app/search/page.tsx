"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Search, ArrowUpRight } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { api } from "@/lib/api";
import type { GlobalSearchResult } from "@/types/api";

function hrefFor(result: GlobalSearchResult) {
  switch (result.type) {
    case "customer":
      return `/customer-360/${result.id}`;
    case "order":
      return `/orders/${result.id}`;
    case "ticket":
      return `/tickets/${result.id}`;
    case "conversation":
      return `/chat?c=${result.id}`;
    case "knowledge_base":
      return `/kb/${result.id}`;
    default:
      return null;
  }
}

export default function GlobalSearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setResults([]);
      setError("");
      return;
    }

    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const response = await api.globalSearch(term);
        setResults(response.results || []);
      } catch {
        setResults([]);
        setError("Search could not be completed.");
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => window.clearTimeout(timer);
  }, [query]);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-stone-900">Global Search</h1>
          <p className="mt-1 text-sm text-stone-500">Search the records available to your account in one place.</p>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-stone-300 bg-white px-4 py-3 shadow-sm">
          <Search className="h-5 w-5 shrink-0 text-stone-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search orders, tickets, customers, conversations, knowledge base…"
            className="w-full bg-transparent text-sm outline-none"
            autoFocus
          />
          <kbd className="hidden rounded bg-stone-100 px-2 py-1 text-xs text-stone-500 sm:block">Ctrl K</kbd>
        </div>

        {loading && <p className="text-sm text-stone-500">Searching…</p>}
        {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        {!loading && query.trim() && results.length === 0 && !error && (
          <div className="rounded-xl border border-dashed border-stone-300 bg-white p-10 text-center text-sm text-stone-500">
            No authorized results found.
          </div>
        )}

        <div className="space-y-2">
          {results.map((result) => {
            const href = hrefFor(result);
            const content = (
              <>
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-stone-900">{result.title}</div>
                    <div className="mt-1 truncate text-xs text-stone-500">{result.type.replace(/_/g, " ")} · {result.subtitle}</div>
                  </div>
                  <ArrowUpRight className="h-4 w-4 shrink-0 text-stone-400" />
                </div>
              </>
            );

            return href ? (
              <Link key={`${result.type}-${result.id}`} href={href} className="block rounded-xl border border-stone-200 bg-white p-4 hover:border-stone-400 hover:bg-stone-50">
                {content}
              </Link>
            ) : (
              <div key={`${result.type}-${result.id}`} className="rounded-xl border border-stone-200 bg-white p-4">
                {content}
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
