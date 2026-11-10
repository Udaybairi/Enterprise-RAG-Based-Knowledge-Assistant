"use client";

import { FolderKanban, Globe, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ConfirmDialog, EmptyState, ErrorBanner, Modal, PageHeader, Spinner, Toast } from "@/components/ui";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { api, formatBytes, formatDate } from "@/services/api";
import type { Collection } from "@/types";

export default function CollectionsPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.collections());
  const [editing, setEditing] = useState<Collection | "new" | null>(null);
  const [toDelete, setToDelete] = useState<Collection | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; tone: "error" | "success" } | null>(null);

  const remove = async () => {
    if (!toDelete) return;
    setBusy(true);
    try {
      await api.deleteCollection(toDelete.id);
      setToast({ msg: `Collection "${toDelete.name}" deleted with all its documents and vectors`, tone: "success" });
      setToDelete(null);
      void reload(true);
    } catch (e) {
      setToast({ msg: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <PageHeader title="Knowledge collections"
        description="Group documents into collections. Each collection has its own isolated vector index."
        actions={<button className="btn-primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />New collection</button>} />
      {error && <ErrorBanner message={error} onRetry={() => reload()} />}
      {loading && !data ? <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div> :
        data?.length === 0 ? (
          <div className="card"><EmptyState icon={<FolderKanban className="h-5 w-5" />} title="No collections yet"
            action={<button className="btn-primary" onClick={() => setEditing("new")}>Create collection</button>} /></div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data?.map((c) => (
              <div key={c.id} className="card flex flex-col p-5">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className="rounded-lg bg-brand-50 p-2 text-brand-600 dark:bg-brand-500/10 dark:text-brand-400"><FolderKanban className="h-4 w-4" /></div>
                    <div>
                      <h3 className="font-semibold">{c.name}</h3>
                      <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                        {c.visibility === "organization" ? <><Globe className="h-3 w-3" />Organization-wide</> : <><Lock className="h-3 w-3" />Private</>}
                        {c.owner_id !== user?.id && " · shared with you"}
                      </span>
                    </div>
                  </div>
                  {c.can_write && (
                    <div className="flex">
                      <button className="btn-ghost p-1.5" onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`}><Pencil className="h-3.5 w-3.5" /></button>
                      <button className="btn-ghost p-1.5 text-red-600" onClick={() => setToDelete(c)} aria-label={`Delete ${c.name}`}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  )}
                </div>
                <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-sm text-slate-600 dark:text-slate-400">{c.description || "No description"}</p>
                <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-slate-100 pt-4 text-center dark:border-slate-800">
                  <div><dt className="text-[11px] text-slate-500">Documents</dt><dd className="font-semibold tabular-nums">{c.document_count}</dd></div>
                  <div><dt className="text-[11px] text-slate-500">Chunks</dt><dd className="font-semibold tabular-nums">{c.chunk_count}</dd></div>
                  <div><dt className="text-[11px] text-slate-500">Size</dt><dd className="font-semibold tabular-nums">{formatBytes(c.size_bytes)}</dd></div>
                </dl>
                <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
                  <span>Created {formatDate(c.created_at)}</span>
                  <Link href="/chat" className="font-medium text-brand-600">Ask →</Link>
                </div>
              </div>
            ))}
          </div>
        )}
      {editing && <CollectionForm initial={editing === "new" ? null : editing} isAdmin={user?.role === "admin"}
        onClose={() => setEditing(null)} onSaved={(msg) => { setEditing(null); setToast({ msg, tone: "success" }); void reload(true); }} />}
      <ConfirmDialog open={!!toDelete} title="Delete collection" busy={busy}
        message={`Delete "${toDelete?.name}" including ${toDelete?.document_count ?? 0} document(s) and the vector index? This cannot be undone.`}
        onCancel={() => setToDelete(null)} onConfirm={remove} />
      {toast && <Toast message={toast.msg} tone={toast.tone} onClose={() => setToast(null)} />}
    </div>
  );
}

function CollectionForm({ initial, isAdmin, onClose, onSaved }: { initial: Collection | null; isAdmin: boolean; onClose: () => void; onSaved: (msg: string) => void }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [visibility, setVisibility] = useState(initial?.visibility ?? "private");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (initial) await api.updateCollection(initial.id, { name, description, visibility });
      else await api.createCollection({ name, description, visibility });
      onSaved(initial ? "Collection updated" : "Collection created");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={initial ? "Edit collection" : "New collection"}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" onClick={save} disabled={busy || !name.trim()}>{busy && <Spinner />}Save</button></>}>
      {error && <ErrorBanner message={error} />}
      <div className="space-y-4">
        <div><label className="label" htmlFor="c-name">Name</label>
          <input id="c-name" className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></div>
        <div><label className="label" htmlFor="c-desc">Description</label>
          <textarea id="c-desc" className="input" rows={3} value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} /></div>
        <div><label className="label" htmlFor="c-vis">Visibility</label>
          <select id="c-vis" className="input" value={visibility} onChange={(e) => setVisibility(e.target.value as Collection["visibility"])}>
            <option value="private">Private: only you (and administrators)</option>
            <option value="organization" disabled={!isAdmin}>Organization-wide: everyone can read{!isAdmin ? " (admins only)" : ""}</option>
          </select></div>
      </div>
    </Modal>
  );
}
