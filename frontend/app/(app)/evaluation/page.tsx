"use client";

import { FlaskConical, Play, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmptyState, ErrorBanner, PageHeader, Spinner, StatusBadge, Toast } from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { api, formatDate } from "@/services/api";
import type { EvalConfigResult, EvalMetrics } from "@/types";

const CHUNKING = ["recursive", "token", "structure", "semantic"];
const RETRIEVAL = ["semantic", "hybrid", "mmr", "keyword"];
const COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6", "#ec4899", "#84cc16", "#64748b", "#0ea5e9", "#a855f7", "#14b8a6"];
const METRICS: { key: keyof EvalMetrics; label: string; invert?: boolean }[] = [
  { key: "precision", label: "Precision@k" }, { key: "recall", label: "Recall@k" }, { key: "mrr", label: "MRR" },
  { key: "context_relevance", label: "Context relevance" }, { key: "answer_relevance", label: "Answer relevance" },
  { key: "faithfulness", label: "Faithfulness" }, { key: "citation_accuracy", label: "Citation accuracy" },
  { key: "answer_correctness", label: "Answer F1" }, { key: "hallucination_rate", label: "Hallucination rate", invert: true },
  { key: "refusal_accuracy", label: "Refusal accuracy" },
];

const fmt = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(3));

export default function EvaluationPage() {
  const { user } = useAuth();
  const runs = useAsync(() => api.evaluationRuns());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [chunking, setChunking] = useState(["recursive", "structure", "semantic"]);
  const [retrieval, setRetrieval] = useState(["semantic", "hybrid", "mmr"]);
  const [topK, setTopK] = useState(4);
  const [generation, setGeneration] = useState(true);
  const [toast, setToast] = useState<string | null>(null);

  const running = runs.data?.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => runs.reload(true), 3000);
    return () => clearInterval(t);
  }, [running, runs.reload]);

  const run = runs.data?.find((r) => r.id === selectedId) ?? runs.data?.find((r) => r.status === "completed") ?? runs.data?.[0];
  const configs: EvalConfigResult[] = run?.results?.configs ?? [];
  const label = (c: EvalConfigResult) => `${c.chunking} + ${c.retrieval}`;

  const radarData = useMemo(() => METRICS.filter((m) => configs.some((c) => c.metrics[m.key] != null)).map((m) => {
    const row: Record<string, string | number> = { metric: m.label };
    configs.forEach((c) => {
      const v = (c.metrics[m.key] as number | null) ?? 0;
      row[label(c)] = m.invert ? 1 - v : v;
    });
    return row;
  }), [configs]);

  const start = async () => {
    try {
      const r = await api.runEvaluation({ chunking_strategies: chunking, retrieval_strategies: retrieval, top_k: topK, evaluate_generation: generation });
      setSelectedId(r.id);
      void runs.reload(true);
      setToast("Evaluation started");
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const toggle = (list: string[], set: (v: string[]) => void, v: string) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <PageHeader title="RAG evaluation"
        description="Compare chunking and retrieval strategies on a gold question → answer → source dataset." />
      {runs.error && <ErrorBanner message={runs.error} onRetry={() => runs.reload()} />}

      {user?.role === "admin" && (
        <div className="card mb-6 grid gap-4 p-5 md:grid-cols-[1fr_1fr_auto_auto] md:items-end">
          <div>
            <span className="label">Chunking strategies</span>
            <div className="flex flex-wrap gap-2">{CHUNKING.map((s) => (
              <label key={s} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={chunking.includes(s)} onChange={() => toggle(chunking, setChunking, s)} />{s}</label>
            ))}</div>
          </div>
          <div>
            <span className="label">Retrieval strategies</span>
            <div className="flex flex-wrap gap-2">{RETRIEVAL.map((s) => (
              <label key={s} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={retrieval.includes(s)} onChange={() => toggle(retrieval, setRetrieval, s)} />{s}</label>
            ))}</div>
          </div>
          <div className="flex items-center gap-4">
            <div><label className="label" htmlFor="ev-k">Top-k</label>
              <input id="ev-k" type="number" min={1} max={20} className="input w-20" value={topK} onChange={(e) => setTopK(+e.target.value)} /></div>
            <label className="mt-5 flex items-center gap-1.5 text-sm"><input type="checkbox" checked={generation} onChange={(e) => setGeneration(e.target.checked)} />Evaluate answers</label>
          </div>
          <button className="btn-primary" onClick={start} disabled={running || !chunking.length || !retrieval.length}>
            {running ? <Spinner /> : <Play className="h-4 w-4" />}{running ? "Running…" : "Run evaluation"}
          </button>
        </div>
      )}

      {runs.loading && !runs.data ? <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div> :
        !run ? (
          <div className="card"><EmptyState icon={<FlaskConical className="h-5 w-5" />} title="No evaluation runs yet"
            description={user?.role === "admin" ? "Start a run above to benchmark strategies." : "An administrator can start an evaluation run."} /></div>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <select className="input w-auto" value={run.id} onChange={(e) => setSelectedId(e.target.value)} aria-label="Evaluation run">
                {runs.data?.map((r) => <option key={r.id} value={r.id}>{formatDate(r.created_at)} · {r.status}</option>)}
              </select>
              <StatusBadge status={run.status} />
              {run.results?.dataset_size != null && (
                <span className="text-xs text-slate-500">{run.results.dataset_size} questions · provider {run.results.provider} · {run.results.embedding_model} · {run.results.duration_s}s</span>
              )}
            </div>
            {run.status === "failed" && <ErrorBanner message={run.error_message ?? "Evaluation failed"} />}
            {run.status === "running" && <div className="card flex items-center justify-center gap-2 py-16 text-sm text-slate-500"><Spinner />Evaluating configurations…</div>}
            {configs.length > 0 && (
              <>
                {run.results.best && (
                  <div className="card mb-6 flex items-center gap-3 border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/30">
                    <Trophy className="h-5 w-5 text-emerald-600" />
                    <div className="text-sm"><span className="font-semibold">Best configuration:</span> {run.results.best.chunking} chunking + {run.results.best.retrieval} retrieval
                      <span className="text-slate-500"> (composite score {run.results.best.score.toFixed(3)})</span></div>
                  </div>
                )}
                <div className="grid gap-6 lg:grid-cols-2">
                  <div className="card p-5">
                    <h2 className="text-sm font-semibold">Retrieval quality</h2>
                    <div className="mt-4 h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={configs.map((c) => ({ name: label(c), precision: c.metrics.precision, recall: c.metrics.recall, mrr: c.metrics.mrr }))} margin={{ left: -20 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#94a3b833" />
                          <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={60} stroke="#94a3b8" />
                          <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} stroke="#94a3b8" />
                          <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                          <Legend wrapperStyle={{ fontSize: 12 }} />
                          <Bar dataKey="precision" name="Precision@k" fill="#6366f1" radius={[3, 3, 0, 0]} />
                          <Bar dataKey="recall" name="Recall@k" fill="#10b981" radius={[3, 3, 0, 0]} />
                          <Bar dataKey="mrr" name="MRR" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                  <div className="card p-5">
                    <h2 className="text-sm font-semibold">Overall profile <span className="font-normal text-slate-500">(hallucination shown as 1 − rate)</span></h2>
                    <div className="mt-4 h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <RadarChart data={radarData} outerRadius="70%">
                          <PolarGrid stroke="#94a3b855" />
                          <PolarAngleAxis dataKey="metric" tick={{ fontSize: 10 }} />
                          <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
                          {configs.map((c, i) => (
                            <Radar key={label(c)} name={label(c)} dataKey={label(c)} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.08} />
                          ))}
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                        </RadarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
                <div className="card mt-6 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-slate-500 uppercase">
                      <tr>
                        <th className="px-4 py-3 font-medium">Configuration</th>
                        <th className="px-3 py-3 font-medium">Chunks</th>
                        {METRICS.map((m) => <th key={m.key} className="px-3 py-3 font-medium whitespace-nowrap">{m.label}</th>)}
                        <th className="px-3 py-3 font-medium whitespace-nowrap">Latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {configs.map((c) => (
                        <tr key={label(c)} className={run.results.best?.chunking === c.chunking && run.results.best?.retrieval === c.retrieval ? "bg-emerald-50/60 dark:bg-emerald-950/20" : ""}>
                          <td className="px-4 py-2.5 font-medium whitespace-nowrap">{label(c)}</td>
                          <td className="px-3 py-2.5 tabular-nums">{c.chunks}</td>
                          {METRICS.map((m) => <td key={m.key} className="px-3 py-2.5 tabular-nums">{fmt(c.metrics[m.key] as number | null)}</td>)}
                          <td className="px-3 py-2.5 tabular-nums whitespace-nowrap">{c.metrics.latency_ms != null ? `${Math.round(c.metrics.latency_ms)} ms` : `${Math.round(c.metrics.retrieval_latency_ms ?? 0)} ms`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
