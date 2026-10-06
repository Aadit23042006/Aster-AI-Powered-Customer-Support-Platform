"use client";

import { AppShell } from "@/components/layout/app-shell";
import { Button, Card } from "@/components/ui/primitives";
import { useAuth } from "@/hooks/use-auth";

export default function SettingsPage() {
  const { logout } = useAuth();
  return (
    <AppShell>
      <div className="mx-auto max-w-2xl space-y-6">
        <h2 className="text-lg font-semibold text-stone-900">Settings</h2>

        <Card className="p-5">
          <h3 className="mb-1 text-sm font-semibold text-stone-900">Security</h3>
          <p className="mb-4 text-sm text-stone-500">Manage how you sign in to your account.</p>
          <Button variant="secondary" onClick={() => (window.location.href = "/forgot-password")}>
            Change password
          </Button>
        </Card>

        <Card className="p-5">
          <h3 className="mb-1 text-sm font-semibold text-stone-900">Sign out</h3>
          <p className="mb-4 text-sm text-stone-500">Sign out of Aster &amp; Row on this device.</p>
          <Button variant="danger" onClick={() => logout()}>
            Log out
          </Button>
        </Card>
      </div>
    </AppShell>
  );
}
