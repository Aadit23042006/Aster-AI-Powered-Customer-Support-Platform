"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";

type VersionRow = {
  id: string;
  version: number;
  status: string;
  created_at: string;
  content?: string;
  content_type?: string;
};

type DiffResult = {
  document_id: string;
  from_version: number;
  to_version: number;
  diff: string[];
};

export default function KBVersions() {
  const { id } = useParams<{ id: string }>();

  const [rows, setRows] = useState<VersionRow[]>([]);
  const [diff, setDiff] = useState<DiffResult | null>(null);

  const [loading, setLoading] = useState(true);
  const [diffLoading, setDiffLoading] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [busy, setBusy] = useState("");

  const [fromVersion, setFromVersion] = useState<number | "">("");
  const [toVersion, setToVersion] = useState<number | "">("");

  const load = useCallback(() => {
    if (!id) return;

    setLoading(true);
    setError("");

    api
      .enterpriseKBVersions(id)
      .then((x) => {
        const items = (x.items || []) as VersionRow[];

        const sorted = [...items].sort(
          (a, b) => Number(a.version) - Number(b.version)
        );

        setRows(sorted);

        if (sorted.length >= 2) {
          setFromVersion(sorted[0].version);
          setToVersion(sorted[1].version);
        } else if (sorted.length === 1) {
          setFromVersion(sorted[0].version);
          setToVersion("");
        }
      })
      .catch((e) =>
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not load versions."
        )
      )
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function act(
    label: string,
    versionId: string,
    fn: () => Promise<any>,
    success: string
  ) {
    setBusy(label + versionId);
    setError("");
    setNotice("");

    try {
      await fn();
      setNotice(success);
      load();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "That action failed."
      );
    } finally {
      setBusy("");
    }
  }

  async function viewDiff() {
    setError("");
    setNotice("");
    setDiff(null);

    if (fromVersion === "" || toVersion === "") {
      setError("Select both From Version and To Version.");
      return;
    }

    if (fromVersion === toVersion) {
      setError("From Version and To Version must be different.");
      return;
    }

    if (!id) {
      setError("Document ID is missing.");
      return;
    }

    setDiffLoading(true);

    try {
      const result = await api.enterpriseKBDiff(
        id,
        Number(fromVersion),
        Number(toVersion)
      );

      setDiff(result as DiffResult);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not load diff."
      );
    } finally {
      setDiffLoading(false);
    }
  }

  return (
    <AppShell>
      <main className="space-y-5 p-6">
        <div>
          <h1 className="text-2xl font-semibold">
            Knowledge Base Version History
          </h1>

          <p className="text-sm text-stone-500">
            Draft, published and archived versions. Historical versions
            are never deleted; rollback and restore create a new
            published version.
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700"
          >
            {notice}
          </div>
        )}

        {loading ? (
          <div
            role="status"
            className="p-4 text-sm text-stone-500"
          >
            Loading versions...
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-xl border bg-white p-6 text-sm text-stone-500">
            No versions yet for this document.
          </div>
        ) : (
          <>
            <div className="rounded-xl border bg-white p-4">
              <h2 className="mb-4 text-lg font-semibold">
                Compare Versions
              </h2>

              <div className="grid gap-4 md:grid-cols-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-stone-700">
                    From Version
                  </span>

                  <select
                    value={fromVersion}
                    onChange={(e) => {
                      setFromVersion(
                        e.target.value === ""
                          ? ""
                          : Number(e.target.value)
                      );
                      setDiff(null);
                    }}
                    className="rounded-lg border px-3 py-2"
                  >
                    <option value="">
                      Select version
                    </option>

                    {rows.map((v) => (
                      <option
                        key={`from-${v.version}`}
                        value={v.version}
                      >
                        v{v.version} ({v.status})
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-stone-700">
                    To Version
                  </span>

                  <select
                    value={toVersion}
                    onChange={(e) => {
                      setToVersion(
                        e.target.value === ""
                          ? ""
                          : Number(e.target.value)
                      );
                      setDiff(null);
                    }}
                    className="rounded-lg border px-3 py-2"
                  >
                    <option value="">
                      Select version
                    </option>

                    {rows.map((v) => (
                      <option
                        key={`to-${v.version}`}
                        value={v.version}
                      >
                        v{v.version} ({v.status})
                      </option>
                    ))}
                  </select>
                </label>

                <div className="flex items-end">
                  <button
                    type="button"
                    onClick={viewDiff}
                    disabled={
                      diffLoading ||
                      fromVersion === "" ||
                      toVersion === ""
                    }
                    className="w-full rounded-lg border bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {diffLoading
                      ? "Loading Diff..."
                      : "View Diff"}
                  </button>
                </div>
              </div>
            </div>

            <div className="rounded-xl border bg-white">
              <div className="border-b p-4">
                <h2 className="text-lg font-semibold">
                  Version History
                </h2>
              </div>

              <div className="divide-y">
                {rows.map((v) => {
                  const key = String(v.id);

                  return (
                    <div
                      key={key}
                      className="flex flex-wrap items-center justify-between gap-3 p-4"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setToVersion(v.version);
                          setDiff(null);
                        }}
                        className="text-left"
                      >
                        <div className="flex items-center gap-2">
                          <b>v{v.version}</b>

                          <span
                            className={`rounded-full px-2 py-1 text-xs ${
                              v.status === "published"
                                ? "bg-emerald-50 text-emerald-700"
                                : v.status === "archived"
                                  ? "bg-stone-200 text-stone-600"
                                  : "bg-amber-50 text-amber-700"
                            }`}
                          >
                            {v.status}
                          </span>
                        </div>

                        <div className="text-xs text-stone-500">
                          {new Date(
                            v.created_at
                          ).toLocaleString()}
                        </div>
                      </button>

                      <div className="flex flex-wrap gap-2">
                        {v.status !== "published" && (
                          <button
                            disabled={
                              busy === `publish${key}`
                            }
                            onClick={() =>
                              act(
                                "publish",
                                key,
                                () =>
                                  api.enterpriseKBPublish(
                                    id,
                                    key
                                  ),
                                "Version published."
                              )
                            }
                            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                          >
                            {busy === `publish${key}`
                              ? "Publishing..."
                              : "Publish"}
                          </button>
                        )}

                        {v.status === "published" && (
                          <button
                            disabled={
                              busy === `archive${key}`
                            }
                            onClick={() =>
                              act(
                                "archive",
                                key,
                                () =>
                                  api.enterpriseKBArchive(
                                    id,
                                    key
                                  ),
                                "Version archived."
                              )
                            }
                            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                          >
                            {busy === `archive${key}`
                              ? "Archiving..."
                              : "Archive"}
                          </button>
                        )}

                        {v.status === "archived" && (
                          <button
                            disabled={
                              busy === `restore${key}`
                            }
                            onClick={() =>
                              act(
                                "restore",
                                key,
                                () =>
                                  api.enterpriseKBRestore(
                                    id,
                                    key
                                  ),
                                "Version restored."
                              )
                            }
                            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                          >
                            {busy === `restore${key}`
                              ? "Restoring..."
                              : "Restore"}
                          </button>
                        )}

                        <button
                          disabled={
                            busy === `rollback${key}`
                          }
                          onClick={() =>
                            act(
                              "rollback",
                              key,
                              () =>
                                api.enterpriseKBRollback(
                                  id,
                                  key
                                ),
                              "Rolled back to this version."
                            )
                          }
                          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                        >
                          {busy === `rollback${key}`
                            ? "Rolling back..."
                            : "Rollback"}
                        </button>

                        <button
                          type="button"
                          onClick={() => {
                            if (
                              fromVersion === ""
                            ) {
                              setFromVersion(
                                v.version
                              );
                            } else {
                              setToVersion(
                                v.version
                              );
                            }

                            setDiff(null);
                          }}
                          className="rounded border px-3 py-1 text-sm"
                        >
                          Select
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {diff && (
          <div className="rounded-xl border bg-white">
            <div className="border-b p-4">
              <h2 className="font-semibold">
                Diff: v{diff.from_version} → v
                {diff.to_version}
              </h2>
            </div>

            <pre className="max-h-[32rem] overflow-auto p-4 text-xs leading-6">
              {diff.diff.join("\n")}
            </pre>
          </div>
        )}
      </main>
    </AppShell>
  );
}
