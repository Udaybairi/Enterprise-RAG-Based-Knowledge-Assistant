"use client";

import clsx from "clsx";
import { MessageSquarePlus, MessagesSquare, RotateCcw, Send, SlidersHorizontal, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ChatMessageView } from "@/components/ChatMessage";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, Stagger, StaggerItem } from "@/components/motion";
import { ConfirmDialog, ErrorBanner, Skeleton } from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { api, timeAgo } from "@/services/api";
import type { ChatMessage, Citation, ConversationSummary, RetrievalOptions } from "@/types";

const tmpId = () => `tmp-${Math.random().toString(36).slice(2)}`;

export default function ChatPage() {
  const history = useAsync(() => api.history());
  const collections = useAsync(() => api.collections());
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [options, setOptions] = useState<RetrievalOptions>({ strategy: "hybrid", top_k: 6, reranker: "lexical", use_query_rewriting: true, multi_query: true });
  const [showOptions, setShowOptions] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [loadingConv, setLoadingConv] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [toDelete, setToDelete] = useState<ConversationSummary | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.suggestions(selected).then(setSuggestions).catch(() => setSuggestions([]));
  }, [selected]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth", block: "end" });
  }, [messages, streaming]);

  const openConversation = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setLoadingConv(true);
    setError(null);
    try {
      const c = await api.conversation(id);
      setConversationId(c.id);
      setMessages(c.messages);
      setSelected(c.collection_ids ?? []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingConv(false);
    }
  }, []);

  const newChat = () => {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setError(null);
    textareaRef.current?.focus();
  };

  const send = async (text: string, regenerate = false) => {
    const question = text.trim();
    if (!question || streaming) return;
    setError(null);
    const assistantId = tmpId();
    const pending: ChatMessage = { id: assistantId, role: "assistant", content: "", citations: [], meta: {}, feedback: 0, created_at: new Date().toISOString(), pending: true, status: "Understanding the question…" };
    setMessages((prev) => {
      let base = prev;
      if (regenerate) {
        while (base.length && base[base.length - 1].role === "assistant") base = base.slice(0, -1);
      } else {
        base = [...base, { id: tmpId(), role: "user", content: question, citations: [], meta: {}, feedback: 0, created_at: new Date().toISOString() }];
      }
      return [...base, pending];
    });
    setInput("");
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));
    try {
      await api.streamChat(
        { message: question, conversation_id: conversationId, collection_ids: selected.length ? selected : undefined, options, regenerate },
        (ev) => {
          switch (ev.type) {
            case "meta":
              setConversationId(ev.conversation_id);
              break;
            case "status":
              patch((m) => ({ ...m, status: ev.message + "…" }));
              break;
            case "token":
              patch((m) => ({ ...m, content: m.content + ev.content }));
              break;
            case "final":
              patch((m) => ({
                ...m, id: ev.message_id, content: ev.answer, citations: ev.citations, pending: false,
                meta: { grounded: ev.grounded, rewritten_query: ev.rewritten_query, latency_ms: ev.latency_ms, retrieval: ev.retrieval },
              }));
              break;
            case "error":
              patch((m) => ({ ...m, pending: false, error: ev.message }));
              break;
          }
        },
        ctrl.signal,
      );
      // stopped by user before the final event
      patch((m) => (m.pending ? { ...m, pending: false, content: m.content || "_Generation stopped._" } : m));
    } catch (e) {
      patch((m) => ({ ...m, pending: false, error: (e as Error).message }));
    } finally {
      setStreaming(false);
      abortRef.current = null;
      void history.reload(true);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  const lastUser = [...messages].reverse().find((m) => m.role === "user");

  const feedback = async (m: ChatMessage, rating: number) => {
    setMessages((prev) => prev.map((x) => (x.id === m.id ? { ...x, feedback: rating } : x)));
    try {
      await api.feedback(m.id, rating);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const openCitation = (c: Citation) =>
    setViewer({ documentId: c.document_id, documentName: c.document_name, fileType: c.file_type, page: c.page_number, snippet: c.snippet });

  const deleteConversation = async () => {
    if (!toDelete) return;
    try {
      await api.deleteConversation(toDelete.id);
      if (toDelete.id === conversationId) newChat();
      setToDelete(null);
      void history.reload(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggleCollection = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  return (
    <div className="flex h-full">
      {/* conversation history */}
      <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200/70 bg-white/60 backdrop-blur-xl md:flex dark:border-white/[0.06] dark:bg-surface-dark/40">
        <div className="p-3">
          <button className="btn-primary w-full" onClick={newChat}><MessageSquarePlus className="h-4 w-4" />New chat</button>
        </div>
        <div className="px-4 pt-2 pb-2 text-[10px] font-semibold tracking-[0.14em] text-slate-400 uppercase">History</div>
        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {history.loading && !history.data && (
            <div className="space-y-2 px-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-11 rounded-xl" />)}</div>
          )}
          {history.data?.length === 0 && <p className="px-2 text-xs text-slate-500">No conversations yet.</p>}
          {history.data?.map((c, i) => (
            <motion.div key={c.id} className="group relative flex items-center rounded-xl"
              initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i, 10) * 0.03 }}>
              {c.id === conversationId && (
                <motion.span layoutId="conv-active" className="absolute inset-0 rounded-xl bg-gradient-to-r from-brand-500/[0.12] to-transparent ring-1 ring-brand-500/20 dark:from-brand-400/20"
                  transition={{ type: "spring", stiffness: 420, damping: 36 }} />
              )}
              <button className="relative min-w-0 flex-1 rounded-xl px-3 py-2 text-left transition-colors hover:bg-slate-900/[0.03] dark:hover:bg-white/[0.04]" onClick={() => openConversation(c.id)}>
                <div className="truncate text-sm font-medium">{c.title}</div>
                <div className="text-[11px] text-slate-500">{timeAgo(c.updated_at)} · {c.message_count} msgs</div>
              </button>
              <button className="relative mr-1 rounded-lg p-1.5 text-slate-400 opacity-0 transition group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 dark:hover:bg-rose-500/10"
                onClick={() => setToDelete(c)} aria-label={`Delete conversation ${c.title}`}><Trash2 className="h-3.5 w-3.5" /></button>
            </motion.div>
          ))}
        </div>
      </aside>

      {/* workspace */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="glass flex flex-wrap items-center gap-2 border-x-0 border-t-0 px-4 py-2.5">
          <button className="btn-ghost p-1.5 md:hidden" onClick={newChat} aria-label="New chat"><MessageSquarePlus className="h-4 w-4" /></button>
          <span className="text-xs font-medium text-slate-500">Search in:</span>
          <CollectionChip active={selected.length === 0} onClick={() => setSelected([])}>All collections</CollectionChip>
          {collections.data?.map((c) => (
            <CollectionChip key={c.id} active={selected.includes(c.id)} onClick={() => toggleCollection(c.id)}>
              {c.name} <span className="opacity-70">({c.document_count})</span>
            </CollectionChip>
          ))}
          <button className={clsx("btn-ghost ml-auto px-2.5 py-1 text-xs", showOptions && "bg-slate-900/[0.05] dark:bg-white/[0.08]")}
            onClick={() => setShowOptions((v) => !v)} aria-expanded={showOptions}>
            <SlidersHorizontal className="h-3.5 w-3.5" />Retrieval
          </button>
        </div>
        <AnimatePresence initial={false}>
          {showOptions && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE_OUT }} className="overflow-hidden">
              <OptionsPanel options={options} setOptions={setOptions} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-7 px-4 py-8">
            {error && <ErrorBanner message={error} />}
            {loadingConv ? (
              <div className="space-y-6">
                <Skeleton className="ml-auto h-12 w-2/3 rounded-3xl" />
                <Skeleton className="h-32 w-full rounded-2xl" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-col items-center pt-6 text-center sm:pt-12">
                <Orb />
                <motion.h2 className="mt-8 text-2xl font-semibold tracking-tight sm:text-3xl"
                  initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.5, ease: EASE_OUT }}>
                  Ask your <span className="text-gradient">knowledge base</span>
                </motion.h2>
                <motion.p className="mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}>
                  Answers come only from your uploaded documents, and every claim links to its source.
                </motion.p>
                {suggestions.length > 0 && (
                  <Stagger className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-2">
                    {suggestions.map((s) => (
                      <StaggerItem key={s}>
                        <button className="card-interactive group flex h-full w-full items-start gap-3 px-4 py-3.5 text-left text-sm" onClick={() => send(s)}>
                          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 transition-colors group-hover:bg-brand-gradient group-hover:text-white dark:bg-brand-400/10 dark:text-brand-300">
                            <MessagesSquare className="h-3.5 w-3.5" />
                          </span>
                          <span className="pt-0.5">{s}</span>
                        </button>
                      </StaggerItem>
                    ))}
                  </Stagger>
                )}
              </div>
            ) : (
              messages.map((m, i) => (
                <ChatMessageView key={m.id} m={m} isLast={i === messages.length - 1}
                  onOpenCitation={openCitation}
                  onRegenerate={!streaming && lastUser ? () => send(lastUser.content, true) : undefined}
                  onFeedback={m.role === "assistant" && !m.id.startsWith("tmp-") ? (r) => feedback(m, r) : undefined} />
              ))
            )}
            {!streaming && !loadingConv && messages.at(-1)?.role === "user" && (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className="flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200" role="status">
                <span>This question has no answer yet. The previous response may have been interrupted.</span>
                <button className="btn-secondary shrink-0 px-2.5 py-1.5 text-xs" onClick={() => send(messages.at(-1)!.content, true)}>
                  <RotateCcw className="h-3.5 w-3.5" />Retry
                </button>
              </motion.div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <form onSubmit={onSubmit} className="px-4 pt-2 pb-4">
          <div className="mx-auto max-w-3xl">
            <div className="group relative rounded-[1.4rem] bg-gradient-to-r from-brand-500/40 via-accent-500/30 to-cyan-400/30 p-px shadow-lift transition-shadow focus-within:from-brand-500 focus-within:via-accent-500 focus-within:to-cyan-400 focus-within:shadow-glow">
              <div className="flex items-end gap-2 rounded-[calc(1.4rem-1px)] bg-white/95 p-2 backdrop-blur-xl dark:bg-surface-dark/95">
                <textarea ref={textareaRef} rows={1} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown}
                  placeholder="Ask about your documents…" aria-label="Message" maxLength={4000}
                  className="max-h-40 min-h-[44px] w-full resize-none bg-transparent px-3 py-2.5 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none sm:text-sm dark:text-slate-100" />
                <AnimatePresence mode="wait" initial={false}>
                  {streaming ? (
                    <motion.button key="stop" type="button" className="btn-secondary h-11 w-11 shrink-0 rounded-2xl p-0" onClick={() => abortRef.current?.abort()} aria-label="Stop generating"
                      initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }}>
                      <Square className="h-4 w-4 fill-current" />
                    </motion.button>
                  ) : (
                    <motion.button key="send" className="btn-primary h-11 w-11 shrink-0 rounded-2xl p-0" disabled={!input.trim()} aria-label="Send"
                      initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }}
                      whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.92 }}>
                      <Send className="h-4 w-4" />
                    </motion.button>
                  )}
                </AnimatePresence>
              </div>
            </div>
            <p className="mt-2.5 text-center text-[11px] text-slate-500">
              Answers are grounded in your documents. Verify important information using the cited sources.
            </p>
          </div>
        </form>
      </section>

      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
      <ConfirmDialog open={!!toDelete} title="Delete conversation" message={`Delete "${toDelete?.title}"? This cannot be undone.`}
        onCancel={() => setToDelete(null)} onConfirm={deleteConversation} />
    </div>
  );
}

function OptionsPanel({ options, setOptions }: { options: RetrievalOptions; setOptions: (o: RetrievalOptions) => void }) {
  const set = <K extends keyof RetrievalOptions>(k: K, v: RetrievalOptions[K]) => setOptions({ ...options, [k]: v });
  return (
    <div className="grid gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 sm:grid-cols-2 lg:grid-cols-5 dark:border-slate-800 dark:bg-slate-900/60">
      <div>
        <label className="label" htmlFor="o-s">Strategy</label>
        <select id="o-s" className="input py-1.5" value={options.strategy} onChange={(e) => set("strategy", e.target.value as RetrievalOptions["strategy"])}>
          <option value="hybrid">Hybrid (vector + BM25)</option>
          <option value="semantic">Semantic</option>
          <option value="mmr">MMR (diverse)</option>
          <option value="keyword">Keyword (BM25)</option>
        </select>
      </div>
      <div>
        <label className="label" htmlFor="o-r">Reranker</label>
        <select id="o-r" className="input py-1.5" value={options.reranker} onChange={(e) => set("reranker", e.target.value as RetrievalOptions["reranker"])}>
          <option value="lexical">Lexical cross-scorer</option>
          <option value="llm">Gemini (LLM)</option>
          <option value="none">None</option>
        </select>
      </div>
      <div>
        <label className="label" htmlFor="o-k">Chunks to retrieve: {options.top_k}</label>
        <input id="o-k" type="range" min={1} max={15} value={options.top_k} onChange={(e) => set("top_k", +e.target.value)} className="w-full accent-brand-600" />
      </div>
      <div>
        <label className="label" htmlFor="o-t">Similarity threshold: {options.similarity_threshold?.toFixed(2) ?? "default"}</label>
        <input id="o-t" type="range" min={0} max={0.9} step={0.05} value={options.similarity_threshold ?? 0.45}
          onChange={(e) => set("similarity_threshold", +e.target.value)} className="w-full accent-brand-600" />
      </div>
      <div className="flex flex-col justify-center gap-1.5 text-xs">
        <label className="flex items-center gap-2"><input type="checkbox" checked={options.use_query_rewriting} onChange={(e) => set("use_query_rewriting", e.target.checked)} />Rewrite follow-ups</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={options.multi_query} onChange={(e) => set("multi_query", e.target.checked)} />Multi-query expansion</label>
      </div>
    </div>
  );
}

function CollectionChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <motion.button layout onClick={onClick} whileTap={{ scale: 0.95 }}
      className={clsx("chip", active
        ? "bg-brand-gradient text-white shadow-glow ring-transparent"
        : "bg-white/70 text-slate-600 ring-slate-200 hover:ring-brand-300 dark:bg-white/[0.04] dark:text-slate-300 dark:ring-white/10")}>
      {children}
    </motion.button>
  );
}

/** Animated gradient orb for the empty chat state. */
function Orb() {
  return (
    <motion.div className="relative h-28 w-28" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.7, ease: EASE_OUT }}>
      <div className="absolute inset-0 rounded-full bg-brand-500/30 blur-2xl" />
      <motion.div className="absolute inset-0 rounded-full bg-[conic-gradient(from_0deg,#6366f1,#8b5cf6,#22d3ee,#6366f1)] opacity-90"
        animate={{ rotate: 360 }} transition={{ duration: 12, repeat: Infinity, ease: "linear" }} />
      <div className="absolute inset-[3px] rounded-full bg-[radial-gradient(circle_at_30%_25%,rgb(255_255_255/0.95),rgb(224_231_255/0.9)_35%,rgb(99_102_241/0.85)_75%)] dark:bg-[radial-gradient(circle_at_30%_25%,rgb(199_210_254/0.9),rgb(99_102_241/0.85)_45%,rgb(30_27_75)_85%)]" />
      <motion.div className="absolute inset-0 flex items-center justify-center"
        animate={{ y: [0, -4, 0] }} transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}>
        <svg viewBox="0 0 24 24" className="h-10 w-10 text-white drop-shadow" fill="currentColor" aria-hidden>
          <path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2Zm6 12l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9L18 14Z" />
        </svg>
      </motion.div>
      <span className="absolute inset-0 rounded-full ring-2 ring-brand-400/40 animate-pulse-ring" />
    </motion.div>
  );
}
