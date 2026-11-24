"use client";

import { AlertTriangle, CheckCircle2, Database, FileText, FolderKanban, HardDrive, Layers, MessageSquare, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { motion } from "motion/react";
import { FadeIn, Stagger, StaggerItem } from "@/components/motion";
import { ErrorBanner, FileTypeIcon, PageHeader, Skeleton, StatCard, StatusBadge } from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { api, formatBytes, timeAgo } from "@/services/api";

const PIE = ["#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#f43f5e", "#64748b"];

export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.stats());

  // keep counters live while documents are being processed
  useEffect(() => {
    if (!data?.pending_documents) return;
    const t = setInterval(() => reload(true), 4000);
    return () => clearInterval(t);
  }, [data?.pending_documents, reload]);

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <PageHeader eyebrow="Overview"
        title={<>Welcome back{user?.full_name ? <>, <span className="text-gradient">{user.full_name.split(" ")[0]}</span></> : ""}</>}
        description="Overview of your knowledge base and processing activity."
        actions={<>
          <Link href="/documents" className="btn-secondary"><FileText className="h-4 w-4" />Upload documents</Link>
          <Link href="/chat" className="btn-primary"><MessageSquare className="h-4 w-4" />Ask a question</Link>
        </>} />
      {error && <ErrorBanner message={error} onRetry={() => reload()} />}
      {loading && !data ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Loading">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[118px] rounded-2xl" />)}
        </div>
      ) : data && (
        <>
          <Stagger className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StaggerItem className="h-full"><StatCard label="Documents" value={data.total_documents} icon={<FileText className="h-4 w-4" />}
              hint={`${data.pending_documents} in progress`} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Processed" value={data.processed_documents} tone="green" icon={<CheckCircle2 className="h-4 w-4" />}
              hint={data.total_documents ? `${Math.round((100 * data.processed_documents) / data.total_documents)}% success` : undefined} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Failed" value={data.failed_documents} tone="red" icon={<AlertTriangle className="h-4 w-4" />} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Indexed chunks" value={data.total_chunks} tone="amber" icon={<Layers className="h-4 w-4" />} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Collections" value={data.total_collections} tone="slate" icon={<FolderKanban className="h-4 w-4" />} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Storage" value={data.storage_bytes} format={formatBytes} tone="slate" icon={<HardDrive className="h-4 w-4" />} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Conversations" value={data.conversations} icon={<MessageSquare className="h-4 w-4" />} /></StaggerItem>
            <StaggerItem className="h-full"><StatCard label="Helpful answers" value={data.feedback.positive} tone="green" icon={<ThumbsUp className="h-4 w-4" />}
              hint={`${data.feedback.negative} marked unhelpful`} /></StaggerItem>
          </Stagger>

          <FadeIn delay={0.25} className="mt-6 grid gap-6 lg:grid-cols-3">
            <div className="card p-5 lg:col-span-2">
              <h2 className="text-sm font-semibold">Processing activity</h2>
              <p className="text-xs text-slate-500">Uploads and outcomes over the last 14 days</p>
              <div className="mt-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.activity} margin={{ left: -20, right: 8 }}>
                    <defs>
                      <linearGradient id="gUp" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} /><stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#94a3b833" />
                    <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 11 }} stroke="#94a3b8" />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="#94a3b8" />
                    <Tooltip contentStyle={{ borderRadius: 12, fontSize: 12, border: "1px solid rgb(148 163 184 / 0.25)", boxShadow: "0 12px 32px -12px rgb(15 23 42 / 0.25)" }} />
                    <Area type="monotone" dataKey="uploaded" name="Uploaded" stroke="#6366f1" fill="url(#gUp)" strokeWidth={2.5} animationDuration={1200} />
                    <Area type="monotone" dataKey="completed" name="Processed" stroke="#10b981" fill="transparent" strokeWidth={2} animationDuration={1200} />
                    <Area type="monotone" dataKey="failed" name="Failed" stroke="#ef4444" fill="transparent" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card p-5">
              <h2 className="text-sm font-semibold">Document types</h2>
              <p className="text-xs text-slate-500">Share of uploaded formats</p>
              {data.file_types.length === 0 ? (
                <p className="py-16 text-center text-sm text-slate-500">No documents yet</p>
              ) : (
                <>
                  <div className="h-44">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={data.file_types} dataKey="count" nameKey="file_type" innerRadius={48} outerRadius={72} paddingAngle={3} cornerRadius={6} stroke="none" animationDuration={1000}>
                          {data.file_types.map((_, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
                        </Pie>
                        <Tooltip contentStyle={{ borderRadius: 12, fontSize: 12, border: "1px solid rgb(148 163 184 / 0.25)", boxShadow: "0 12px 32px -12px rgb(15 23 42 / 0.25)" }} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                    {data.file_types.map((f, i) => (
                      <span key={f.file_type} className="flex items-center gap-1.5 text-xs">
                        <span className="h-2 w-2 rounded-full" style={{ background: PIE[i % PIE.length] }} />
                        {f.file_type.toUpperCase()} · {f.count}
                      </span>
                    ))}
                  </div>
                </>
              )}
              <div className="mt-5 border-t border-slate-200 pt-4 dark:border-slate-800">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold"><Database className="h-3.5 w-3.5" />Embedding status</h3>
                <ul className="mt-2 space-y-1.5">
                  {data.embedding_status.map((e) => (
                    <li key={e.model} className="flex justify-between text-xs">
                      <span className="truncate text-slate-600 dark:text-slate-400">{e.model}</span>
                      <span className="font-medium tabular-nums">{e.count}</span>
                    </li>
                  ))}
                  {data.embedding_status.length === 0 && <li className="text-xs text-slate-500">Nothing embedded yet</li>}
                </ul>
              </div>
            </div>
          </FadeIn>

          <div className="card mt-6">
            <div className="flex items-center justify-between px-5 py-4">
              <h2 className="text-sm font-semibold">Recent uploads</h2>
              <Link href="/documents" className="text-xs font-medium text-brand-600">View all</Link>
            </div>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.recent_documents.length === 0 && (
                <li className="px-5 pb-6 text-sm text-slate-500">No documents yet. Upload some to get started.</li>
              )}
              {data.recent_documents.map((d, i) => (
                <motion.li key={d.id} className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-slate-50/80 dark:hover:bg-white/[0.03]"
                  initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.3 + i * 0.05 }}>
                  <FileTypeIcon type={d.file_type} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{d.filename}</div>
                    <div className="text-xs text-slate-500">
                      {formatBytes(d.size_bytes)} · {d.chunk_count} chunks · {timeAgo(d.created_at)}
                    </div>
                  </div>
                  <StatusBadge status={d.status} />
                </motion.li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
