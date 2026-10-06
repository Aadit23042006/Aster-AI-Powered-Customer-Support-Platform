"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  Upload,
  RefreshCw,
  Search,
  X,
  Archive,
  Undo2,
  Trash2,
  Send,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, EmptyState, Input, Spinner, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import type { KBDashboard, KBDocument, KBDocumentDetail, KBDocumentStatus, KBIndexStatus } from "@/types/api";

function statusTone(status: KBDocumentStatus) {
  return { draft: "neutral", published: "success", archived: "warning" }[status] as "neutral" | "success" | "warning";
}

function IndexBadge({ status }: { status: KBIndexStatus }) {
  const map: Record<KBIndexStatus, { tone: "neutral" | "success" | "warning" | "danger" | "info"; label: string }> = {
    not_indexed: { tone: "neutral", label: "Not indexed" },
    queued: { tone: "info", label: "Queued" },
    processing: { tone: "info", label: "Processing…" },
    completed: { tone: "success", label: "Indexed" },
    failed: { tone: "danger", label: "Index failed" },
  };
  const { tone, label } = map[status];
  return <Badge tone={tone}>{label}</Badge>;
}

export default function KBPage() {
  const [summary, setSummary] = useState<KBDashboard | null>(null);
  const [docs, setDocs] = useState<KBDocument[] | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reindexingAll, setReindexingAll] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([api.kbSummary(), api.kbList({ status: statusFilter || undefined, search: search || undefined })]);
      setSummary(s);
      setDocs(list.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load knowledge base.");
    }
  }, [statusFilter, search]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
  }, [load]);

  async function handleUpload(file: File) {
    setError(null);
    try {
      const doc = await api.kbUpload(file.name.replace(/\.[^.]+$/, ""), "general", file);
      await load();
      setSelectedId(doc.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    }
  }

  async function handleReindexAll() {
    setReindexingAll(true);
    setError(null);
    try {
      await api.kbReindexAll();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Full re-index failed.");
    } finally {
      setReindexingAll(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-stone-900">Knowledge Base</h1>
            <p className="text-sm text-stone-500">Documents the AI agent can cite as authoritative policy once published and indexed.</p>
          </div>
          <div className="flex gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.markdown,.txt,.pdf,.docx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
                e.target.value = "";
              }}
            />
            <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()}>
              <Upload className="h-4 w-4" /> Upload
            </Button>
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> Create Article
            </Button>
          </div>
        </div>

        {summary && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <StatCard label="Documents" value={summary.documents} />
            <StatCard label="Published" value={summary.published} />
            <StatCard label="Drafts" value={summary.drafts} />
            <StatCard label="Archived" value={summary.archived} />
            <Card className="flex flex-col justify-center gap-1 p-4">
              <span className="text-xs text-stone-500">Index Status</span>
              <div className="flex items-center gap-1.5">
                {summary.index_healthy ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    <span className="text-sm font-medium text-emerald-700">Healthy</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 text-red-600" />
                    <span className="text-sm font-medium text-red-700">{summary.failed_index} failing</span>
                  </>
                )}
              </div>
              {summary.last_indexed_at && <span className="text-[11px] text-stone-400">Last: {formatDateTime(summary.last_indexed_at)}</span>}
            </Card>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <Input placeholder="Search titles…" className="pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>
          <Button variant="secondary" size="sm" onClick={handleReindexAll} disabled={reindexingAll}>
            {reindexingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Re-index all
          </Button>
        </div>

        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        {docs === null && (
          <div className="flex justify-center py-12">
            <Spinner className="h-5 w-5 text-stone-400" />
          </div>
        )}
        {docs?.length === 0 && <EmptyState title="No documents yet" description="Create an article or upload a file to get started." />}

        {docs && docs.length > 0 && (
          <Card className="divide-y divide-stone-100">
            {docs.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-stone-50"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 shrink-0 text-stone-400" />
                    <span className="truncate text-sm font-medium text-stone-900">{d.title}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-stone-400">
                    {d.category} · v{d.current_version} · updated {formatDateTime(d.updated_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={statusTone(d.status)}>{d.status}</Badge>
                  <IndexBadge status={d.index_status} />
                </div>
              </button>
            ))}
          </Card>
        )}
      </div>

      {creating && (
        <CreateDocumentModal
          onClose={() => setCreating(false)}
          onCreated={(doc) => {
            setCreating(false);
            load();
            setSelectedId(doc.id);
          }}
        />
      )}
      {selectedId && (
        <DocumentDrawer
          id={selectedId}
          onClose={() => setSelectedId(null)}
          onChanged={load}
          onDeleted={() => {
            setSelectedId(null);
            load();
          }}
        />
      )}
    </AppShell>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-stone-900">{value}</div>
    </Card>
  );
}

function CreateDocumentModal({ onClose, onCreated }: { onClose: () => void; onCreated: (doc: KBDocumentDetail) => void }) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("general");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const doc = await api.kbCreate({ title, category, content, content_type: "markdown" });
      onCreated(doc);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create document.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <Card className="w-full max-w-lg p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-stone-900">Create Article</h2>
          <button onClick={onClose}>
            <X className="h-4 w-4 text-stone-400" />
          </button>
        </div>
        <div className="space-y-3">
          <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <Input placeholder="Category (e.g. shipping, returns)" value={category} onChange={(e) => setCategory(e.target.value)} />
          <Textarea placeholder="Markdown content…" rows={10} value={content} onChange={(e) => setContent(e.target.value)} />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={submit} disabled={saving || !title.trim() || !content.trim()}>
              {saving ? <Spinner className="h-4 w-4" /> : "Create draft"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function DocumentDrawer({
  id,
  onClose,
  onChanged,
  onDeleted,
}: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [doc, setDoc] = useState<KBDocumentDetail | null>(null);
  const [editedContent, setEditedContent] = useState("");
  const [editedTitle, setEditedTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const d = await api.kbGet(id);
    setDoc(d);
    setEditedContent(d.content);
    setEditedTitle(d.title);
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    load();
  }, [load]);

  async function withBusy(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!doc) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
        <Spinner className="h-5 w-5 text-white" />
      </div>
    );
  }

  const contentDirty = editedContent !== doc.content;
  const titleDirty = editedTitle !== doc.title;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <div className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white p-5 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-2">
          <div className="flex-1">
            <Input value={editedTitle} onChange={(e) => setEditedTitle(e.target.value)} className="text-base font-semibold" />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge tone={statusTone(doc.status)}>{doc.status}</Badge>
              <IndexBadge status={doc.index_status} />
              <span className="text-xs text-stone-400">v{doc.current_version} · {doc.versions.length} version{doc.versions.length !== 1 ? "s" : ""}</span>
            </div>
          </div>
          <button onClick={onClose}>
            <X className="h-5 w-5 text-stone-400" />
          </button>
        </div>

        {doc.index_status === "failed" && doc.index_error && (
          <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">Index error: {doc.index_error}</div>
        )}
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <Textarea rows={16} value={editedContent} onChange={(e) => setEditedContent(e.target.value)} className="font-mono text-xs" />

        <div className="mt-3 flex flex-wrap gap-2">
          {(contentDirty || titleDirty) && (
            <Button
              size="sm"
              onClick={() =>
                withBusy(() =>
                  api.kbUpdate(doc.id, {
                    title: titleDirty ? editedTitle : undefined,
                    category: undefined,
                    content: contentDirty ? editedContent : undefined,
                    content_type: contentDirty ? doc.content_type : undefined,
                  })
                )
              }
              disabled={busy}
            >
              <Send className="h-4 w-4" /> Save {contentDirty ? "(new version)" : ""}
            </Button>
          )}
          {doc.status === "draft" && (
            <Button size="sm" variant="secondary" onClick={() => withBusy(() => api.kbPublish(doc.id))} disabled={busy}>
              Publish
            </Button>
          )}
          {doc.status === "published" && (
            <Button size="sm" variant="secondary" onClick={() => withBusy(() => api.kbUnpublish(doc.id))} disabled={busy}>
              Unpublish
            </Button>
          )}
          {doc.status !== "archived" && (
            <Button size="sm" variant="secondary" onClick={() => withBusy(() => api.kbArchive(doc.id))} disabled={busy}>
              <Archive className="h-4 w-4" /> Archive
            </Button>
          )}
          {doc.status === "archived" && (
            <Button size="sm" variant="secondary" onClick={() => withBusy(() => api.kbRestore(doc.id))} disabled={busy}>
              <Undo2 className="h-4 w-4" /> Restore to draft
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={() => withBusy(() => api.kbReindex(doc.id))} disabled={busy}>
            <RefreshCw className={cn("h-4 w-4", busy && "animate-spin")} /> Re-index
          </Button>
          {doc.status !== "published" && (
            <Button
              size="sm"
              variant="danger"
              onClick={() =>
                withBusy(async () => {
                  await api.kbDelete(doc.id);
                  onDeleted();
                })
              }
              disabled={busy}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          )}
        </div>

        <div className="mt-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">Version history</h3>
          <ul className="space-y-1">
            {doc.versions.map((v) => (
              <li key={v.id} className="flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => {
                    window.location.href = `/kb/${doc.id}/versions?from_version=${v.version}`;
                  }}
                  className="rounded px-1 py-1 text-left text-stone-600 underline-offset-2 hover:bg-stone-50 hover:text-stone-900 hover:underline"
                  title={`Open version history for v${v.version}`}
                >
                  v{v.version} {v.source_filename ? `· ${v.source_filename}` : ""} ({v.content_type})
                </button>
                <span className="text-stone-500">{formatDateTime(v.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}



