"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, Clock, Loader2, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import type { DocumentStatus } from "@/types";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin", className ?? "h-4 w-4")} aria-label="Loading" />;
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  label, value, icon, hint, tone = "brand",
}: { label: string; value: ReactNode; icon: ReactNode; hint?: string; tone?: "brand" | "green" | "red" | "amber" | "slate" }) {
  const tones = {
    brand: "bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-400",
    green: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400",
    red: "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400",
    amber: "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400",
    slate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  };
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400">{label}</span>
        <span className={clsx("rounded-lg p-2", tones[tone])}>{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, { cls: string; icon: ReactNode; label: string }> = {
    completed: { cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-400", icon: <CheckCircle2 className="h-3 w-3" />, label: "Ready" },
    processing: { cls: "bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-500/10 dark:text-blue-400", icon: <Spinner className="h-3 w-3" />, label: "Processing" },
    pending: { cls: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-400", icon: <Clock className="h-3 w-3" />, label: "Queued" },
    failed: { cls: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-400", icon: <AlertCircle className="h-3 w-3" />, label: "Failed" },
    running: { cls: "bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-500/10 dark:text-blue-400", icon: <Spinner className="h-3 w-3" />, label: "Running" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", s.cls)}>
      {s.icon}
      {s.label}
    </span>
  );
}

export function FileTypeIcon({ type }: { type: string }) {
  const colors: Record<string, string> = {
    pdf: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
    docx: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    pptx: "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
    xlsx: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    csv: "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
    md: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
    markdown: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
    txt: "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
  };
  return (
    <span className={clsx("inline-flex h-8 w-10 shrink-0 items-center justify-center rounded-md text-[10px] font-bold uppercase", colors[type] ?? colors.txt)}>
      {type}
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
  if (!open) return null;
  const widths = { md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-6xl" };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div className={clsx("card relative flex max-h-[90vh] w-full flex-col overflow-hidden shadow-xl", widths[size])}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <h2 className="min-w-0 truncate text-base font-semibold">{title}</h2>
          <button className="btn-ghost -mr-2 p-1.5" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-800">{footer}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-500 dark:bg-slate-800 dark:text-slate-400">{icon}</div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="flex-1">{message}</span>
      {onRetry && <button className="font-medium underline" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Toast({ message, tone = "info", onClose }: { message: string; tone?: "info" | "error" | "success"; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4500);
    return () => clearTimeout(t);
  }, [onClose]);
  const tones = {
    info: "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
    error: "bg-red-600 text-white",
    success: "bg-emerald-600 text-white",
  };
  return (
    <div className={clsx("fixed right-4 bottom-4 z-[60] max-w-sm rounded-lg px-4 py-3 text-sm shadow-lg", tones[tone])} role="status">
      {message}
    </div>
  );
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
