"use client";

import { Eye, FileText, Info, RefreshCw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { UploadDropzone } from "@/components/UploadDropzone";
import {
  ConfirmDialog, EmptyState, ErrorBanner, FileTypeIcon, Modal, PageHeader, Spinner, StatusBadge, Toast,
} from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { api, formatBytes, formatDate } from "@/services/api";
import type { DocumentDetail, DocumentItem } from "@/types";

const PAGE_SIZE = 25;

export default function DocumentsPage() {
  const collections = useAsync(() => api.collections());
  const [collectionId, setCollectionId] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [fileType, setFileType] = useState("");
  const [offset, setOffset] = useState(0);
  const [toast, setToast] = useState<{ msg: string; tone: "info" | "error" | "success" } | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [details, setDetails] = useState<DocumentDetail | null>(null);
  const [toDelete, setToDelete] = useState<DocumentItem | null>(null);
  const [toReprocess, setToReprocess] = useState<DocumentItem | null>(null);
  const [busy, setBusy] = useState(false);

  const docs = useAsync(
    () => api.documents({ collection_id: collectionId || undefined, search: query || undefined,
      status: status || undefined, file_type: fileType || undefined, offset, limit: PAGE_SIZE }),
    [collectionId, query, status, fileType, offset],
  );

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const inFlight = docs.data?.items.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(() => docs.reload(true), 2500);
    return () => clearInterval(t);
  }, [inFlight, docs.reload]);

  const colName = useCallback(
    (id: string) => collections.data?.find((c) => c.id === id)?.name ?? "—", [collections.data]);

  const showDetails = async (d: DocumentItem) => {
    try {
      setDetails(await api.document(d.id));
    } catch (e) {
      setToast({ msg: (e as Error).message, tone: "error" });
    }
  };

  const doDelete = async () => {
    if (!toDelete) return;
    setBusy(true);
    try {
      await api.deleteDocument(toDelete.id);
      setToast({ msg: `Deleted ${toDelete.filename} and its vectors`, tone: "success" });
      setToDelete(null);
      void docs.reload(true);
    } catch (e) {
      setToast({ msg: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <PageHeader title="Documents" description="Upload, inspect, re-process and remove documents in your knowledge base." />
      {collections.data && (
        <UploadDropzone collections={collections.data} onUploaded={(msg, err) => {
          setToast({ msg, tone: err ? "error" : "success" });
          void docs.reload(true);
        }} />
      )}

      <div className="card mt-6">
        <div className="flex flex-col gap-3 border-b border-slate-200 p-4 md:flex-row md:items-center dark:border-slate-800">
          <div className="relative flex-1">
            <Search className="absolute top-2.5 left-3 h-4 w-4 text-slate-400" />
            <input className="input pl-9" placeholder="Search by file name…" value={search}
              onChange={(e) => setSearch(e.target.value)} aria-label="Search documents" />
          </div>
          <select className="input md:w-48" value={collectionId} aria-label="Collection"
            onChange={(e) => { setCollectionId(e.target.value); setOffset(0); }}>
            <option value="">All collections</option>
            {collections.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input md:w-36" value={status} aria-label="Status"
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">Any status</option>
            <option value="completed">Ready</option>
            <option value="processing">Processing</option>
            <option value="pending">Queued</option>
            <option value="failed">Failed</option>
          </select>
          <select className="input md:w-32" value={fileType} aria-label="File type"
            onChange={(e) => { setFileType(e.target.value); setOffset(0); }}>
            <option value="">Any type</option>
            {["pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"].map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
          </select>
        </div>
        {docs.error && <div className="p-4"><ErrorBanner message={docs.error} onRetry={() => docs.reload()} /></div>}
        {docs.loading && !docs.data ? (
          <div className="flex justify-center py-16"><Spinner className="h-6 w-6" /></div>
        ) : docs.data && docs.data.items.length === 0 ? (
          <EmptyState icon={<FileText className="h-5 w-5" />} title="No documents found"
            description="Upload documents above, or adjust the filters." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">Document</th>
                  <th className="hidden px-4 py-3 font-medium md:table-cell">Collection</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="hidden px-4 py-3 font-medium lg:table-cell">Chunks</th>
                  <th className="hidden px-4 py-3 font-medium lg:table-cell">Uploaded</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {docs.data?.items.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <FileTypeIcon type={d.file_type} />
                        <div className="min-w-0">
                          <div className="max-w-xs truncate font-medium">{d.filename}</div>
                          <div className="text-xs text-slate-500">
                            {formatBytes(d.size_bytes)}{d.page_count ? ` · ${d.page_count} pages` : ""}
                            {d.chunking_strategy ? ` · ${d.chunking_strategy}` : ""}
                          </div>
                          {d.status === "failed" && d.error_message && (
                            <div className="mt-0.5 max-w-sm truncate text-xs text-red-600" title={d.error_message}>{d.error_message}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 md:table-cell dark:text-slate-400">{colName(d.collection_id)}</td>
                    <td className="px-4 py-3"><StatusBadge status={d.status} /></td>
                    <td className="hidden px-4 py-3 tabular-nums lg:table-cell">{d.chunk_count}</td>
                    <td className="hidden px-4 py-3 text-slate-600 lg:table-cell dark:text-slate-400">{formatDate(d.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <button className="btn-ghost p-1.5" title="Preview" aria-label={`Preview ${d.filename}`}
                          disabled={d.status !== "completed"}
                          onClick={() => setViewer({ documentId: d.id, documentName: d.filename, fileType: d.file_type, page: d.page_count ? 1 : null })}>
                          <Eye className="h-4 w-4" />
                        </button>
                        <button className="btn-ghost p-1.5" title="Metadata & logs" aria-label={`Details for ${d.filename}`} onClick={() => showDetails(d)}>
                          <Info className="h-4 w-4" />
                        </button>
                        <button className="btn-ghost p-1.5" title="Re-process" aria-label={`Re-process ${d.filename}`}
                          disabled={d.status === "processing"} onClick={() => setToReprocess(d)}>
                          <RefreshCw className="h-4 w-4" />
                        </button>
                        <button className="btn-ghost p-1.5 text-red-600" title="Delete" aria-label={`Delete ${d.filename}`}
                          disabled={d.status === "processing"} onClick={() => setToDelete(d)}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {docs.data && docs.data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
            <span className="text-slate-500">{offset + 1}–{Math.min(offset + PAGE_SIZE, docs.data.total)} of {docs.data.total}</span>
            <div className="flex gap-2">
              <button className="btn-secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>Previous</button>
              <button className="btn-secondary" disabled={offset + PAGE_SIZE >= docs.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
            </div>
          </div>
        )}
      </div>

      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
      <DetailsModal doc={details} onClose={() => setDetails(null)} collectionName={details ? colName(details.collection_id) : ""} />
      <ReprocessModal doc={toReprocess} onClose={() => setToReprocess(null)} onDone={(msg, err) => {
        setToast({ msg, tone: err ? "error" : "success" });
        setToReprocess(null);
        void docs.reload(true);
      }} />
      <ConfirmDialog open={!!toDelete} title="Delete document"
        message={`Delete "${toDelete?.filename}"? Its chunks and vectors will be removed from the index. This cannot be undone.`}
        onCancel={() => setToDelete(null)} onConfirm={doDelete} busy={busy} />
      {toast && <Toast message={toast.msg} tone={toast.tone} onClose={() => setToast(null)} />}
    </div>
  );
}

function DetailsModal({ doc, onClose, collectionName }: { doc: DocumentDetail | null; onClose: () => void; collectionName: string }) {
  if (!doc) return null;
  const rows: [string, string | number][] = [
    ["Collection", collectionName], ["Type", doc.mime_type], ["Size", formatBytes(doc.size_bytes)],
    ["Pages", doc.page_count || "n/a (not paginated)"], ["Chunks", doc.chunk_count],
    ["Chunking", doc.chunking_strategy ?? "—"], ["Embedding model", doc.embedding_model ?? "—"],
    ["Vector store", doc.vector_store ?? "—"], ["Uploaded", formatDate(doc.created_at)],
    ["Processed", formatDate(doc.processed_at)],
  ];
  Object.entries(doc.meta || {}).forEach(([k, v]) => rows.push([k.replace(/_/g, " "), String(v)]));
  return (
    <Modal open onClose={onClose} title={doc.filename} size="lg">
      <div className="mb-4 flex items-center gap-2"><StatusBadge status={doc.status} />
        {doc.error_message && <span className="text-sm text-red-600">{doc.error_message}</span>}</div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-slate-100 py-1.5 dark:border-slate-800">
            <dt className="text-slate-500 capitalize">{k}</dt><dd className="truncate text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-6 mb-2 text-sm font-semibold">Processing log</h3>
      <ol className="space-y-1.5 font-mono text-xs">
        {doc.logs.map((l) => (
          <li key={l.id} className={`flex gap-3 rounded px-2 py-1 ${l.level === "ERROR" ? "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" : l.level === "WARNING" ? "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300" : "bg-slate-50 dark:bg-slate-800/60"}`}>
            <span className="w-20 shrink-0 font-semibold">{l.stage}</span>
            <span className="flex-1">{l.message}</span>
            {l.duration_ms != null && <span className="shrink-0 text-slate-500">{Math.round(l.duration_ms)} ms</span>}
          </li>
        ))}
      </ol>
    </Modal>
  );
}

function ReprocessModal({ doc, onClose, onDone }: { doc: DocumentItem | null; onClose: () => void; onDone: (msg: string, err?: boolean) => void }) {
  const [strategy, setStrategy] = useState("structure");
  const [size, setSize] = useState(1000);
  const [overlap, setOverlap] = useState(150);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!doc) return;
    setBusy(true);
    try {
      await api.reprocess(doc.id, { chunking_strategy: strategy, chunk_size: size, chunk_overlap: overlap });
      onDone(`Re-processing ${doc.filename} with ${strategy} chunking`);
    } catch (e) {
      onDone((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={!!doc} onClose={onClose} title={`Re-process ${doc?.filename ?? ""}`}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={submit} disabled={busy}>{busy && <Spinner />}Re-process</button></>}>
      <p className="mb-4 text-sm text-slate-500">
        Re-chunks and re-indexes the document. Unchanged chunks reuse cached embeddings; stale vectors are removed.
      </p>
      <div className="space-y-4">
        <div>
          <label className="label" htmlFor="rp-s">Chunking strategy</label>
          <select id="rp-s" className="input" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="structure">Structure-aware (headings, tables)</option>
            <option value="semantic">Semantic (embedding boundaries)</option>
            <option value="recursive">Recursive character</option>
            <option value="token">Token-based</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="rp-size">Chunk size (chars)</label>
            <input id="rp-size" type="number" min={100} max={8000} className="input" value={size} onChange={(e) => setSize(+e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="rp-ov">Overlap (chars)</label>
            <input id="rp-ov" type="number" min={0} max={size - 1} className="input" value={overlap} onChange={(e) => setOverlap(+e.target.value)} />
          </div>
        </div>
      </div>
    </Modal>
  );
}
