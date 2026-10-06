"use client";

import { useState } from "react";
import { Badge, Button, Card, Input, Spinner, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { Phase4Persona } from "@/types/api";
import { CompactEmpty, describeError, Field, Modal, NoticeBanner, useNotice } from "./common";

// The backend accepts free-text values for these; the lists are only suggestions.
const SUGGEST: Record<string, string[]> = {
  tone: ["friendly", "professional", "empathetic", "playful"],
  style: ["professional", "conversational", "concise"],
  formality: ["casual", "neutral", "formal"],
  response_length: ["concise", "balanced", "detailed"],
};
const LANGUAGES: Record<string, string> = { en: "English", hi: "Hindi", es: "Spanish", fr: "French", de: "German" };

interface PersonaForm {
  name: string;
  description: string;
  tone: string;
  style: string;
  formality: string;
  response_length: string;
  language: string;
  brand_voice: string;
  greeting: string;
  closing: string;
  custom_instructions: string;
}

function toForm(p?: Phase4Persona): PersonaForm {
  return {
    name: p?.name ?? "",
    description: p?.description ?? "",
    tone: p?.tone ?? "friendly",
    style: p?.style ?? "professional",
    formality: p?.formality ?? "neutral",
    response_length: p?.response_length ?? "concise",
    language: p?.language ?? "en",
    brand_voice: p?.brand_voice ?? "",
    greeting: p?.greeting ?? "",
    closing: p?.closing ?? "",
    custom_instructions: p?.custom_instructions ?? "",
  };
}

// PATCH replaces every field on the backend (PersonaPatch == PersonaCreate), so we always send the full set.
// Optional text fields become null when blank; required-with-default fields are omitted when blank so the
// backend default applies.
function toPayload(f: PersonaForm): Record<string, unknown> {
  const nullable = (v: string) => (v.trim() ? v.trim() : null);
  const payload: Record<string, unknown> = {
    name: f.name.trim(),
    description: nullable(f.description),
    brand_voice: nullable(f.brand_voice),
    greeting: nullable(f.greeting),
    closing: nullable(f.closing),
    custom_instructions: nullable(f.custom_instructions),
  };
  for (const k of ["tone", "style", "formality", "response_length", "language"] as const) {
    if (f[k].trim()) payload[k] = f[k].trim();
  }
  return payload;
}

function PersonaFormModal({
  persona,
  onClose,
  onSubmit,
}: {
  persona?: Phase4Persona;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<string | null>;
}) {
  const [form, setForm] = useState<PersonaForm>(() => toForm(persona));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof PersonaForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    const err = await onSubmit(toPayload(form));
    if (err) {
      setError(err);
      setBusy(false);
    }
  }

  const languageOptions = LANGUAGES[form.language] ? LANGUAGES : { ...LANGUAGES, [form.language]: form.language };

  return (
    <Modal title={persona ? "Edit persona" : "Create persona"} onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="space-y-3">
        {error && (
          <div role="alert" className="rounded-lg bg-red-50 p-2.5 text-xs text-red-700">
            {error}
          </div>
        )}
        <Field label="Name">
          <Input value={form.name} onChange={set("name")} required autoFocus disabled={busy} />
        </Field>
        <Field label="Description">
          <Input value={form.description} onChange={set("description")} disabled={busy} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["tone", "style", "formality", "response_length"] as const).map((k) => (
            <Field key={k} label={k === "response_length" ? "Response length" : k[0].toUpperCase() + k.slice(1)}>
              <Input value={form[k]} onChange={set(k)} list={`persona-${k}`} disabled={busy} />
              <datalist id={`persona-${k}`}>
                {SUGGEST[k].map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
            </Field>
          ))}
          <Field label="Language">
            <select
              value={form.language}
              onChange={set("language")}
              disabled={busy}
              className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            >
              {Object.entries(languageOptions).map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Brand voice">
          <Input value={form.brand_voice} onChange={set("brand_voice")} disabled={busy} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Greeting">
            <Input value={form.greeting} onChange={set("greeting")} disabled={busy} />
          </Field>
          <Field label="Closing">
            <Input value={form.closing} onChange={set("closing")} disabled={busy} />
          </Field>
        </div>
        <Field label="Custom instructions" hint="Persona text that tries to override safety rules is rejected by the server.">
          <Textarea rows={4} value={form.custom_instructions} onChange={set("custom_instructions")} disabled={busy} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !form.name.trim()}>
            {busy && <Spinner className="h-4 w-4" />}
            {persona ? "Save changes" : "Create"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function PersonasPanel({
  personas,
  setPersonas,
}: {
  personas: Phase4Persona[];
  setPersonas: (p: Phase4Persona[]) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Phase4Persona | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const notice = useNotice();

  async function refresh(): Promise<boolean> {
    setRefreshing(true);
    try {
      setPersonas(await api.phase4Personas());
      return true;
    } catch (e) {
      notice.showError(describeError(e, "refresh personas"));
      return false;
    } finally {
      setRefreshing(false);
    }
  }

  // Returns an error message for the modal to show, or null on success (modal closes).
  async function save(payload: Record<string, unknown>, target: Phase4Persona | null): Promise<string | null> {
    try {
      const saved = target ? await api.phase4UpdatePersona(target.id, payload) : await api.phase4CreatePersona(payload);
      setCreating(false);
      setEditing(null);
      if (await refresh()) notice.showSuccess(target ? `Saved changes to "${saved.name}".` : `Created persona "${saved.name}" as a draft.`);
      return null;
    } catch (e) {
      return describeError(e, target ? "edit personas" : "create personas");
    }
  }

  async function publish(p: Phase4Persona) {
    setPublishingId(p.id);
    notice.clear();
    try {
      const updated = await api.phase4PublishPersona(p.id);
      if (await refresh()) notice.showSuccess(`"${updated.name}" is now ${updated.status}.`);
    } catch (e) {
      notice.showError(describeError(e, "publish personas"));
    } finally {
      setPublishingId(null);
    }
  }

  const createButton = (
    <Button size="sm" onClick={() => setCreating(true)}>
      + Create Persona
    </Button>
  );

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">AI Personas</h2>
        <div className="flex items-center gap-3">
          {refreshing && <Spinner className="h-4 w-4 text-stone-400" />}
          <span className="text-xs text-stone-500">{personas.length}</span>
          {createButton}
        </div>
      </div>
      <NoticeBanner success={notice.success} error={notice.error} />
      {personas.length === 0 ? (
        <CompactEmpty title="No AI personas yet." action={createButton} />
      ) : (
        <div className="mt-3 space-y-2">
          {personas.map((p) => {
            const published = p.status === "published";
            return (
              <div key={p.id} className="rounded-lg bg-stone-50 p-3 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{p.name}</span>
                      <Badge tone={published ? "success" : "warning"}>{p.status}</Badge>
                    </div>
                    <div className="mt-0.5 text-xs text-stone-500">
                      {[p.tone, p.style].filter(Boolean).join(" / ")}
                      {p.response_length ? ` · ${p.response_length} responses` : ""} · v{p.active_version}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(p)} disabled={publishingId === p.id}>
                      Edit
                    </Button>
                    {!published && (
                      <Button size="sm" onClick={() => publish(p)} disabled={publishingId !== null}>
                        {publishingId === p.id && <Spinner className="h-4 w-4" />}
                        Publish
                      </Button>
                    )}
                  </div>
                </div>
                {p.custom_instructions && (
                  <p className="mt-2 line-clamp-3 whitespace-pre-line text-xs text-stone-600" title={p.custom_instructions}>
                    {p.custom_instructions}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
      {creating && <PersonaFormModal onClose={() => setCreating(false)} onSubmit={(pl) => save(pl, null)} />}
      {editing && <PersonaFormModal persona={editing} onClose={() => setEditing(null)} onSubmit={(pl) => save(pl, editing)} />}
    </Card>
  );
}
