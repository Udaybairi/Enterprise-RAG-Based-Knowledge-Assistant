"use client";

import clsx from "clsx";
import { UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { api } from "@/services/api";
import type { Collection } from "@/types";
import { Spinner } from "./ui";

const ACCEPT = ".pdf,.docx,.txt,.csv,.xlsx,.pptx,.md,.markdown";
const MAX_MB = 50;

export function UploadDropzone({
  collections, defaultCollectionId, onUploaded,
}: { collections: Collection[]; defaultCollectionId?: string; onUploaded: (msg: string, error?: boolean) => void }) {
  const writable = collections.filter((c) => c.can_write);
  const [collectionId, setCollectionId] = useState(defaultCollectionId || writable[0]?.id || "");
  const [strategy, setStrategy] = useState("");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const upload = async (list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    const allowed = ACCEPT.split(",");
    const invalid = files.filter(
      (f) => !allowed.includes(`.${f.name.split(".").pop()?.toLowerCase()}`) || f.size > MAX_MB * 1024 * 1024,
    );
    const ok = files.filter((f) => !invalid.includes(f));
    if (!ok.length) {
      onUploaded(`Unsupported file type or larger than ${MAX_MB} MB: ${invalid.map((f) => f.name).join(", ")}`, true);
      return;
    }
    setBusy(true);
    try {
      const res = await api.upload(ok, collectionId || undefined, strategy || undefined);
      const rejected = [...invalid.map((f) => `${f.name} (unsupported or too large)`),
        ...res.rejected.map((r) => `${r.filename}: ${r.reason}`)];
      const msg = `${res.documents.length} document(s) queued for processing.` +
        (rejected.length ? ` Rejected: ${rejected.join("; ")}` : "");
      onUploaded(msg, res.documents.length === 0);
    } catch (e) {
      onUploaded((e as Error).message, true);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    void upload(e.dataTransfer.files);
  };

  return (
    <div className="card p-4">
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="up-col">Collection</label>
          <select id="up-col" className="input" value={collectionId} onChange={(e) => setCollectionId(e.target.value)}>
            {writable.length === 0 && <option value="">My Documents (default)</option>}
            {writable.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="up-strat">Chunking strategy</label>
          <select id="up-strat" className="input" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="">Default (server setting)</option>
            <option value="structure">Structure-aware</option>
            <option value="semantic">Semantic</option>
            <option value="recursive">Recursive character</option>
            <option value="token">Token-based</option>
          </select>
        </div>
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        role="button"
        tabIndex={0}
        className={clsx(
          "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition",
          drag ? "border-brand-500 bg-brand-50 dark:bg-brand-500/10" : "border-slate-300 hover:border-brand-400 dark:border-slate-700",
        )}>
        {busy ? <Spinner className="h-8 w-8 text-brand-600" /> : <UploadCloud className="h-8 w-8 text-brand-600" />}
        <p className="mt-3 text-sm font-medium">{busy ? "Uploading…" : "Drop files here or click to browse"}</p>
        <p className="mt-1 text-xs text-slate-500">PDF, DOCX, PPTX, XLSX, CSV, TXT, Markdown · up to {MAX_MB} MB each · max 20 files</p>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden"
          onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>
    </div>
  );
}
