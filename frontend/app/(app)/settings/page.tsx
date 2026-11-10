"use client";

import { CheckCircle2, RefreshCw, Shield, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ErrorBanner, PageHeader, Spinner, Toast } from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { api, formatDate } from "@/services/api";

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-100 py-2 text-sm last:border-0 dark:border-slate-800">
      <span className="text-slate-500">{k}</span><span className="text-right font-medium">{v}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const settings = useAsync(() => api.settings());
  const isAdmin = user?.role === "admin";
  const users = useAsync(() => (isAdmin ? api.users() : Promise.resolve([])), [isAdmin]);
  const audit = useAsync(() => (isAdmin ? api.auditLogs(100) : Promise.resolve([])), [isAdmin]);
  const [checking, setChecking] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const s = settings.data;
  const ms = s?.model_status as { ok?: boolean; message?: string; models?: Record<string, { model: string; available: boolean; supports: boolean }> } | undefined;

  const recheck = async () => {
    setChecking(true);
    try {
      await api.checkModels();
      await settings.reload(true);
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const updateUser = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      void users.reload(true);
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6 lg:p-8">
      <PageHeader title="Settings" description="Appearance, AI configuration and administration." />
      {settings.error && <ErrorBanner message={settings.error} />}

      <Section title="Appearance">
        <div className="flex gap-2">
          {(["light", "dark", "system"] as Theme[]).map((t) => (
            <button key={t} className={theme === t ? "btn-primary" : "btn-secondary"} onClick={() => setTheme(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
          ))}
        </div>
      </Section>

      <Section title="AI models" description="Configured through environment variables on the server; API keys are never exposed to the browser.">
        {!s ? <Spinner /> : (
          <>
            <Row k="Provider" v={s.llm_provider} />
            <Row k="Generation model" v={s.chat_model} />
            <Row k="Utility model (rewrite / rerank)" v={s.utility_model} />
            <Row k="Embedding model" v={`${s.embedding_model} (${s.embedding_dimension} dims)`} />
            <Row k="Vector store" v={s.vector_store} />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {ms?.ok ? <span className="flex items-center gap-1.5 text-sm text-emerald-600"><CheckCircle2 className="h-4 w-4" />{ms.message ?? "Models available"}</span>
                : <span className="flex items-center gap-1.5 text-sm text-amber-600"><XCircle className="h-4 w-4" />{ms?.message ?? "Model availability not verified yet"}</span>}
              <button className="btn-secondary px-2.5 py-1.5 text-xs" onClick={recheck} disabled={checking}>
                {checking ? <Spinner className="h-3.5 w-3.5" /> : <RefreshCw className="h-3.5 w-3.5" />}Verify models
              </button>
            </div>
            {ms?.models && (
              <ul className="mt-3 space-y-1 text-xs">
                {Object.entries(ms.models).map(([role, m]) => (
                  <li key={role} className="flex items-center gap-2">
                    {m.available && m.supports ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <XCircle className="h-3.5 w-3.5 text-red-600" />}
                    <span className="w-20 text-slate-500">{role}</span><code>{m.model}</code>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Section>

      {s && (
        <div className="grid gap-6 md:grid-cols-2">
          <Section title="Ingestion defaults">
            <Row k="Chunking strategy" v={s.chunking.strategy} />
            <Row k="Chunk size / overlap" v={`${s.chunking.chunk_size} / ${s.chunking.chunk_overlap} chars`} />
            <Row k="Max upload size" v={`${s.upload.max_size_mb} MB`} />
            <Row k="Allowed types" v={s.upload.allowed_extensions.join(" ")} />
          </Section>
          <Section title="Retrieval defaults" description="Override per question from the chat Retrieval panel.">
            <Row k="Strategy" v={s.retrieval.strategy} />
            <Row k="Top-k" v={s.retrieval.top_k} />
            <Row k="Similarity threshold" v={s.retrieval.similarity_threshold} />
            <Row k="Reranker" v={s.retrieval.reranker} />
            <Row k="Query rewriting" v={s.retrieval.query_rewriting ? "on" : "off"} />
            <Row k="Multi-query expansions" v={s.retrieval.multi_query_count} />
          </Section>
        </div>
      )}

      {isAdmin && (
        <>
          <Section title="Users & roles" description="Administrators manage all collections, users and evaluations.">
            {users.loading && !users.data ? <Spinner /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-slate-500 uppercase"><tr><th className="py-2">User</th><th>Role</th><th>Status</th><th>Joined</th><th /></tr></thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {users.data?.map((u) => (
                      <tr key={u.id}>
                        <td className="py-2"><div className="font-medium">{u.full_name || "—"}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                        <td>
                          <select className="input w-auto py-1 text-xs" value={u.role} disabled={u.id === user?.id}
                            onChange={(e) => updateUser(() => api.setRole(u.id, e.target.value))} aria-label={`Role for ${u.email}`}>
                            <option value="user">user</option><option value="admin">admin</option>
                          </select>
                        </td>
                        <td className="text-xs">{u.is_active ? "Active" : "Disabled"}</td>
                        <td className="text-xs text-slate-500">{formatDate(u.created_at)}</td>
                        <td className="text-right">
                          {u.id !== user?.id && (
                            <button className="btn-ghost px-2 py-1 text-xs" onClick={() => updateUser(() => api.setActive(u.id, !u.is_active))}>
                              {u.is_active ? "Disable" : "Enable"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
          <Section title="Audit log" description="Security-relevant actions across the platform (latest 100).">
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white text-left text-slate-500 uppercase dark:bg-slate-900"><tr><th className="py-2">Time</th><th>User</th><th>Action</th><th>Resource</th><th>IP</th></tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {audit.data?.map((a) => (
                    <tr key={a.id}>
                      <td className="py-1.5 whitespace-nowrap">{formatDate(a.created_at)}</td>
                      <td>{a.user_email ?? "—"}</td>
                      <td><span className="inline-flex items-center gap-1"><Shield className="h-3 w-3 text-slate-400" />{a.action}</span></td>
                      <td className="text-slate-500">{a.resource_type ? `${a.resource_type}:${a.resource_id?.slice(0, 8) ?? ""}` : "—"}</td>
                      <td className="text-slate-500">{a.ip_address ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
      {toast && <Toast message={toast} tone="error" onClose={() => setToast(null)} />}
    </div>
  );
}
