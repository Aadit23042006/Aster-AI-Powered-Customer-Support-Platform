"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, MessageSquare, Package, Ticket as TicketIcon, User, Settings, BookOpen, BarChart3, ShieldAlert, Activity, FlaskConical, Sparkles, Wrench, UsersRound, UserCog, BrainCircuit, FileSearch, Search, Bot, CircleHelp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";

const customerNav = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/chat", label: "AI Assistant", icon: MessageSquare },
  { href: "/orders", label: "Orders", icon: Package },
  { href: "/tickets", label: "Support Tickets", icon: TicketIcon },
  { href: "/advanced", label: "AI Studio", icon: Sparkles },
];
const workspaceNav = [
  { href: "/support-workspace", label: "Support Workspace", icon: UsersRound },
  { href: "/action-center", label: "Action Center", icon: Wrench },
  { href: "/ai-intelligence", label: "AI Intelligence", icon: BrainCircuit },
  { href: "/ai-safety", label: "AI Safety", icon: ShieldAlert },
];
const adminNav = [
  { href: "/users", label: "User Management", icon: UserCog },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/kb", label: "Knowledge Base", icon: BookOpen },
  { href: "/ai-traces", label: "AI Traces", icon: Activity },
  { href: "/evaluations", label: "Evaluations", icon: FlaskConical },
  { href: "/ai-evaluation-playground", label: "Eval Playground", icon: FlaskConical },
  { href: "/prompt-management", label: "Prompt Management", icon: Settings },
  { href: "/ai-usage", label: "AI Usage & Routing", icon: BarChart3 },
];
const utilityNav = [
  { href: "/source-explorer", label: "Source Explorer", icon: FileSearch },
  { href: "/search", label: "Global Search", icon: Search },
  { href: "/profile", label: "Profile", icon: User },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const isStaff = !!user?.roles.some((r) => ["support_agent", "admin", "super_admin"].includes(r));
  const isAdmin = !!user?.roles.some((r) => ["admin", "super_admin"].includes(r));
  return (
    <aside className="sticky top-0 hidden h-screen w-[268px] shrink-0 flex-col overflow-y-auto border-r border-slate-800 bg-[#101828] text-white lg:flex">
      <div className="flex h-[76px] items-center gap-3 border-b border-white/10 px-6">
        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500 font-black shadow-lg shadow-indigo-950/30"><Bot className="h-5 w-5" /><span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#101828] bg-emerald-400" /></div>
        <div><p className="text-sm font-bold tracking-wide">Aster &amp; Row</p><p className="text-[10px] font-medium uppercase tracking-[.18em] text-slate-400">AI Support OS</p></div>
      </div>
      <div className="px-4 pt-5"><div className="mb-3 flex items-center justify-between px-2"><span className="text-[10px] font-bold uppercase tracking-[.16em] text-slate-500">Workspace</span><span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-[9px] font-bold text-emerald-300">LIVE</span></div>
        <nav className="space-y-1">{customerNav.map((item) => <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />)}</nav>
      </div>
      {isStaff && <Section title="Support & AI" items={workspaceNav} pathname={pathname} />}
      {isAdmin && <Section title="Admin & Intelligence" items={adminNav} pathname={pathname} />}
      <div className="mt-auto border-t border-white/10 bg-[#101828] p-4"><div className="mb-3 rounded-xl bg-white/5 p-3"><div className="flex items-center gap-2"><CircleHelp className="h-4 w-4 text-indigo-300" /><span className="text-xs font-semibold">Need help?</span></div><p className="mt-1 text-[11px] leading-4 text-slate-400">Search the workspace or ask the AI assistant.</p></div>{utilityNav.map((item) => <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} compact />)}</div>
    </aside>
  );
}
function Section({ title, items, pathname }: { title: string; items: typeof workspaceNav; pathname: string }) { return <div className="px-4 pt-5"><div className="mb-2 px-2 text-[10px] font-bold uppercase tracking-[.16em] text-slate-500">{title}</div><nav className="space-y-1">{items.map((item) => <NavLink key={item.href} {...item} active={pathname.startsWith(item.href)} />)}</nav></div>; }
function NavLink({ href, label, icon: Icon, active, compact = false }: { href: string; label: string; icon: React.ComponentType<{ className?: string }>; active: boolean; compact?: boolean }) { return <Link href={href} className={cn("group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all", compact && "py-2 text-xs", active ? "bg-white text-slate-900 shadow-sm" : "text-slate-400 hover:bg-white/5 hover:text-white")}><Icon className={cn("h-[17px] w-[17px]", active ? "text-indigo-600" : "text-slate-500 group-hover:text-slate-300")} />{label}{active && !compact && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-indigo-500" />}</Link>; }
