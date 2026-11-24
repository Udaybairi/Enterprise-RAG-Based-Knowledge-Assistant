"use client";

import clsx from "clsx";
import { AlertTriangle, Check, Copy, FileText, RefreshCw, ShieldCheck, ThumbsDown, ThumbsUp } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage as Msg, Citation } from "@/types";
import { Logo } from "./Logo";
import { EASE_OUT } from "./motion";

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
      className={clsx("card-interactive group w-full p-3.5 text-left",
        active && "border-brand-500 ring-2 ring-brand-500/20")}>
      <div className="flex items-start gap-2.5">
        <span className="flex h-5 min-w-5 items-center justify-center rounded-md bg-brand-gradient px-1 text-[11px] font-semibold text-white shadow-glow">{c.index}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            <span className="truncate">{c.document_name}</span>
            {page && <span className="shrink-0 text-slate-500">· {page}</span>}
          </div>
          {c.section && <div className="mt-0.5 truncate text-[11px] text-slate-500">§ {c.section}</div>}
          <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-slate-600 dark:text-slate-400">“{c.snippet}”</p>
          {c.vector_score != null && (
            <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500"
              title="Cosine similarity between the question and this passage's embedding. It indicates closeness in meaning, not a calibrated probability that the passage is correct.">
              <span>Similarity</span>
              <span className="h-1 w-16 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                <motion.span className="block h-full rounded-full bg-gradient-to-r from-brand-500 to-accent-500"
                  initial={{ width: 0 }} animate={{ width: `${Math.min(100, Math.max(5, c.vector_score * 100))}%` }}
                  transition={{ duration: 0.8, ease: EASE_OUT, delay: 0.2 }} />
              </span>
              <span className="tabular-nums">{c.vector_score.toFixed(2)}</span>
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
      <motion.div className="flex justify-end" initial={{ opacity: 0, x: 24, scale: 0.98 }} animate={{ opacity: 1, x: 0, scale: 1 }}
        transition={{ duration: 0.4, ease: EASE_OUT }}>
        <div className="max-w-[85%] rounded-3xl rounded-br-md bg-brand-gradient px-4.5 py-3 text-[0.94rem] leading-relaxed whitespace-pre-wrap text-white shadow-[0_10px_30px_-12px_rgb(79_70_229/0.7)]">{m.content}</div>
      </motion.div>
    );
  }

  const copy = async () => {
    await navigator.clipboard.writeText(m.content.replace(/\n\n> ⚠️.*$/s, ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const grounded = m.meta?.grounded;
  return (
    <motion.div className="flex gap-3" initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.45, ease: EASE_OUT }}>
      <div className="mt-0.5"><Logo size="sm" /></div>
      <div className="min-w-0 flex-1">
        <div className="card px-5 py-4">
          {m.pending && !m.content && (
            <div className="flex items-center gap-3 text-sm">
              <TypingDots />
              <motion.span key={m.status} className="bg-[linear-gradient(90deg,rgb(100_116_139)_0%,rgb(99_102_241)_50%,rgb(100_116_139)_100%)] bg-[length:200%_100%] bg-clip-text text-transparent animate-shimmer"
                initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
                {m.status || "Thinking…"}
              </motion.span>
            </div>
          )}
          {m.error ? (
            <div className="flex items-start gap-2 text-sm text-rose-600 dark:text-rose-400"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{m.error}</div>
          ) : (
            <div className={clsx("prose-chat", m.pending && m.content && "caret")}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const match = href?.match(/^#cite-(\d+)$/);
                    if (match) {
                      const c = byIndex.get(Number(match[1]));
                      if (!c) return m.pending ? <sup className="text-[10px] text-slate-400">[{match[1]}]</sup> : null;
                      return (
                        <button onClick={() => onOpenCitation(c)} title={`${c.document_name}${pageLabel(c) ? `, ${pageLabel(c)}` : ""}`}
                          className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-1 items-center justify-center rounded-md bg-brand-100 px-1 align-baseline text-[10px] font-semibold text-brand-700 transition-all hover:scale-110 hover:bg-brand-600 hover:text-white hover:shadow-glow dark:bg-brand-400/20 dark:text-brand-200">
                          {match[1]}
                        </button>
                      );
                    }
                    return <a href={href} target="_blank" rel="noopener noreferrer">{children as ReactNode}</a>;
                  },
                }}>
                {content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {!m.pending && !m.error && (
          <>
            {m.citations.length > 0 && (
              <div className="mt-4">
                <div className="mb-2 text-[11px] font-semibold tracking-[0.12em] text-slate-500 uppercase">Sources</div>
                <div className="grid gap-2.5 sm:grid-cols-2">
                  {m.citations.map((c, i) => (
                    <motion.div key={`${c.index}-${c.chunk_id}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.4, ease: EASE_OUT, delay: 0.1 + i * 0.07 }}>
                      <CitationCard c={c} onOpen={onOpenCitation} />
                    </motion.div>
                  ))}
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
                <span className={clsx("ml-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset",
                  grounded ? "bg-emerald-50 text-emerald-700 ring-emerald-600/15 dark:bg-emerald-400/10 dark:text-emerald-300"
                    : "bg-slate-100 text-slate-600 ring-slate-500/15 dark:bg-white/5 dark:text-slate-400")}>
                  {grounded && <ShieldCheck className="h-3 w-3" />}
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
    </motion.div>
  );
}

function TypingDots() {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-brand-500"
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15, ease: "easeInOut" }} />
      ))}
    </span>
  );
}
