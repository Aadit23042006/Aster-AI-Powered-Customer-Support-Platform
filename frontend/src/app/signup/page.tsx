 "use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Bot, CheckCircle2, ShieldCheck, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button, Card, Input } from "@/components/ui/primitives";

export default function SignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const result = await api.signup(fullName.trim(), email.trim(), password, confirmPassword);
      if (typeof window !== "undefined") {
        localStorage.setItem("access_token", result.access_token);
        localStorage.setItem("refresh_token", result.refresh_token);
      }
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create your account. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f5f7fb] lg:grid lg:grid-cols-[1.1fr_.9fr]">
      <section className="relative hidden overflow-hidden bg-[#101828] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-96 w-96 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-500">
              <Bot className="h-6 w-6" />
            </div>
            <div>
              <p className="font-bold">Aster &amp; Row</p>
              <p className="text-[10px] uppercase tracking-[.18em] text-slate-400">AI Support OS</p>
            </div>
          </div>

          <div className="mt-28 max-w-xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-indigo-200">
              <Sparkles className="h-3.5 w-3.5" /> Built for modern support teams
            </div>
            <h1 className="text-5xl font-bold leading-[1.08] tracking-tight">
              Build a smarter
              <br />
              <span className="text-indigo-300">support workspace.</span>
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-slate-300">
              Bring conversations, orders, AI actions, knowledge and customer context together in one modern workspace.
            </p>
            <div className="mt-9 grid grid-cols-2 gap-3">
              {["AI-assisted workflows", "Human approval controls", "Knowledge-grounded answers", "Production-ready analytics"].map((x) => (
                <div key={x} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-slate-200">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  {x}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="relative flex items-center gap-2 text-xs text-slate-400">
          <ShieldCheck className="h-4 w-4" /> Secure workspace · Role-based access
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-5 py-10 md:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white">
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <p className="font-bold text-slate-900">Aster &amp; Row</p>
                <p className="text-[9px] uppercase tracking-[.18em] text-slate-400">AI Support OS</p>
              </div>
            </div>
          </div>

          <div className="mb-8">
            <p className="text-xs font-bold uppercase tracking-[.18em] text-indigo-600">Get started</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Create your account</h2>
            <p className="mt-2 text-sm text-slate-500">Set up your Aster &amp; Row workspace access.</p>
          </div>

          <Card className="p-6 md:p-7">
            {error && (
              <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700" role="alert">
                {error}
              </div>
            )}

            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <label className="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-600">Full name</label>
                <Input required minLength={2} value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Your full name" />
              </div>

              <div>
                <label className="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-600">Email</label>
                <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </div>

              <div>
                <label className="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-600">Password</label>
                <Input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
              </div>

              <div>
                <label className="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-600">Confirm password</label>
                <Input type="password" required minLength={8} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Repeat your password" />
              </div>

              <Button type="submit" className="h-11 w-full" disabled={loading}>
                {loading ? "Creating account…" : "Create account"}
                <ArrowRight className="h-4 w-4" />
              </Button>
            </form>
          </Card>

          <p className="mt-5 text-center text-sm text-slate-500">
            Already have an account?{" "}
            <Link href="/login" className="font-semibold text-indigo-600 hover:text-indigo-700">
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
