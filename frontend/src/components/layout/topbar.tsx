"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  LogOut,
  Menu,
  User as UserIcon,
  X,
  LayoutDashboard,
  MessageSquare,
  Package,
  Ticket as TicketIcon,
  Settings,
} from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";

const mobileNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "AI Chat", icon: MessageSquare },
  { href: "/orders", label: "Orders", icon: Package },
  { href: "/tickets", label: "Tickets", icon: TicketIcon },
  { href: "/profile", label: "Profile", icon: UserIcon },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Topbar() {
  const { user, logout } = useAuth();

  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);

  /*
   * Global Search keyboard shortcuts
   *
   * Windows/Linux:
   * Ctrl + K
   *
   * macOS:
   * Cmd + K
   *
   * Escape closes the search modal.
   */
  useEffect(() => {
    const handleKeyboard = (e: KeyboardEvent) => {
      if (
        (e.ctrlKey || e.metaKey) &&
        e.key.toLowerCase() === "k"
      ) {
        e.preventDefault();
        setSearchOpen(true);
      }

      if (e.key === "Escape") {
        setSearchOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyboard);

    return () => {
      window.removeEventListener("keydown", handleKeyboard);
    };
  }, []);

  /*
   * Global Search API
   *
   * Calls:
   * GET /search?q=...
   */
  useEffect(() => {
    if (!searchOpen || !query.trim()) {
      setResults([]);
      return;
    }

    const timeoutId = setTimeout(() => {
      api
        .globalSearch(query)
        .then((response) => {
          setResults(response.results || []);
        })
        .catch(() => {
          setResults([]);
        });
    }, 250);

    return () => clearTimeout(timeoutId);
  }, [searchOpen, query]);

  const pathname = usePathname();

  const title =
    pathname.split("/").filter(Boolean)[0] || "dashboard";

  /*
   * Map Global Search result types to their frontend routes.
   *
   * customer     -> /customer-360/{id}
   * order        -> /orders/{id}
   * ticket       -> /tickets/{id}
   * conversation -> /conversations/{id}
   *
   * Unknown result types remain non-navigable.
   */
  const getSearchResultHref = (result: any): string => {
    switch (result.type) {
      case "customer":
        return `/customer-360/${result.id}`;

      case "order":
        return `/orders/${result.id}`;

      case "ticket":
        return `/tickets/${result.id}`;

      case "conversation":
        return `/chat?c=${result.id}`;

      case "knowledge_base":
        return `/kb/${result.id}`;

      default:
        return "#";
    }
  };

  const handleSearchResultClick = (result: any) => {
    setSearchOpen(false);
    setQuery("");
    setResults([]);
  };

  return (
    <>
      <header className="glass sticky top-0 z-40 flex h-[76px] items-center justify-between border-b border-slate-200/80 px-4 md:px-7">
        <div className="flex items-center gap-3">
          <button
            className="md:hidden"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5 text-stone-600" />
          </button>

          <h1 className="text-sm font-bold capitalize text-slate-900">
            {title.replace(/-/g, " ")}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {/* Desktop Global Search button */}
          <button
            onClick={() => setSearchOpen(true)}
            className="hidden h-10 min-w-[250px] items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/80 px-3.5 text-xs text-slate-500 shadow-sm hover:bg-white sm:flex"
          >
            <span>Search everything</span>

            <kbd className="ml-auto rounded-md bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-400 ring-1 ring-slate-200">
              Ctrl K
            </kbd>
          </button>

          {/* Notifications */}
          <button
            className="relative rounded-xl p-2.5 text-slate-500 hover:bg-slate-100"
            aria-label="Notifications"
          >
            <Bell className="h-5 w-5" />
          </button>

          {/* User menu */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen((value) => !value)}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white py-1.5 pl-1.5 pr-3 text-sm shadow-sm hover:border-slate-300"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-bold text-white">
                {user?.full_name?.[0]?.toUpperCase() || "?"}
              </span>

              <span className="hidden font-semibold text-slate-700 sm:inline">
                {user?.full_name}
              </span>
            </button>

            {menuOpen && (
              <div className="absolute right-0 mt-2 w-52 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
                <Link
                  href="/profile"
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  onClick={() => setMenuOpen(false)}
                >
                  <UserIcon className="h-4 w-4" />
                  Profile
                </Link>

                <button
                  onClick={() => logout()}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                >
                  <LogOut className="h-4 w-4" />
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Global Search Modal */}
      {searchOpen && (
        <div
          className="fixed inset-0 z-[60] bg-black/30 p-4"
          onClick={() => setSearchOpen(false)}
        >
          <div
            className="mx-auto mt-16 max-w-2xl rounded-xl border bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search orders, tickets, customers, conversations, KB, products…"
              className="w-full rounded-t-xl border-b p-4 outline-none"
            />

            <div className="max-h-96 overflow-auto p-2">
              {results.length ? (
                results.map((result: any) => {
                  const href = getSearchResultHref(result);

                  return (
                    <Link
                      key={`${result.type}-${result.id}`}
                      href={href}
                      onClick={() =>
                        handleSearchResultClick(result)
                      }
                      className="block rounded-lg p-3 hover:bg-stone-50"
                    >
                      <div className="text-sm font-medium text-stone-900">
                        {result.title}
                      </div>

                      <div className="text-xs text-stone-500">
                        {result.type} · {result.subtitle}
                      </div>
                    </Link>
                  );
                })
              ) : (
                <div className="p-6 text-center text-sm text-stone-500">
                  {query
                    ? "No authorized results found."
                    : "Start typing to search everything."}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Mobile Navigation */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="w-64 bg-white">
            <div className="flex h-16 items-center justify-between border-b border-stone-200 px-4">
              <span className="font-semibold">Menu</span>

              <button
                onClick={() => setMobileNavOpen(false)}
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <nav className="space-y-0.5 px-3 py-4">
              {mobileNav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileNavOpen(false)}
                  className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-stone-600 hover:bg-stone-100"
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>

          <div
            className="flex-1 bg-black/30"
            onClick={() => setMobileNavOpen(false)}
          />
        </div>
      )}
    </>
  );
}