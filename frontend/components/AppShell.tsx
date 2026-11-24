"use client";

import clsx from "clsx";
import {
  BarChart3, FileText, FolderKanban, LayoutDashboard, LogOut, Menu, MessageSquare, Monitor, Moon, Settings, Sun, X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { Logo } from "./Logo";
import { EASE_OUT } from "./motion";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "AI Assistant", icon: MessageSquare },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/collections", label: "Collections", icon: FolderKanban },
  { href: "/evaluation", label: "Evaluation", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeSwitch({ id }: { id: string }) {
  const { theme, setTheme } = useTheme();
  const opts: { v: Theme; icon: ReactNode; label: string }[] = [
    { v: "light", icon: <Sun className="h-3.5 w-3.5" />, label: "Light" },
    { v: "system", icon: <Monitor className="h-3.5 w-3.5" />, label: "System" },
    { v: "dark", icon: <Moon className="h-3.5 w-3.5" />, label: "Dark" },
  ];
  return (
    <div className="relative flex rounded-xl bg-slate-900/[0.04] p-1 dark:bg-white/[0.05]" role="radiogroup" aria-label="Theme">
      {opts.map((o) => (
        <button key={o.v} role="radio" aria-checked={theme === o.v} title={o.label} onClick={() => setTheme(o.v)}
          className={clsx("relative z-10 flex flex-1 items-center justify-center rounded-lg py-1.5 transition-colors",
            theme === o.v ? "text-slate-900 dark:text-white" : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300")}>
          {theme === o.v && (
            <motion.span layoutId={`theme-pill-${id}`} className="absolute inset-0 -z-10 rounded-lg bg-white shadow-soft dark:bg-white/10"
              transition={{ type: "spring", stiffness: 500, damping: 38 }} />
          )}
          {o.icon}
        </button>
      ))}
    </div>
  );
}

function Sidebar({ id, onNavigate }: { id: string; onNavigate?: () => void }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  if (!user) return null;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-5 pt-6 pb-7">
        <Logo />
        <div>
          <div className="text-sm font-semibold tracking-tight">Knowledge Assistant</div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400">Enterprise RAG</div>
        </div>
      </div>
      <div className="px-5 pb-2 text-[10px] font-semibold tracking-[0.14em] text-slate-400 uppercase">Workspace</div>
      <nav className="flex-1 space-y-1 px-3" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(href);
          return (
            <Link key={href} href={href} onClick={onNavigate}
              className={clsx("group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                active ? "text-brand-700 dark:text-white" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")}>
              {active && (
                <motion.span layoutId={`nav-pill-${id}`}
                  className="absolute inset-0 -z-0 rounded-xl bg-gradient-to-r from-brand-500/[0.12] to-accent-500/[0.06] ring-1 ring-brand-500/20 dark:from-brand-400/20 dark:to-accent-400/10 dark:ring-brand-400/25"
                  transition={{ type: "spring", stiffness: 420, damping: 36 }} />
              )}
              {active && (
                <motion.span layoutId={`nav-bar-${id}`} className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-brand-gradient"
                  transition={{ type: "spring", stiffness: 420, damping: 36 }} />
              )}
              <Icon className={clsx("relative h-[18px] w-[18px] transition-transform duration-300 group-hover:scale-110",
                active ? "text-brand-600 dark:text-brand-300" : "")} />
              <span className="relative">{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="space-y-3 p-4">
        <ThemeSwitch id={id} />
        <div className="flex items-center gap-3 rounded-2xl border border-slate-200/70 bg-white/60 p-2.5 dark:border-white/[0.06] dark:bg-white/[0.03]">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-gradient text-xs font-semibold text-white uppercase shadow-glow">
            {(user.full_name || user.email).slice(0, 2)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user.full_name || user.email}</div>
            <div className="text-[11px] text-slate-500 capitalize dark:text-slate-400">{user.role}</div>
          </div>
          <button className="btn-ghost p-2" title="Sign out" aria-label="Sign out"
            onClick={() => { logout(); router.replace("/login"); }}>
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  // The mobile menu remembers the path it was opened on, so navigating closes it automatically.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === pathname;
  const setOpen = (v: boolean) => setOpenOn(v ? pathname : null);

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname]);

  if (loading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="relative">
          <span className="absolute inset-0 rounded-2xl bg-brand-500/40 animate-pulse-ring" />
          <Logo size="lg" />
        </motion.div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="hidden w-[264px] shrink-0 border-r border-slate-200/70 bg-white/70 backdrop-blur-xl lg:block dark:border-white/[0.06] dark:bg-surface-dark/60">
        <Sidebar id="desktop" />
      </aside>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <motion.div className="absolute inset-0 bg-slate-950/50 backdrop-blur-sm" onClick={() => setOpen(false)}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            <motion.aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-2xl dark:bg-surface-dark"
              initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ duration: 0.35, ease: EASE_OUT }}>
              <button className="btn-ghost absolute top-5 right-3 p-1.5" onClick={() => setOpen(false)} aria-label="Close menu">
                <X className="h-4 w-4" />
              </button>
              <Sidebar id="mobile" onNavigate={() => setOpen(false)} />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass flex items-center gap-3 border-x-0 border-t-0 px-4 py-3 lg:hidden">
          <button className="btn-ghost p-1.5" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <Logo size="sm" />
          <span className="text-sm font-semibold tracking-tight">Knowledge Assistant</span>
        </header>
        <main className="relative min-h-0 flex-1 overflow-y-auto">
          <div aria-hidden className="page-backdrop pointer-events-none absolute inset-x-0 top-0 h-[520px]" />
          <div className="relative h-full">{children}</div>
        </main>
      </div>
    </div>
  );
}
