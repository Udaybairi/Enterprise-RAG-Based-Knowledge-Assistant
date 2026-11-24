"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, Clock, Loader2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, type ReactNode } from "react";
import type { DocumentStatus } from "@/types";
import { AnimatedNumber, EASE_OUT } from "./motion";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin", className ?? "h-4 w-4")} aria-label="Loading" />;
}

export function PageHeader({ title, description, actions, eyebrow }:
  { title: ReactNode; description?: string; actions?: ReactNode; eyebrow?: string }) {
  return (
    <motion.div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: EASE_OUT }}>
      <div>
        {eyebrow && (
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-brand-200/70 bg-brand-50/70 px-2.5 py-0.5 text-[11px] font-medium text-brand-700 dark:border-brand-400/20 dark:bg-brand-400/10 dark:text-brand-200">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            {eyebrow}
          </div>
        )}
        <h1 className="text-[1.7rem] leading-tight font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </motion.div>
  );
}

const TONES = {
  brand: { tile: "from-brand-500 to-accent-500", glow: "bg-brand-500/20" },
  green: { tile: "from-emerald-500 to-teal-500", glow: "bg-emerald-500/20" },
  red: { tile: "from-rose-500 to-red-500", glow: "bg-rose-500/20" },
  amber: { tile: "from-amber-400 to-orange-500", glow: "bg-amber-500/20" },
  slate: { tile: "from-slate-500 to-slate-700", glow: "bg-slate-500/20" },
};

export function StatCard({
  label, value, icon, hint, tone = "brand", format,
}: { label: string; value: ReactNode | number; icon: ReactNode; hint?: string; tone?: keyof typeof TONES; format?: (n: number) => string }) {
  const t = TONES[tone];
  return (
    <div className="card-interactive group relative h-full overflow-hidden p-5">
      <div className={clsx("pointer-events-none absolute -top-10 -right-10 h-28 w-28 rounded-full opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100", t.glow)} />
      <div className="relative flex items-center justify-between">
        <span className="text-[11px] font-semibold tracking-[0.12em] text-slate-500 uppercase dark:text-slate-400">{label}</span>
        <span className={clsx("flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-soft transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3", t.tile)}>
          {icon}
        </span>
      </div>
      <div className="relative mt-4 text-[1.9rem] leading-none font-semibold tracking-tight tabular-nums">
        {typeof value === "number" ? <AnimatedNumber value={value} format={format} /> : value}
      </div>
      {hint && <div className="relative mt-2 text-xs text-slate-500 dark:text-slate-400">{hint}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, { cls: string; icon: ReactNode; label: string }> = {
    completed: { cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/15 dark:bg-emerald-400/10 dark:text-emerald-300", icon: <CheckCircle2 className="h-3 w-3" />, label: "Ready" },
    processing: { cls: "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-400/10 dark:text-blue-300", icon: <LiveDot className="bg-blue-500" />, label: "Processing" },
    pending: { cls: "bg-amber-50 text-amber-700 ring-amber-600/15 dark:bg-amber-400/10 dark:text-amber-300", icon: <Clock className="h-3 w-3" />, label: "Queued" },
    failed: { cls: "bg-rose-50 text-rose-700 ring-rose-600/15 dark:bg-rose-400/10 dark:text-rose-300", icon: <AlertCircle className="h-3 w-3" />, label: "Failed" },
    running: { cls: "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-400/10 dark:text-blue-300", icon: <LiveDot className="bg-blue-500" />, label: "Running" },
  };
  const s = map[status] ?? map.pending;
  return (
    <motion.span layout initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
      className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset", s.cls)}>
      {s.icon}
      {s.label}
    </motion.span>
  );
}

export function LiveDot({ className }: { className?: string }) {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className={clsx("absolute inset-0 rounded-full animate-pulse-ring", className)} />
      <span className={clsx("relative inline-flex h-2 w-2 rounded-full", className)} />
    </span>
  );
}

export function FileTypeIcon({ type }: { type: string }) {
  const colors: Record<string, string> = {
    pdf: "from-rose-500 to-red-600",
    docx: "from-blue-500 to-indigo-600",
    pptx: "from-orange-400 to-amber-600",
    xlsx: "from-emerald-500 to-green-600",
    csv: "from-teal-400 to-cyan-600",
    md: "from-violet-500 to-purple-600",
    markdown: "from-violet-500 to-purple-600",
    txt: "from-slate-400 to-slate-600",
  };
  return (
    <span className={clsx("relative inline-flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br text-[9px] font-bold tracking-wide text-white uppercase shadow-soft", colors[type] ?? colors.txt)}>
      <span className="absolute top-0 right-0 h-2.5 w-2.5 rounded-bl-md bg-white/30" />
      {type.slice(0, 4)}
    </span>
  );
}

export function Modal({
  open, onClose, title, children, size = "md", footer,
}: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; size?: "md" | "lg" | "xl"; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const widths = { md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-6xl" };
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <motion.div className="absolute inset-0 bg-slate-950/40 backdrop-blur-md" onClick={onClose}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
          <motion.div className={clsx("card relative flex max-h-[90vh] w-full flex-col overflow-hidden shadow-2xl", widths[size])}
            initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }} transition={{ duration: 0.3, ease: EASE_OUT }}>
            <div className="flex items-center justify-between border-b border-slate-200/70 px-5 py-4 dark:border-white/[0.06]">
              <h2 className="min-w-0 truncate text-base font-semibold tracking-tight">{title}</h2>
              <button className="btn-ghost -mr-2 p-1.5" onClick={onClose} aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-slate-200/70 bg-slate-50/60 px-5 py-3 dark:border-white/[0.06] dark:bg-white/[0.02]">{footer}</div>}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <motion.div className="flex flex-col items-center justify-center px-6 py-16 text-center"
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: EASE_OUT }}>
      <div className="relative mb-4">
        <div className="absolute inset-0 rounded-2xl bg-brand-500/25 blur-xl" />
        <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glow animate-float">
          {icon}
        </div>
      </div>
      <h3 className="text-base font-semibold tracking-tight">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </motion.div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
      className="mb-4 flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="flex-1">{message}</span>
      {onRetry && <button className="font-medium underline underline-offset-2" onClick={onRetry}>Retry</button>}
    </motion.div>
  );
}

export function Toast({ message, tone = "info", onClose }: { message: string; tone?: "info" | "error" | "success"; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4500);
    return () => clearTimeout(t);
  }, [onClose]);
  const tones = {
    info: "bg-slate-900/95 text-white dark:bg-white/95 dark:text-slate-900",
    error: "bg-gradient-to-r from-rose-600 to-red-600 text-white",
    success: "bg-gradient-to-r from-emerald-600 to-teal-600 text-white",
  };
  return (
    <motion.div className={clsx("fixed right-4 bottom-4 z-[60] flex max-w-sm items-start gap-2.5 rounded-2xl px-4 py-3 text-sm shadow-2xl backdrop-blur", tones[tone])}
      role="status" initial={{ opacity: 0, y: 24, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 380, damping: 30 }}>
      {tone === "success" && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
      {tone === "error" && <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
      <span>{message}</span>
    </motion.div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function ConfirmDialog({
  open, title, message, confirmLabel = "Delete", onConfirm, onCancel, busy,
}: { open: boolean; title: string; message: string; confirmLabel?: string; onConfirm: () => void; onCancel: () => void; busy?: boolean }) {
  return (
    <Modal open={open} onClose={onCancel} title={title}
      footer={<>
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn-danger" onClick={onConfirm} disabled={busy}>{busy && <Spinner />}{confirmLabel}</button>
      </>}>
      <p className="text-sm text-slate-600 dark:text-slate-300">{message}</p>
    </Modal>
  );
}
