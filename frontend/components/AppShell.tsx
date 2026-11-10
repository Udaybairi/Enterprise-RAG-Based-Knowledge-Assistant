"use client";

import clsx from "clsx";
import {
  BarChart3, BookOpen, FileText, FolderKanban, LayoutDashboard, LogOut, Menu, MessageSquare, Monitor, Moon,
  Settings, Sparkles, Sun, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { Spinner } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "AI Assistant", icon: MessageSquare },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/collections", label: "Collections", icon: FolderKanban },
  { href: "/evaluation", label: "Evaluation", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const opts: { v: Theme; icon: ReactNode; label: string }[] = [
    { v: "light", icon: <Sun className="h-3.5 w-3.5" />, label: "Light" },
    { v: "system", icon: <Monitor className="h-3.5 w-3.5" />, label: "System" },
    { v: "dark", icon: <Moon className="h-3.5 w-3.5" />, label: "Dark" },
  ];
  return (
    <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-800" role="radiogroup" aria-label="Theme">
      {opts.map((o) => (
        <button key={o.v} role="radio" aria-checked={theme === o.v} title={o.label} onClick={() => setTheme(o.v)}
          className={clsx("flex flex-1 items-center justify-center rounded-md py-1.5 transition",
            theme === o.v ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-500")}>
          {o.icon}
        </button>
      ))}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname]);
  useEffect(() => setOpen(false), [pathname]);

  if (loading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
          <Sparkles className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold leading-tight">Knowledge Assistant</div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400">Enterprise RAG</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href}
            className={clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
              isActive(href)
                ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100")}>
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>
      <div className="space-y-3 border-t border-slate-200 p-4 dark:border-slate-800">
        <ThemeSwitch />
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold uppercase dark:bg-slate-700">
            {(user.full_name || user.email).slice(0, 2)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user.full_name || user.email}</div>
            <div className="text-[11px] text-slate-500 capitalize dark:text-slate-400">{user.role}</div>
          </div>
          <button className="btn-ghost p-1.5" title="Sign out" aria-label="Sign out"
            onClick={() => { logout(); router.replace("/login"); }}>
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:block dark:border-slate-800 dark:bg-slate-900">
        {sidebar}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-white shadow-xl dark:bg-slate-900">
            <button className="btn-ghost absolute top-4 right-3 p-1.5" onClick={() => setOpen(false)} aria-label="Close menu">
              <X className="h-4 w-4" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 lg:hidden dark:border-slate-800 dark:bg-slate-900">
          <button className="btn-ghost p-1.5" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <BookOpen className="h-4 w-4 text-brand-600" />
          <span className="text-sm font-semibold">Knowledge Assistant</span>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
