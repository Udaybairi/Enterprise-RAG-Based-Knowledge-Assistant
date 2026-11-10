"use client";

import clsx from "clsx";
import { AlertTriangle, Bot, Check, Copy, FileText, RefreshCw, ThumbsDown, ThumbsUp, User as UserIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage as Msg, Citation } from "@/types";
import { Spinner } from "./ui";

/** Turn [n] markers into links handled by the custom anchor renderer (skip real markdown links). */
function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,3})\](?!\()/g, "[$1](#cite-$1)");
}

function pageLabel(c: Citation) {
  if (c.page_number == null) return null;
  return c.page_end && c.page_end !== c.page_number ? `pp. ${c.page_number}–${c.page_end}` : `p. ${c.page_number}`;
}

export function CitationCard({ c, onOpen, active }: { c: Citation; onOpen: (c: Citation) => void; active?: boolean }) {
  const page = pageLabel(c);
  return (
    <button onClick={() => onOpen(c)} id={`citation-${c.chunk_id}`}
      className={clsx("group w-full rounded-lg border p-3 text-left transition hover:border-brand-400 hover:shadow-sm",
        active ? "border-brand-500 ring-2 ring-brand-500/20" : "border-slate-200 dark:border-slate-700")}>
      <div className="flex items-start gap-2">
        <span className="flex h-5 min-w-5 items-center justify-center rounded bg-brand-600 px-1 text-[11px] font-semibold text-white">{c.index}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            <span className="truncate">{c.document_name}</span>
            {page && <span className="shrink-0 text-slate-500">· {page}</span>}
          </div>
          {c.section && <div className="mt-0.5 truncate text-[11px] text-slate-500">§ {c.section}</div>}
          <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-slate-600 dark:text-slate-400">“{c.snippet}”</p>
          {c.score != null && (
            <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
              <span>Relevance</span>
              <span className="h-1 w-16 overflow-hidden rounded bg-slate-200 dark:bg-slate-700">
                <span className="block h-full bg-brand-500" style={{ width: `${Math.min(100, Math.max(5, c.score * 100))}%` }} />
              </span>
              <span className="tabular-nums">{c.score.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

export function ChatMessageView({
  m, onOpenCitation, onRegenerate, onFeedback, isLast,
}: {
  m: Msg;
  onOpenCitation: (c: Citation) => void;
  onRegenerate?: () => void;
  onFeedback?: (rating: number) => void;
  isLast?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const byIndex = useMemo(() => new Map(m.citations.map((c) => [c.index, c])), [m.citations]);
  const content = useMemo(() => linkCitations(m.content), [m.content]);

  if (m.role === "user") {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm whitespace-pre-wrap text-white">{m.content}</div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 dark:bg-slate-700"><UserIcon className="h-4 w-4" /></div>
      </div>
    );
  }

  const copy = async () => {
    await navigator.clipboard.writeText(m.content.replace(/\n\n> ⚠️.*$/s, ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const grounded = m.meta?.grounded;
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-400">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="card px-4 py-3">
          {m.pending && !m.content && (
            <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner />{m.status || "Thinking…"}</div>
          )}
          {m.error ? (
            <div className="flex items-start gap-2 text-sm text-red-600"><AlertTriangle className="mt-0.5 h-4 w-4" />{m.error}</div>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const match = href?.match(/^#cite-(\d+)$/);
                    if (match) {
                      const c = byIndex.get(Number(match[1]));
                      if (!c) return m.pending ? <sup className="text-[10px] text-slate-400">[{match[1]}]</sup> : null;
                      return (
                        <button onClick={() => onOpenCitation(c)} title={`${c.document_name}${pageLabel(c) ? `, ${pageLabel(c)}` : ""}`}
                          className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-1 items-center justify-center rounded bg-brand-100 px-1 align-baseline text-[10px] font-semibold text-brand-700 hover:bg-brand-600 hover:text-white dark:bg-brand-500/20 dark:text-brand-300">
                          {match[1]}
                        </button>
                      );
                    }
                    return <a href={href} target="_blank" rel="noopener noreferrer">{children as ReactNode}</a>;
                  },
                }}>
                {content}
              </ReactMarkdown>
              {m.pending && m.content && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-brand-500 align-middle" />}
            </div>
          )}
        </div>

        {!m.pending && !m.error && (
          <>
            {m.citations.length > 0 && (
              <div className="mt-3">
                <div className="mb-2 text-[11px] font-semibold tracking-wide text-slate-500 uppercase">Sources</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {m.citations.map((c) => <CitationCard key={`${c.index}-${c.chunk_id}`} c={c} onOpen={onOpenCitation} />)}
                </div>
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1 text-slate-500">
              <button className="btn-ghost p-1.5" onClick={copy} title="Copy answer" aria-label="Copy answer">
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
              {isLast && onRegenerate && (
                <button className="btn-ghost p-1.5" onClick={onRegenerate} title="Regenerate" aria-label="Regenerate answer">
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
              )}
              {onFeedback && (
                <>
                  <button className={clsx("btn-ghost p-1.5", m.feedback === 1 && "text-emerald-600")} title="Helpful" aria-pressed={m.feedback === 1}
                    onClick={() => onFeedback(m.feedback === 1 ? 0 : 1)}><ThumbsUp className="h-3.5 w-3.5" /></button>
                  <button className={clsx("btn-ghost p-1.5", m.feedback === -1 && "text-red-600")} title="Not helpful" aria-pressed={m.feedback === -1}
                    onClick={() => onFeedback(m.feedback === -1 ? 0 : -1)}><ThumbsDown className="h-3.5 w-3.5" /></button>
                </>
              )}
              {grounded !== undefined && (
                <span className={clsx("ml-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                  grounded ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
                    : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400")}>
                  {grounded ? `Grounded in ${m.citations.length} source${m.citations.length === 1 ? "" : "s"}` : "No supporting sources"}
                </span>
              )}
              {m.meta?.latency_ms != null && <span className="ml-1 text-[10px]">{(m.meta.latency_ms / 1000).toFixed(1)}s</span>}
              {m.meta?.rewritten_query && (
                <span className="ml-1 truncate text-[10px]" title="Follow-up resolved to this standalone query">
                  ↳ searched: “{m.meta.rewritten_query}”
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
