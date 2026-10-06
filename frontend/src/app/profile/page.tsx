"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, Input } from "@/components/ui/primitives";
import { useAuth } from "@/hooks/use-auth";
import { api, ApiError } from "@/lib/api";
import { formatDate, titleCase } from "@/lib/utils";

export default function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.updateProfile(fullName);
      await refreshUser();
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save changes.");
    } finally {
      setSaving(false);
    }
  }

  if (!user) return null;

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl space-y-6">
        <h2 className="text-lg font-semibold text-stone-900">Profile</h2>

        <Card className="p-5">
          <h3 className="mb-4 text-sm font-semibold text-stone-900">Profile information</h3>
          <form onSubmit={onSave} className="space-y-4">
            {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
            {saved && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">Profile updated.</div>}
            <div>
              <label className="mb-1 block text-sm font-medium text-stone-700">Full name</label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-stone-700">Email</label>
              <Input value={user.email} disabled className="bg-stone-50 text-stone-500" />
              <p className="mt-1 text-xs text-stone-400">Email changes aren&apos;t supported yet — contact support if needed.</p>
            </div>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </Card>

        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-stone-900">Account activity</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-stone-500">Account created</dt>
              <dd className="text-stone-900">{formatDate(user.created_at)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-stone-500">Roles</dt>
              <dd className="flex gap-1">
                {user.roles.map((r) => (
                  <Badge key={r}>{titleCase(r)}</Badge>
                ))}
              </dd>
            </div>
          </dl>
        </Card>
      </div>
    </AppShell>
  );
}
