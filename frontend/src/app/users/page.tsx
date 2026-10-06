"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Search, ShieldCheck, Trash2, UserCog, Users, X } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Card, EmptyState, Input, Spinner } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";
import type { AdminUser } from "@/types/api";

function roleLabel(role: string) {
  if (role === "support_agent") return "Support";
  if (role === "super_admin") return "Super Admin";
  return role.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function roleTone(role: string): "info" | "success" | "warning" | "danger" | "neutral" {
  if (role === "super_admin") return "danger";
  if (role === "admin") return "info";
  if (role === "support_agent") return "warning";
  return "success";
}

function effectiveRole(roles: string[]) {
  if (roles.includes("super_admin")) return "super_admin";
  if (roles.includes("admin")) return "admin";
  if (roles.includes("support_agent")) return "support_agent";
  if (roles.includes("customer")) return "customer";
  return null;
}

export default function UserManagementPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.adminUsers({ page: 1, page_size: 100, search: search.trim() || undefined });
      setUsers(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load users.");
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadUsers(), 220);
    return () => window.clearTimeout(timer);
  }, [loadUsers]);

  const counts = useMemo(() => ({
    admins: users.filter((u) => ["admin", "super_admin"].includes(effectiveRole(u.roles) || "")).length,
    support: users.filter((u) => effectiveRole(u.roles) === "support_agent").length,
    customers: users.filter((u) => effectiveRole(u.roles) === "customer").length,
  }), [users]);

  const canDelete = (target: AdminUser) => {
    if (!currentUser || target.id === currentUser.id) return false;
    // All four built-in account types are protected. Keep the helper so any
    // future non-core/test role can still be made removable by policy.
    return !["admin", "super_admin", "support_agent", "customer"].includes(effectiveRole(target.roles) || "");
  };

  const protectionReason = (target: AdminUser) => {
    if (target.id === currentUser?.id) return "You cannot delete your own account";
    const role = effectiveRole(target.roles);
    if (role === "super_admin") return "Super admin accounts are protected";
    if (role === "admin") return "Admin accounts are protected";
    if (role === "support_agent") return "Support accounts are protected";
    if (role === "customer") return "Customer accounts are protected";
    return "Protected account";
  };

  const confirmDelete = async () => {
    if (!deleteTarget || !canDelete(deleteTarget)) return;
    setDeleting(true);
    setError(null);
    setSuccess(null);
    try {
      await api.deleteAdminUser(deleteTarget.id);
      setUsers((items) => items.filter((item) => item.id !== deleteTarget.id));
      setTotal((value) => Math.max(0, value - 1));
      setSuccess(`${deleteTarget.email} was permanently deleted.`);
      setDeleteTarget(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete this account.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-indigo-600"><UserCog className="h-5 w-5" /><span className="text-xs font-bold uppercase tracking-[.16em]">Admin & Management</span></div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">User Management</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">Manage customer, support and admin accounts from one secure workspace.</p>
          </div>
          <Badge tone="info"><ShieldCheck className="mr-1 h-3.5 w-3.5" /> Admin only</Badge>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat icon={Users} label="Total users" value={total} />
          <Stat icon={ShieldCheck} label="Admins" value={counts.admins} />
          <Stat icon={UserCog} label="Support" value={counts.support} />
          <Stat icon={CheckCircle2} label="Customers" value={counts.customers} />
        </div>

        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 p-4 md:p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div><h2 className="text-sm font-semibold text-slate-900">Accounts</h2><p className="mt-0.5 text-xs text-slate-500">Core Admin, Support, Customer and Super Admin accounts are protected from permanent deletion.</p></div>
              <div className="relative w-full md:w-80"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by email..." className="pl-9" /></div>
            </div>
          </div>

          {error && <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
          {success && <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{success}</div>}

          {loading ? <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-indigo-600" /></div> : users.length === 0 ? (
            <div className="p-5"><EmptyState title="No users found" description={search ? "Try a different email search." : "No accounts are currently available."} /></div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left">
                <thead className="bg-slate-50/80 text-[11px] font-bold uppercase tracking-[.12em] text-slate-500"><tr><th className="px-5 py-3">User</th><th className="px-5 py-3">Role</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Created</th><th className="px-5 py-3 text-right">Actions</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {users.map((item) => {
                    const removable = canDelete(item);
                    return <tr key={item.id} className="transition hover:bg-slate-50/70">
                      <td className="px-5 py-4"><div className="font-semibold text-slate-900">{item.full_name}</div><div className="mt-0.5 text-xs text-slate-500">{item.email}</div></td>
                      <td className="px-5 py-4"><div className="flex flex-wrap gap-1.5">{item.roles.map((role) => <Badge key={role} tone={roleTone(role)}>{roleLabel(role)}</Badge>)}</div></td>
                      <td className="px-5 py-4"><Badge tone={item.is_active ? "success" : "neutral"}>{item.is_active ? "Active" : "Disabled"}</Badge></td>
                      <td className="px-5 py-4 text-xs text-slate-500">{new Date(item.created_at).toLocaleDateString()}</td>
                      <td className="px-5 py-4 text-right"><Button variant="danger" size="sm" disabled={!removable} onClick={() => setDeleteTarget(item)} title={!removable ? protectionReason(item) : "Delete account"}><ShieldCheck className="h-3.5 w-3.5" />{removable ? "Delete" : "Protected"}</Button></td>
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4 text-xs leading-5 text-amber-900"><strong>Deletion policy:</strong> Admin, Support, Customer and Super Admin accounts are protected. The currently signed-in account is always protected as well. The API enforces the same rule even if a direct delete request is attempted.</div>
      </div>

      {deleteTarget && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="delete-user-title">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
          <div className="flex items-start justify-between gap-4"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 text-red-600"><Trash2 className="h-5 w-5" /></div><button aria-label="Close" onClick={() => !deleting && setDeleteTarget(null)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-5 w-5" /></button></div>
          <h2 id="delete-user-title" className="mt-5 text-lg font-bold text-slate-900">Delete this account?</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">This permanently removes <strong className="text-slate-800">{deleteTarget.email}</strong>. The action cannot be undone.</p>
          <div className="mt-4 rounded-xl border border-red-100 bg-red-50 px-3 py-2.5 text-xs text-red-700">User-owned data follows the existing database deletion rules. Business history designed to survive account deletion is retained.</div>
          <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" disabled={deleting} onClick={() => setDeleteTarget(null)}>Cancel</Button><Button variant="danger" disabled={deleting} onClick={() => void confirmDelete()}>{deleting ? <Spinner className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />}{deleting ? "Deleting..." : "Yes, delete account"}</Button></div>
        </div>
      </div>}
    </AppShell>
  );
}

function Stat({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: number }) {
  return <Card className="p-4"><div className="flex items-center gap-2 text-xs text-slate-500"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><Icon className="h-4 w-4" /></span>{label}</div><div className="mt-2 text-2xl font-bold text-slate-900">{value}</div></Card>;
}
