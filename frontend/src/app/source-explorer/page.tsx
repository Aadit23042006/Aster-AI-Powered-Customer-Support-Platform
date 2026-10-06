"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";

import { AppShell } from "@/components/layout/app-shell";
import { Card, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { AICitation } from "@/types/api";

type CitationWithVersion = AICitation & {
  document_version?: string | null;
};

function normalizeMarkdown(value: string): string {
  if (!value) {
    return "";
  }

  /*
   * Some persisted passages contain escaped Markdown:
   *
   *   \# Returns Policy
   *   \## Standard return window
   *   \*\*30 calendar days\*\*
   *
   * Source Explorer should render those as normal Markdown.
   *
   * Only remove the backslash when it is escaping a Markdown
   * character. This avoids changing ordinary backslashes.
   */
  return value.replace(
    /\\([\\`*_[\]{}()#+\-.!>])/g,
    "$1"
  );
}

function SourceExplorerInner() {
  const router = useRouter();
  const params = useSearchParams();
  const queryConversationId = params.get("c");

  const [conversationId, setConversationId] = useState<string | null>(
    queryConversationId
  );
  const [sources, setSources] = useState<CitationWithVersion[] | null>(
    null
  );
  const [error, setError] = useState("");

  useEffect(() => {
    if (queryConversationId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConversationId(queryConversationId);
      return;
    }

    let cancelled = false;

    setSources(null);
    setError("");

    api
      .listConversations()
      .then((conversations) => {
        if (cancelled) return;

        const latest = Array.isArray(conversations)
          ? conversations[0]
          : null;

        if (!latest?.id) {
          setConversationId(null);
          setSources([]);
          return;
        }

        setConversationId(latest.id);
        router.replace(
          `/source-explorer?c=${encodeURIComponent(latest.id)}`
        );
      })
      .catch((e) => {
        if (cancelled) return;
        setConversationId(null);
        setError(
          e?.message || "Could not find a conversation to inspect."
        );
      });

    return () => {
      cancelled = true;
    };
  }, [queryConversationId, router]);

  useEffect(() => {
    if (!conversationId) {
      return;
    }

    let cancelled = false;

    setSources(null);
    setError("");

    api
      .sourceExplorer(conversationId)
      .then((rows) => {
        if (!cancelled) {
          setSources(rows as CitationWithVersion[]);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e?.message || "Could not load verified sources."
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-4">
        <div>
          <h1 className="text-xl font-semibold">
            RAG Source Explorer
          </h1>

          <p className="mt-1 text-sm text-stone-500">
            Only verified retrieved passages are shown.
          </p>
        </div>

        {error && (
          <div className="rounded bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {!sources && !error && (
          <Spinner className="h-5 w-5" />
        )}

        {sources?.length === 0 && (
          <Card className="p-5 text-sm text-stone-500">
            No verified source found.
          </Card>
        )}

        {sources?.map((source) => {
          const version =
            source.document_version || null;

          const relevance =
            source.relevance_score == null
              ? null
              : Math.round(
                  Number(source.relevance_score) * 100
                );

          const passage = normalizeMarkdown(
            source.passage || ""
          );

          return (
            <Card
              key={source.id}
              className="p-5"
            >
              {/* Header */}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="font-semibold">
                    {source.title || source.document}
                  </h2>

                  <div className="mt-1 text-xs text-stone-500">
                    {source.document}
                    {" · "}
                    {source.heading || "Source"}
                  </div>
                </div>

                {relevance != null && (
                  <div className="shrink-0 text-sm font-medium">
                    {relevance}%
                  </div>
                )}
              </div>

              {/* Citation metadata */}
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 rounded-md bg-stone-50 px-3 py-2 text-xs text-stone-600">
                <div>
                  <span className="font-medium text-stone-700">
                    Version:
                  </span>{" "}
                  {version || "—"}
                </div>

                <div>
                  <span className="font-medium text-stone-700">
                    Updated:
                  </span>{" "}
                  {source.updated_at || "—"}
                </div>

                <div>
                  <span className="font-medium text-stone-700">
                    Relevance:
                  </span>{" "}
                  {relevance != null
                    ? `${relevance}%`
                    : "—"}
                </div>
              </div>

              {/* Verified passage */}
              <div className="mt-5">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-stone-500">
                  Verified retrieved passage
                </div>

                <div className="prose prose-sm max-w-none text-stone-700">
                  <ReactMarkdown
                    components={{
                      h1: ({ children }) => (
                        <h1 className="mb-3 text-xl font-semibold text-stone-900">
                          {children}
                        </h1>
                      ),

                      h2: ({ children }) => (
                        <h2 className="mb-2 mt-4 text-lg font-semibold text-stone-900">
                          {children}
                        </h2>
                      ),

                      h3: ({ children }) => (
                        <h3 className="mb-2 mt-3 text-base font-semibold text-stone-900">
                          {children}
                        </h3>
                      ),

                      p: ({ children }) => (
                        <p className="mb-3 leading-6">
                          {children}
                        </p>
                      ),

                      strong: ({ children }) => (
                        <strong className="font-semibold text-stone-900">
                          {children}
                        </strong>
                      ),

                      ul: ({ children }) => (
                        <ul className="mb-3 list-disc space-y-1 pl-5">
                          {children}
                        </ul>
                      ),

                      ol: ({ children }) => (
                        <ol className="mb-3 list-decimal space-y-1 pl-5">
                          {children}
                        </ol>
                      ),

                      li: ({ children }) => (
                        <li>{children}</li>
                      ),
                    }}
                  >
                    {passage}
                  </ReactMarkdown>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </AppShell>
  );
}

export default function SourceExplorer() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <Spinner className="h-5 w-5" />
        </AppShell>
      }
    >
      <SourceExplorerInner />
    </Suspense>
  );
}