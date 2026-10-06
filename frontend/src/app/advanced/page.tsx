/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import { Button, Card, Spinner } from "@/components/ui/primitives";
import {
  api,
  ApiError,
  type Phase4ApiKey,
  type Phase4RecommendationHistoryItem,
  type Phase4Webhook,
} from "@/lib/api";
import type {
  Phase4Organization,
  Phase4Persona,
  Phase4Product,
} from "@/types/api";

import { PersonasPanel } from "@/components/advanced/personas-panel";
import { WebhooksPanel } from "@/components/advanced/webhooks-panel";

export default function AdvancedPage() {
  // ---------------------------------------------------------------------------
  // Phase 4 platform data
  // ---------------------------------------------------------------------------

  const [orgs, setOrgs] = useState<Phase4Organization[]>([]);
  const [products, setProducts] = useState<Phase4Product[]>([]);
  const [personas, setPersonas] = useState<Phase4Persona[]>([]);
  const [keys, setKeys] = useState<Phase4ApiKey[]>([]);
  const [webhooks, setWebhooks] = useState<Phase4Webhook[]>([]);

  // ---------------------------------------------------------------------------
  // Language
  // ---------------------------------------------------------------------------

  const [language, setLanguage] = useState("en");

  // ---------------------------------------------------------------------------
  // Product recommendations
  // ---------------------------------------------------------------------------

  const [query, setQuery] = useState("");
  const [budget, setBudget] = useState("");
  const [recommendations, setRecommendations] = useState<Phase4Product[]>(
    []
  );

  const [recommendationHistory, setRecommendationHistory] = useState<
    Phase4RecommendationHistoryItem[]
  >([]);

  const [recommending, setRecommending] = useState(false);

  // Feature 15: Product Recommendation Intelligence — per-recommendation
  // explanation (why each product was suggested), fetched on demand.
  const [explanations, setExplanations] = useState<
    Record<string, { items: any[]; loading: boolean; error?: string }>
  >({});

  // ---------------------------------------------------------------------------
  // General page state
  // ---------------------------------------------------------------------------

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API key secret is returned only once by the backend.
  const [newKey, setNewKey] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Load all Phase 4 data
  // ---------------------------------------------------------------------------

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const [
        organizations,
        catalogProducts,
        phase4Personas,
        languagePreference,
        apiKeys,
        phase4Webhooks,
        savedRecommendations,
      ] = await Promise.all([
        api.phase4Organizations(),
        api.phase4Products(),
        api.phase4Personas(),
        api.phase4GetLanguage(),
        api.phase4Keys(),
        api.phase4Webhooks(),
        api.phase4RecommendationHistory(),
      ]);

      setOrgs(organizations);
      setProducts(catalogProducts);
      setPersonas(phase4Personas);
      setLanguage(languagePreference.preferred_language);
      setKeys(apiKeys);
      setWebhooks(phase4Webhooks);

      setRecommendationHistory(savedRecommendations);

      // Restore the most recent persisted recommendation after refresh.
      setRecommendations(savedRecommendations[0]?.products ?? []);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Failed to load Phase 4 platform data"
      );
    } finally {
      setLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Initial load
  // ---------------------------------------------------------------------------

  useEffect(() => {
    void load();
  }, []);

  // ---------------------------------------------------------------------------
  // Language
  // ---------------------------------------------------------------------------

  async function changeLanguage(nextLanguage: string) {
    setLanguage(nextLanguage);

    try {
      await api.phase4SetLanguage(nextLanguage);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Failed to update language preference"
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Product recommendations
  // ---------------------------------------------------------------------------

  async function deleteRecommendation(recommendationId: string) {
    if (!window.confirm("Delete this saved product recommendation? This cannot be undone.")) {
      return;
    }

    try {
      await api.phase4DeleteRecommendation(recommendationId);
      const history = await api.phase4RecommendationHistory();
      setRecommendationHistory(history);
      setRecommendations(history[0]?.products ?? []);
      setError(null);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Failed to delete the saved recommendation"
      );
    }
  }

  async function toggleExplanation(recommendationId: string) {
    // Already loaded — collapse it.
    if (explanations[recommendationId]) {
      setExplanations((prev) => {
        const next = { ...prev };
        delete next[recommendationId];
        return next;
      });
      return;
    }

    setExplanations((prev) => ({
      ...prev,
      [recommendationId]: { items: [], loading: true },
    }));

    try {
      const result = await api.recommendationExplanation(recommendationId);
      setExplanations((prev) => ({
        ...prev,
        [recommendationId]: { items: result.items ?? [], loading: false },
      }));
    } catch (e) {
      setExplanations((prev) => ({
        ...prev,
        [recommendationId]: {
          items: [],
          loading: false,
          error:
            e instanceof ApiError
              ? e.message
              : "Failed to load recommendation explanation",
        },
      }));
    }
  }

  async function recommend() {
    const trimmedQuery = query.trim();

    if (!trimmedQuery || recommending) {
      return;
    }

    setRecommending(true);
    setError(null);

    try {
      const result = await api.phase4Recommend({
        query: trimmedQuery,
        budget: budget ? Number(budget) : undefined,
        limit: 6,
      });

      // Immediately show the newly generated recommendation.
      setRecommendations(result.products);

      // Refresh persisted recommendation history.
      const history = await api.phase4RecommendationHistory();

      setRecommendationHistory(history);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Failed to generate recommendations"
      );
    } finally {
      setRecommending(false);
    }
  }

  // ---------------------------------------------------------------------------
  // API keys
  // ---------------------------------------------------------------------------

  async function createKey() {
    setError(null);

    try {
      const result = await api.phase4CreateKey({
        name: `Dashboard ${new Date().toISOString().slice(0, 10)}`,
        scopes: ["products:read", "recommendations:read"],
        expires_in_days: 90,
      });

      // Secret is intentionally shown only once.
      setNewKey(result.secret);

      await load();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Failed to create API key"
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <AppShell>
        <div className="p-8">
          <Spinner />
        </div>
      </AppShell>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {/* ----------------------------------------------------------------- */}
        {/* Header                                                            */}
        {/* ----------------------------------------------------------------- */}

        <div>
          <h1 className="text-2xl font-semibold">Advanced Platform</h1>

          <p className="text-sm text-stone-500">
            Phase 4: multimodal, multilingual, SaaS and integrations.
          </p>
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* Error                                                             */}
        {/* ----------------------------------------------------------------- */}

        {error && (
          <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ----------------------------------------------------------------- */}
        {/* Language + Organizations                                          */}
        {/* ----------------------------------------------------------------- */}

        <div className="grid gap-4 md:grid-cols-2">
          {/* Language */}
          <Card>
            <h2 className="font-semibold">Language</h2>

            <p className="mt-1 text-xs text-stone-500">
              Preference is persisted for your account.
            </p>

            <select
              value={language}
              onChange={(event) => {
                void changeLanguage(event.target.value);
              }}
              className="mt-3 rounded-lg border p-2 text-sm"
            >
              <option value="en">English</option>
              <option value="hi">Hindi</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
            </select>
          </Card>

          {/* Organizations */}
          <Card>
            <h2 className="font-semibold">Organizations</h2>

            {orgs.length === 0 ? (
              <div className="mt-3 rounded-lg bg-stone-50 p-3 text-sm text-stone-500">
                No organizations available.
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {orgs.map((organization) => (
                  <div
                    key={organization.id}
                    className="flex justify-between rounded-lg bg-stone-50 p-2 text-sm"
                  >
                    <span>{organization.name}</span>

                    <span className="text-stone-500">
                      {organization.role}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* Product Recommendations                                           */}
        {/* ----------------------------------------------------------------- */}

        <Card>
          <div>
            <h2 className="font-semibold">Product Recommendations</h2>

            <p className="mt-1 text-xs text-stone-500">
              Get product recommendations using the organization&apos;s real
              product catalog.
            </p>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void recommend();
                }
              }}
              placeholder="e.g. black jacket"
              className="min-w-[220px] flex-1 rounded-lg border p-2 text-sm"
              disabled={recommending}
            />

            <input
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              placeholder="Budget"
              type="number"
              min="0"
              step="0.01"
              className="w-32 rounded-lg border p-2 text-sm"
              disabled={recommending}
            />

            <Button
              onClick={() => {
                void recommend();
              }}
              disabled={!query.trim() || recommending}
            >
              {recommending ? "Finding..." : "Recommend"}
            </Button>
          </div>

          {/* Current recommendation results */}
          {recommendations.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-stone-500">
                Current Results
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {recommendations.map((product) => (
                  <div
                    key={product.id}
                    className="rounded-xl border p-4"
                  >
                    <div className="font-medium">{product.name}</div>

                    <div className="text-xs text-stone-500">
                      {product.sku} · {product.inventory_status}
                    </div>

                    <div className="mt-2 font-semibold">
                      {product.currency} {product.price.toFixed(2)}
                    </div>

                    {product.description && (
                      <div className="mt-1 text-xs text-stone-500">
                        {product.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* No recommendation results */}
          {!recommending &&
            query.trim() &&
            recommendations.length === 0 && (
              <div className="mt-4 rounded-lg bg-stone-50 p-4 text-sm text-stone-500">
                No matching products were found for this request.
              </div>
            )}

          {/* Catalog fallback / available products */}
          {recommendations.length === 0 && !query.trim() && products.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-stone-500">
                Available Catalog
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {products.slice(0, 6).map((product) => (
                  <div
                    key={product.id}
                    className="rounded-xl border p-4"
                  >
                    <div className="font-medium">{product.name}</div>

                    <div className="text-xs text-stone-500">
                      {product.sku} · {product.inventory_status}
                    </div>

                    <div className="mt-2 font-semibold">
                      {product.currency} {product.price.toFixed(2)}
                    </div>

                    {product.description && (
                      <div className="mt-1 text-xs text-stone-500">
                        {product.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* ----------------------------------------------------------------- */}
        {/* Saved Recommendation History                                      */}
        {/* ----------------------------------------------------------------- */}

        <Card>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="font-semibold">Saved Recommendations</h2>

              <p className="mt-1 text-xs text-stone-500">
                Previous recommendation requests are persisted for your
                account and organization.
              </p>
            </div>

            <span className="whitespace-nowrap text-xs text-stone-500">
              {recommendationHistory.length} saved
            </span>
          </div>

          {recommendationHistory.length === 0 ? (
            <div className="mt-4 rounded-lg bg-stone-50 p-4 text-sm text-stone-500">
              No recommendation history yet. Run a recommendation above.
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {recommendationHistory.map((item) => (
                <div
                  key={item.recommendation_id}
                  className="rounded-xl border p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="font-medium">{item.query}</div>

                      <div className="mt-1 text-xs text-stone-500">
                        {item.products.length} product
                        {item.products.length === 1 ? "" : "s"} recommended
                      </div>
                    </div>

                    <div className="flex items-center gap-2 text-xs text-stone-400">
                      {new Date(item.created_at).toLocaleString()}
                      {item.products.length > 0 && (
                        <button
                          type="button"
                          onClick={() => void toggleExplanation(item.recommendation_id)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-900"
                        >
                          {explanations[item.recommendation_id]
                            ? "Hide reasons"
                            : "Why these?"}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void deleteRecommendation(item.recommendation_id)}
                        className="rounded-md p-1.5 text-stone-400 hover:bg-red-50 hover:text-red-600"
                        title="Delete saved recommendation"
                        aria-label="Delete saved recommendation"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {explanations[item.recommendation_id] && (
                    <div className="mt-3 rounded-lg border border-stone-200 bg-white p-3">
                      {explanations[item.recommendation_id].loading ? (
                        <div className="flex items-center gap-2 text-xs text-stone-500">
                          <Spinner className="h-3.5 w-3.5" /> Loading reasons…
                        </div>
                      ) : explanations[item.recommendation_id].error ? (
                        <div className="text-xs text-red-600">
                          {explanations[item.recommendation_id].error}
                        </div>
                      ) : explanations[item.recommendation_id].items.length === 0 ? (
                        <div className="text-xs text-stone-500">
                          No specific match reasons were found for this recommendation.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {explanations[item.recommendation_id].items.map((it: any) => (
                            <div key={it.product.id} className="text-xs">
                              <span className="font-medium text-stone-700">
                                {it.product.name}
                              </span>{" "}
                              <span className="text-stone-400">— {it.confidence_label}</span>
                              {it.reasons.length > 0 ? (
                                <ul className="mt-1 ml-4 list-disc space-y-0.5 text-stone-500">
                                  {it.reasons.map((r: any, idx: number) => (
                                    <li key={idx}>
                                      {r.type === "query_match"
                                        ? `Matched your search terms: ${
                                            Array.isArray(r.evidence)
                                              ? r.evidence.join(", ")
                                              : r.evidence
                                          }`
                                        : r.type === "same_category"
                                        ? `Same category you searched: ${r.evidence}`
                                        : `${r.type}: ${r.evidence}`}
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="mt-1 ml-4 text-stone-400">
                                  No specific match reason recorded for this product.
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {item.products.length > 0 ? (
                    <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {item.products.map((product) => (
                        <div
                          key={product.id}
                          className="rounded-lg bg-stone-50 p-3"
                        >
                          <div className="font-medium">
                            {product.name}
                          </div>

                          <div className="mt-1 text-xs text-stone-500">
                            {product.sku} · {product.inventory_status}
                          </div>

                          <div className="mt-2 text-sm font-semibold">
                            {product.currency}{" "}
                            {product.price.toFixed(2)}
                          </div>

                          {product.description && (
                            <div className="mt-1 text-xs text-stone-500">
                              {product.description}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 rounded-lg bg-stone-50 p-3 text-xs text-stone-500">
                      No products matched this recommendation request.
                    </div>
                  )}

                  <div className="mt-3 text-[11px] text-stone-400">
                    Recommendation ID: {item.recommendation_id}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ----------------------------------------------------------------- */}
        {/* Personas + API Keys                                               */}
        {/* ----------------------------------------------------------------- */}

        <div className="grid gap-4 md:grid-cols-2">
          {/* AI Personas */}
          <PersonasPanel
            personas={personas}
            setPersonas={setPersonas}
          />

          {/* API Keys */}
          <Card>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">API Keys</h2>

              <Button
                size="sm"
                onClick={() => {
                  void createKey();
                }}
              >
                Create
              </Button>
            </div>

            {/* One-time secret */}
            {newKey && (
              <div className="mt-3 rounded-lg bg-amber-50 p-3 text-xs break-all text-amber-900">
                <b>Show once:</b> {newKey}
              </div>
            )}

            {keys.length === 0 ? (
              <div className="mt-3 rounded-lg bg-stone-50 p-3 text-sm text-stone-500">
                No API keys created yet.
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {keys.map((key) => (
                  <div
                    key={key.id}
                    className="flex justify-between gap-3 rounded-lg bg-stone-50 p-2 text-xs"
                  >
                    <span>
                      {key.name} · {key.prefix}
                    </span>

                    <span
                      className={
                        key.revoked_at
                          ? "text-red-600"
                          : "text-green-700"
                      }
                    >
                      {key.revoked_at ? "Revoked" : "Active"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* Webhooks                                                          */}
        {/* ----------------------------------------------------------------- */}

        <WebhooksPanel
          webhooks={webhooks}
          setWebhooks={setWebhooks}
        />

        {/* ----------------------------------------------------------------- */}
        {/* Footer                                                            */}
        {/* ----------------------------------------------------------------- */}

      </div>
    </AppShell>
  );
}