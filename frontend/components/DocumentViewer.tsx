"use client";

import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type { ChunkPreview } from "@/types";
import { Modal, Spinner } from "./ui";

export interface ViewerTarget {
  documentId: string;
  documentName: string;
  fileType?: string | null;
  page?: number | null;
  snippet?: string;
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Highlight the cited snippet (or its sentences) inside chunk text. */
function Highlighted({ text, snippet }: { text: string; snippet?: string }) {
  const parts = useMemo(() => {
    if (!snippet) return [text];
    const needles = snippet
      .replace(/…$/, "")
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 12);
    if (!needles.length) return [text];
    const re = new RegExp(`(${needles.map(escapeRegExp).join("|")})`, "g");
    return text.split(re);
  }, [text, snippet]);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <mark key={i} className="hl">{p}</mark> : <span key={i}>{p}</span>))}
    </>
  );
}

const NO_CHUNKS: ChunkPreview[] = [];

export function DocumentViewer({ target, onClose }: { target: ViewerTarget | null; onClose: () => void }) {
  // State is keyed by the target / page it belongs to, so switching citations never shows (or is
  // overwritten by) data from the previously opened document or page.
  const [pageSel, setPageSel] = useState<{ target: ViewerTarget | null; page: number | null } | null>(null);
  const page = pageSel && pageSel.target === target ? pageSel.page : target?.page ?? null;
  const setPage = (fn: (p: number | null) => number | null) => setPageSel({ target, page: fn(page) });

  const [file, setFile] = useState<{ docId: string; url: string } | null>(null);
  const fileUrl = file && file.docId === target?.documentId ? file.url : null;

  const previewKey = target ? `${target.documentId}:${page ?? "all"}` : null;
  const [preview, setPreview] = useState<{ key: string; docId: string; chunks: ChunkPreview[]; pageCount: number;
    error: string | null } | null>(null);
  const loading = !!previewKey && preview?.key !== previewKey;
  const chunks = preview?.key === previewKey ? preview.chunks : NO_CHUNKS;
  const pageCount = preview && preview.docId === target?.documentId ? preview.pageCount : 0;
  const [actionError, setActionError] = useState<string | null>(null);
  const error = (preview?.key === previewKey ? preview?.error : null) ?? actionError;
  const isPdf = target?.fileType === "pdf" || target?.documentName.toLowerCase().endsWith(".pdf");

  useEffect(() => {
    if (!target || !isPdf) return;
    let url: string | null = null;
    let cancelled = false;
    api.fileUrl(target.documentId)
      .then((r) => {
        url = r.url;
        if (!cancelled) setFile({ docId: target.documentId, url: r.url });
      })
      .catch((e) => !cancelled && setActionError(e.message));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [target, isPdf]);

  useEffect(() => {
    if (!target || !previewKey) return;
    let cancelled = false;
    api.preview(target.documentId, page)
      .then((r) => !cancelled && setPreview({ key: previewKey, docId: target.documentId, chunks: r.chunks,
        pageCount: r.page_count, error: null }))
      .catch((e) => !cancelled && setPreview({ key: previewKey, docId: target.documentId, chunks: [],
        pageCount: 0, error: e.message }));
    return () => {
      cancelled = true;
    };
  }, [target, page, previewKey]);

  // Scroll the first highlighted passage into view
  useEffect(() => {
    if (!loading) document.querySelector("#viewer-text mark")?.scrollIntoView({ block: "center" });
  }, [loading, chunks]);

  const openOriginal = async () => {
    if (!target) return;
    try {
      const { url } = await api.fileUrl(target.documentId);
      window.open(isPdf && page ? `${url}#page=${page}` : url, "_blank", "noopener");
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  return (
    <Modal open={!!target} onClose={onClose} size="xl"
      title={<span>{target?.documentName}{page ? <span className="ml-2 text-sm font-normal text-slate-500">· page {page}</span> : null}</span>}>
      {target && (
        <div className={isPdf ? "grid gap-4 lg:grid-cols-2" : ""}>
          {isPdf && (
            <div className="h-[65vh] overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
              {fileUrl ? (
                <iframe key={`${fileUrl}-${page}`} title="Document" className="h-full w-full bg-white"
                  src={`${fileUrl}#page=${page ?? 1}&view=FitH`} />
              ) : (
                <div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6" /></div>
              )}
            </div>
          )}
          <div className="flex h-[65vh] flex-col">
            <div className="mb-3 flex items-center justify-between gap-2">
              <span className="text-xs font-medium tracking-wide text-slate-500 uppercase">
                Extracted text {target.snippet ? "· cited passage highlighted" : ""}
              </span>
              <div className="flex items-center gap-1">
                {pageCount > 0 && (
                  <>
                    <button className="btn-ghost p-1.5" disabled={!page || page <= 1} aria-label="Previous page"
                      onClick={() => setPage((p) => Math.max(1, (p ?? 1) - 1))}><ChevronLeft className="h-4 w-4" /></button>
                    <span className="text-xs tabular-nums">{page ?? "all"} / {pageCount}</span>
                    <button className="btn-ghost p-1.5" disabled={!!page && page >= pageCount} aria-label="Next page"
                      onClick={() => setPage((p) => Math.min(pageCount, (p ?? 0) + 1))}><ChevronRight className="h-4 w-4" /></button>
                  </>
                )}
                <button className="btn-secondary px-2.5 py-1.5 text-xs" onClick={openOriginal}>
                  <ExternalLink className="h-3.5 w-3.5" /> Original
                </button>
              </div>
            </div>
            {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
            <div id="viewer-text" className="flex-1 space-y-3 overflow-y-auto pr-1">
              {loading ? <div className="flex justify-center py-10"><Spinner className="h-5 w-5" /></div> :
                chunks.length === 0 ? <p className="text-sm text-slate-500">No extracted text for this page.</p> :
                chunks.map((c) => (
                  <div key={c.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                    <div className="mb-1.5 flex flex-wrap gap-x-3 text-[11px] text-slate-500">
                      <span>Chunk #{c.chunk_index + 1}</span>
                      {c.page_number && <span>Page {c.page_number}</span>}
                      {c.section && <span className="truncate">§ {c.section}</span>}
                      <span>{c.token_count} tokens</span>
                    </div>
                    <p className="text-sm leading-relaxed whitespace-pre-wrap"><Highlighted text={c.text} snippet={target.snippet} /></p>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
