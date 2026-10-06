"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { Button, Card, Input } from "@/components/ui/primitives";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-stone-50 px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-lg font-semibold text-stone-900">Reset your password</h1>
        <Card className="p-6">
          {sent ? (
            <p className="text-sm text-stone-600">
              If that email is registered, a reset link has been sent. Check your inbox.
            </p>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
              <div>
                <label className="mb-1 block text-sm font-medium text-stone-700">Email</label>
                <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Sending…" : "Send reset link"}
              </Button>
            </form>
          )}
        </Card>
        <p className="mt-5 text-center text-sm text-stone-500">
          <Link href="/login" className="font-medium text-stone-900 hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
