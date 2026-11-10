"use client";

import clsx from "clsx";
import { MessageSquarePlus, MessagesSquare, Send, SlidersHorizontal, Sparkles, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ChatMessageView } from "@/components/ChatMessage";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { ConfirmDialog, EmptyState, ErrorBanner, Spinner } from "@/components/ui";
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
      <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 bg-white md:flex dark:border-slate-800 dark:bg-slate-900">
        <div className="p-3">
          <button className="btn-primary w-full" onClick={newChat}><MessageSquarePlus className="h-4 w-4" />New chat</button>
        </div>
        <div className="px-4 pb-2 text-[11px] font-semibold tracking-wide text-slate-500 uppercase">History</div>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {history.loading && !history.data && <div className="flex justify-center py-6"><Spinner /></div>}
          {history.data?.length === 0 && <p className="px-2 text-xs text-slate-500">No conversations yet.</p>}
          {history.data?.map((c) => (
            <div key={c.id} className={clsx("group flex items-center rounded-lg",
              c.id === conversationId ? "bg-brand-50 dark:bg-brand-500/10" : "hover:bg-slate-100 dark:hover:bg-slate-800")}>
              <button className="min-w-0 flex-1 px-3 py-2 text-left" onClick={() => openConversation(c.id)}>
                <div className="truncate text-sm">{c.title}</div>
                <div className="text-[11px] text-slate-500">{timeAgo(c.updated_at)} · {c.message_count} msgs</div>
              </button>
              <button className="mr-1 rounded p-1.5 text-slate-400 opacity-0 group-hover:opacity-100 hover:text-red-600 focus:opacity-100"
                onClick={() => setToDelete(c)} aria-label={`Delete conversation ${c.title}`}><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      </aside>

      {/* workspace */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
          <button className="btn-ghost p-1.5 md:hidden" onClick={newChat} aria-label="New chat"><MessageSquarePlus className="h-4 w-4" /></button>
          <span className="text-xs font-medium text-slate-500">Search in:</span>
          <button onClick={() => setSelected([])}
            className={clsx("rounded-full px-2.5 py-1 text-xs font-medium ring-1", selected.length === 0 ? "bg-brand-600 text-white ring-brand-600" : "ring-slate-200 dark:ring-slate-700")}>
            All collections
          </button>
          {collections.data?.map((c) => (
            <button key={c.id} onClick={() => toggleCollection(c.id)}
              className={clsx("rounded-full px-2.5 py-1 text-xs font-medium ring-1", selected.includes(c.id) ? "bg-brand-600 text-white ring-brand-600" : "ring-slate-200 dark:ring-slate-700")}>
              {c.name} <span className="opacity-70">({c.document_count})</span>
            </button>
          ))}
          <button className={clsx("btn-ghost ml-auto px-2 py-1 text-xs", showOptions && "bg-slate-100 dark:bg-slate-800")}
            onClick={() => setShowOptions((v) => !v)} aria-expanded={showOptions}>
            <SlidersHorizontal className="h-3.5 w-3.5" />Retrieval
          </button>
        </div>
        {showOptions && <OptionsPanel options={options} setOptions={setOptions} />}

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {error && <ErrorBanner message={error} />}
            {loadingConv ? (
              <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>
            ) : messages.length === 0 ? (
              <div className="pt-10">
                <EmptyState icon={<Sparkles className="h-5 w-5" />} title="Ask your knowledge base"
                  description="Answers are generated only from your uploaded documents and every claim links to its source." />
                {suggestions.length > 0 && (
                  <div className="mx-auto grid max-w-2xl gap-2 sm:grid-cols-2">
                    {suggestions.map((s) => (
                      <button key={s} className="card px-4 py-3 text-left text-sm hover:border-brand-400" onClick={() => send(s)}>
                        <MessagesSquare className="mb-1 h-4 w-4 text-brand-600" />{s}
                      </button>
                    ))}
                  </div>
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
            <div ref={bottomRef} />
          </div>
        </div>

        <form onSubmit={onSubmit} className="border-t border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea ref={textareaRef} rows={1} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown}
              placeholder="Ask a question about your documents…" aria-label="Message" maxLength={4000}
              className="input max-h-40 min-h-[42px] resize-none py-2.5" />
            {streaming ? (
              <button type="button" className="btn-secondary h-[42px]" onClick={() => abortRef.current?.abort()} aria-label="Stop generating">
                <Square className="h-4 w-4" />
              </button>
            ) : (
              <button className="btn-primary h-[42px]" disabled={!input.trim()} aria-label="Send"><Send className="h-4 w-4" /></button>
            )}
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-500">
            Answers are grounded in your documents. Verify important information using the cited sources.
          </p>
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
