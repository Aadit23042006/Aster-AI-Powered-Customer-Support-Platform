"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";

export default function PromptManagement() {
  const [rows, setRows] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [test, setTest] = useState("");
  const [out, setOut] = useState<any>(null);

  // Prompt version creation
  const [newVersionContent, setNewVersionContent] = useState("");
  const [versionBusy, setVersionBusy] = useState(false);
  const [versionErr, setVersionErr] = useState("");

  // Draft version edit/delete actions
  const [editingVersion, setEditingVersion] = useState<number | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [versionActionBusy, setVersionActionBusy] = useState<number | null>(null);
  const [versionActionErr, setVersionActionErr] = useState("");

  // A/B experiments
  const [experiments, setExperiments] = useState<any[]>([]);
  const [expName, setExpName] = useState("");
  const [vA, setVA] = useState(1);
  const [vB, setVB] = useState(2);
  const [split, setSplit] = useState(50);
  const [expErr, setExpErr] = useState("");
  const [expBusy, setExpBusy] = useState(false);

  const load = () =>
    api.prompts()
      .then(setRows)
      .catch(() => {});

  useEffect(() => {
    load();
  }, []);

  // Create a completely new prompt
  async function create() {
    if (!name.trim() || !content.trim()) {
      return;
    }

    await api.createPrompt({
      name,
      content,
    });

    setName("");
    setContent("");

    load();
  }

  // Open prompt details
  function openPrompt(p: any) {
    api.promptDetail(p.id).then((detail) => {
      setSelected(detail);

      const versions = detail?.versions || [];

      const activeVersion =
        versions.find(
          (v: any) =>
            v.version === detail.active_version
        ) || versions[versions.length - 1];

      // Pre-fill the version editor with the
      // currently active version.
      if (activeVersion) {
        setNewVersionContent(
          activeVersion.content || ""
        );
      } else {
        setNewVersionContent("");
      }
    });

    api.experiments(p.id)
      .then(setExperiments)
      .catch(() => setExperiments([]));

    setVersionErr("");
    setOut(null);
  }

  // Create the next prompt version
  async function createVersion() {
    if (!selected) {
      return;
    }

    if (!newVersionContent.trim()) {
      setVersionErr(
        "Version content cannot be empty."
      );
      return;
    }

    setVersionBusy(true);
    setVersionErr("");

    try {
      await api.createPromptVersion(
        selected.id,
        newVersionContent
      );

      // Refresh prompt details so the newly-created
      // version immediately appears in the UI.
      const detail = await api.promptDetail(
        selected.id
      );

      setSelected(detail);

      // Clear editor after successful creation.
      setNewVersionContent("");

      // Refresh prompt list so active_version is current.
      load();
    } catch (e: any) {
      setVersionErr(
        e?.message ||
          "Could not create prompt version."
      );
    } finally {
      setVersionBusy(false);
    }
  }

  function startEditVersion(v: any) {
    if (!selected || v.status === "production" || v.status === "published") return;
    setVersionActionErr("");
    setEditingVersion(v.version);
    setEditingContent(v.content || "");
  }

  function cancelEditVersion() {
    setEditingVersion(null);
    setEditingContent("");
    setVersionActionErr("");
  }

  async function saveVersion() {
    if (!selected || editingVersion === null) return;
    if (!editingContent.trim()) {
      setVersionActionErr("Version content cannot be empty.");
      return;
    }

    setVersionActionBusy(editingVersion);
    setVersionActionErr("");
    try {
      await api.updatePromptVersion(selected.id, editingVersion, editingContent);
      const detail = await api.promptDetail(selected.id);
      setSelected(detail);
      setEditingVersion(null);
      setEditingContent("");
      load();
    } catch (e: any) {
      setVersionActionErr(e?.message || "Could not update prompt version.");
    } finally {
      setVersionActionBusy(null);
    }
  }

  async function rollbackVersion(version: number) {
    if (!selected) return;

    const target = (selected.versions || []).find(
      (v: any) => v.version === version
    );

    if (!target || target.status === "production" || target.status === "published") {
      return;
    }

    if (
      !window.confirm(
        `Rollback prompt to v${version}? The selected historical version will become production, the current production version will be archived, and no version will be deleted.`
      )
    ) {
      return;
    }

    setVersionActionBusy(version);
    setVersionActionErr("");

    try {
      await api.rollbackPrompt(selected.id, version);

      const detail = await api.promptDetail(selected.id);
      setSelected(detail);
      load();
    } catch (e: any) {
      setVersionActionErr(
        e?.message ||
          "Could not rollback prompt version."
      );
    } finally {
      setVersionActionBusy(null);
    }
  }

  async function deleteVersion(version: number) {
    if (!selected) return;
    const target = (selected.versions || []).find((v: any) => v.version === version);
    if (!target || target.status === "production" || target.status === "published") return;
    if (!window.confirm(`Delete draft version v${version}? This cannot be undone.`)) return;

    setVersionActionBusy(version);
    setVersionActionErr("");
    try {
      await api.deletePromptVersion(selected.id, version);
      const detail = await api.promptDetail(selected.id);
      setSelected(detail);
      load();
      if (editingVersion === version) cancelEditVersion();
    } catch (e: any) {
      setVersionActionErr(e?.message || "Could not delete prompt version.");
    } finally {
      setVersionActionBusy(null);
    }
  }

  // Create A/B experiment
  async function createExperiment() {
    if (!selected) {
      return;
    }

    setExpBusy(true);
    setExpErr("");

    try {
      await api.createExperiment(
        selected.id,
        {
          name: expName,
          variant_a_version: vA,
          variant_b_version: vB,
          traffic_split_b: split,
        }
      );

      setExpName("");

      const updated =
        await api.experiments(
          selected.id
        );

      setExperiments(updated);
    } catch (e: any) {
      setExpErr(
        e?.message ||
          "Could not create the experiment."
      );
    } finally {
      setExpBusy(false);
    }
  }

  // Stop A/B experiment
  async function stopExperiment(
    id: string
  ) {
    if (!selected) {
      return;
    }

    await api.stopExperiment(
      selected.id,
      id
    );

    const updated =
      await api.experiments(
        selected.id
      );

    setExperiments(updated);
  }

  // Publish a specific prompt version
  async function publishVersion(
    version: number
  ) {
    if (!selected) {
      return;
    }

    await api.publishPrompt(
      selected.id,
      version
    );

    const detail =
      await api.promptDetail(
        selected.id
      );

    setSelected(detail);

    load();
  }

  // Test currently active prompt
  async function testPrompt() {
    if (!selected) {
      return;
    }

    try {
      const result =
        await api.testPrompt(
          selected.id,
          test ? { input: test } : {}
        );

      setOut(result);
    } catch (e: any) {
      setOut({
        error:
          e?.message ||
          "Prompt test failed.",
      });
    }
  }

  const nextVersion =
    (selected?.versions?.length || 0) + 1;

  return (
    <AppShell>
      <main className="p-6 space-y-5">

        {/* PAGE HEADER */}
        <div>
          <h1 className="text-2xl font-semibold">
            Prompt Management
          </h1>

          <p className="text-sm text-stone-500">
            Version, test, publish and safely roll back
            production prompts.
          </p>
        </div>

        {/* CREATE PROMPT + PROMPT LIST */}
        <div className="grid gap-4 md:grid-cols-2">

          {/* CREATE PROMPT */}
          <div className="rounded-xl border bg-white p-4 space-y-3">
            <h2 className="font-semibold">
              Create prompt
            </h2>

            <input
              value={name}
              onChange={(e) =>
                setName(e.target.value)
              }
              placeholder="Prompt name"
              className="w-full rounded-lg border p-2"
            />

            <textarea
              value={content}
              onChange={(e) =>
                setContent(e.target.value)
              }
              placeholder="Use {{variables}}"
              className="min-h-40 w-full rounded-lg border p-2"
            />

            <button
              onClick={create}
              disabled={
                !name.trim() ||
                !content.trim()
              }
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              Create
            </button>
          </div>

          {/* PROMPTS */}
          <div className="rounded-xl border bg-white p-4">
            <h2 className="font-semibold">
              Prompts
            </h2>

            <div className="mt-3 space-y-2">
              {rows.length === 0 ? (
                <p className="text-sm text-stone-500">
                  No prompts found.
                </p>
              ) : (
                rows.map((p) => (
                  <button
                    key={p.id}
                    onClick={() =>
                      openPrompt(p)
                    }
                    className="block w-full rounded-lg border p-3 text-left hover:bg-stone-50"
                  >
                    <div className="font-medium">
                      {p.name}
                    </div>

                    <div className="text-xs text-stone-500">
                      Active v
                      {p.active_version}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        {/* SELECTED PROMPT */}
        {selected && (
          <section className="rounded-xl border bg-white p-5">

            <h2 className="font-semibold">
              {selected.name}
            </h2>

            {/* CREATE NEW VERSION */}
            <div className="mt-5 rounded-lg border bg-stone-50 p-4">

              <h3 className="font-semibold">
                Create new version
              </h3>

              <p className="mt-1 text-xs text-stone-500">
                Create a new draft version without
                modifying any existing version.
              </p>

              {versionErr && (
                <div
                  role="alert"
                  className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700"
                >
                  {versionErr}
                </div>
              )}

              <div className="mt-3">
                <label className="text-sm font-medium">
                  Version content
                </label>

                <textarea
                  value={newVersionContent}
                  onChange={(e) =>
                    setNewVersionContent(
                      e.target.value
                    )
                  }
                  placeholder="Enter the new prompt version content"
                  className="mt-1 min-h-40 w-full rounded-lg border bg-white p-3 text-sm"
                />
              </div>

              <div className="mt-3 flex items-center gap-3">

                <button
                  disabled={
                    versionBusy ||
                    !newVersionContent.trim()
                  }
                  onClick={createVersion}
                  className="rounded-lg bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-50"
                >
                  {versionBusy
                    ? "Creating..."
                    : `Create v${nextVersion}`}
                </button>

                <span className="text-xs text-stone-500">
                  Next version: v
                  {nextVersion}
                </span>
              </div>
            </div>

            {/* EXISTING VERSIONS */}
            <div className="mt-5">

              <h3 className="font-semibold">
                Versions
              </h3>

              <div className="mt-3 space-y-2">

                {(selected.versions || []).length ===
                0 ? (
                  <p className="text-sm text-stone-500">
                    No versions found.
                  </p>
                ) : (
                  (selected.versions || []).map(
                    (v: any) => (
                      <div
                        key={v.id}
                        className="rounded-lg border p-3"
                      >

                        {/* VERSION HEADER */}
                        <div className="flex justify-between">

                          <b>
                            v{v.version}
                          </b>

                          <span
                            className={
                              v.status ===
                              "published"
                                ? "text-emerald-700"
                                : "text-stone-500"
                            }
                          >
                            {v.status}
                          </span>

                        </div>

                        {/* VERSION CONTENT */}
                        {editingVersion === v.version ? (
                          <div className="mt-2">
                            <textarea
                              value={editingContent}
                              onChange={(e) => setEditingContent(e.target.value)}
                              rows={7}
                              className="w-full rounded border p-2 text-sm"
                            />
                            {versionActionErr && (
                              <div role="alert" className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700">
                                {versionActionErr}
                              </div>
                            )}
                            <div className="mt-2 flex gap-2">
                              <button
                                onClick={saveVersion}
                                disabled={versionActionBusy === v.version || !editingContent.trim()}
                                className="rounded bg-stone-900 px-3 py-1 text-sm text-white disabled:opacity-50"
                              >
                                {versionActionBusy === v.version ? "Saving..." : "Save"}
                              </button>
                              <button
                                onClick={cancelEditVersion}
                                disabled={versionActionBusy === v.version}
                                className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <p className="mt-2 whitespace-pre-wrap text-sm">
                            {v.content}
                          </p>
                        )}

                        {/* VERSION ACTIONS */}
                        <div className="mt-3 flex flex-wrap gap-2">
                          {v.status !== "production" && v.status !== "published" && editingVersion !== v.version && (
                            <>
                              <button
                                onClick={() => startEditVersion(v)}
                                disabled={versionActionBusy === v.version}
                                className="rounded border px-3 py-1 text-sm hover:bg-stone-50 disabled:opacity-50"
                              >
                                Edit
                              </button>
                              <button
                                onClick={() => deleteVersion(v.version)}
                                disabled={versionActionBusy === v.version}
                                className="rounded border px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
                              >
                                {versionActionBusy === v.version ? "Deleting..." : "Delete"}
                              </button>
                            </>
                          )}

                          {v.status !== "production" && v.status !== "published" && (
                            <>
                              <button
                                onClick={() => publishVersion(v.version)}
                                disabled={versionActionBusy === v.version}
                                className="rounded border px-3 py-1 text-sm hover:bg-stone-50 disabled:opacity-50"
                              >
                                Publish
                              </button>

                              <button
                                onClick={() => rollbackVersion(v.version)}
                                disabled={versionActionBusy === v.version}
                                className="rounded border border-amber-300 px-3 py-1 text-sm text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                              >
                                {versionActionBusy === v.version
                                  ? "Rolling back..."
                                  : "Rollback"}
                              </button>
                            </>
                          )}

                          <button
                            onClick={testPrompt}
                            className="rounded border px-3 py-1 text-sm hover:bg-stone-50"
                          >
                            Test active
                          </button>
                        </div>
                      </div>
                    )
                  )
                )}

              </div>
            </div>

            {/* PROMPT TEST INPUT */}
            <div className="mt-4">

              <label className="text-sm font-medium">
                Test input
              </label>

              <input
                value={test}
                onChange={(e) =>
                  setTest(e.target.value)
                }
                placeholder='JSON-like variable value, e.g. "30 days"'
                className="mt-1 w-full rounded border p-2"
              />

            </div>

            {/* TEST OUTPUT */}
            {out && (
              <pre className="mt-3 overflow-auto rounded bg-stone-50 p-3 text-xs">
                {JSON.stringify(
                  out,
                  null,
                  2
                )}
              </pre>
            )}

            {/* A/B EXPERIMENTS */}
            <div className="mt-6 border-t pt-4">

              <h3 className="font-semibold">
                A/B experiments
              </h3>

              <p className="text-xs text-stone-500">
                Split traffic between two versions.
                Only one running experiment per
                prompt at a time.
              </p>

              {/* EXPERIMENT ERROR */}
              {expErr && (
                <div
                  role="alert"
                  className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700"
                >
                  {expErr}
                </div>
              )}

              {/* EXPERIMENT FORM */}
              <div className="mt-3 flex flex-wrap items-end gap-2 text-sm">

                <label className="flex flex-col">
                  Name

                  <input
                    value={expName}
                    onChange={(e) =>
                      setExpName(
                        e.target.value
                      )
                    }
                    className="rounded border p-1.5"
                  />
                </label>

                <label className="flex flex-col">
                  Version A

                  <input
                    type="number"
                    min={1}
                    value={vA}
                    onChange={(e) =>
                      setVA(
                        Number(
                          e.target.value
                        )
                      )
                    }
                    className="w-20 rounded border p-1.5"
                  />
                </label>

                <label className="flex flex-col">
                  Version B

                  <input
                    type="number"
                    min={1}
                    value={vB}
                    onChange={(e) =>
                      setVB(
                        Number(
                          e.target.value
                        )
                      )
                    }
                    className="w-20 rounded border p-1.5"
                  />
                </label>

                <label className="flex flex-col">
                  % to B

                  <input
                    type="number"
                    min={1}
                    max={99}
                    value={split}
                    onChange={(e) =>
                      setSplit(
                        Number(
                          e.target.value
                        )
                      )
                    }
                    className="w-20 rounded border p-1.5"
                  />
                </label>

                <button
                  disabled={
                    !expName.trim() ||
                    expBusy
                  }
                  onClick={
                    createExperiment
                  }
                  className="rounded bg-stone-900 px-3 py-1.5 text-white disabled:opacity-50"
                >
                  {expBusy
                    ? "Starting..."
                    : "Start experiment"}
                </button>

              </div>

              {/* EXPERIMENT LIST */}
              {experiments.length === 0 ? (
                <p className="mt-3 text-sm text-stone-500">
                  No experiments yet for this
                  prompt.
                </p>
              ) : (
                <ul className="mt-3 space-y-2">

                  {experiments.map(
                    (e) => (
                      <li
                        key={e.id}
                        className="rounded-lg border p-3 text-sm"
                      >

                        <div className="flex items-center justify-between">

                          <b>
                            {e.name}
                          </b>

                          <span
                            className={`rounded px-2 py-0.5 text-xs ${
                              e.status ===
                              "running"
                                ? "bg-emerald-50 text-emerald-700"
                                : "bg-stone-100 text-stone-600"
                            }`}
                          >
                            {e.status}
                          </span>

                        </div>

                        <div className="text-xs text-stone-500">
                          A: v
                          {
                            e.variant_a_version
                          }

                          {" · "}

                          B: v
                          {
                            e.variant_b_version
                          }

                          {" ("}

                          {
                            e.traffic_split_b
                          }

                          % to B)
                        </div>

                        {e.status ===
                          "running" && (
                          <button
                            onClick={() =>
                              stopExperiment(
                                e.id
                              )
                            }
                            className="mt-2 rounded border px-2 py-1 text-xs hover:bg-stone-50"
                          >
                            Stop
                          </button>
                        )}

                      </li>
                    )
                  )}

                </ul>
              )}

            </div>
          </section>
        )}

      </main>
    </AppShell>
  );
}