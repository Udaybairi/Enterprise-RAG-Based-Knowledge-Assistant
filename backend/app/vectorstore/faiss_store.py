"""FAISS-backed vector store (local development / single node).

Uses ``IndexIDMap2(IndexFlatIP)`` over L2-normalised vectors: exact cosine
search with support for deletion and vector reconstruction (needed for MMR).
Each namespace persists as ``<ns>.faiss`` + ``<ns>.json`` (id map + metadata),
written atomically.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.core.logging import get_logger
from app.vectorstore.base import VectorHit, VectorStore, Where, matches, sanitize_metadata

log = get_logger(__name__)
_NS_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class _Namespace:
    def __init__(self, dim: int):
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        self.str_to_int: dict[str, int] = {}
        self.int_to_str: dict[int, str] = {}
        self.meta: dict[str, dict[str, Any]] = {}
        self.next_id = 1
        self.lock = threading.RLock()


class FaissVectorStore(VectorStore):
    name = "faiss"

    def __init__(self, root: Path, dimension: int):
        self.root = Path(root) / "faiss"
        self.root.mkdir(parents=True, exist_ok=True)
        self.dim = dimension
        self._ns: dict[str, _Namespace] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- persistence
    def _paths(self, namespace: str) -> tuple[Path, Path]:
        if not _NS_RE.match(namespace):
            raise ValueError(f"invalid namespace {namespace!r}")
        return self.root / f"{namespace}.faiss", self.root / f"{namespace}.json"

    def _load(self, namespace: str) -> _Namespace:
        with self._lock:
            if namespace in self._ns:
                return self._ns[namespace]
            ns = _Namespace(self.dim)
            idx_path, meta_path = self._paths(namespace)
            if idx_path.exists() and meta_path.exists():
                ns.index = faiss.read_index(str(idx_path))
                data = json.loads(meta_path.read_text())
                ns.str_to_int = {k: int(v) for k, v in data["ids"].items()}
                ns.int_to_str = {v: k for k, v in ns.str_to_int.items()}
                ns.meta = data["meta"]
                ns.next_id = int(data["next_id"])
                if ns.index.d != self.dim:
                    raise ValueError(
                        f"FAISS index {namespace} has dimension {ns.index.d}, expected {self.dim}. "
                        "Re-process documents after changing the embedding model."
                    )
            self._ns[namespace] = ns
            return ns

    def _save(self, namespace: str, ns: _Namespace) -> None:
        idx_path, meta_path = self._paths(namespace)
        tmp_idx, tmp_meta = idx_path.with_suffix(".faiss.tmp"), meta_path.with_suffix(".json.tmp")
        faiss.write_index(ns.index, str(tmp_idx))
        tmp_meta.write_text(json.dumps({"ids": ns.str_to_int, "meta": ns.meta, "next_id": ns.next_id}))
        os.replace(tmp_idx, idx_path)
        os.replace(tmp_meta, meta_path)

    # ---------------------------------------------------------------- operations
    def upsert(self, namespace, ids, vectors, metadatas) -> None:
        if not ids:
            return
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.shape != (len(ids), self.dim):
            raise ValueError(f"vectors shape {vectors.shape} != ({len(ids)}, {self.dim})")
        ns = self._load(namespace)
        with ns.lock:
            existing = [ns.str_to_int[i] for i in ids if i in ns.str_to_int]
            if existing:
                ns.index.remove_ids(np.array(existing, dtype=np.int64))
            int_ids = []
            for sid, meta in zip(ids, metadatas):
                iid = ns.str_to_int.get(sid)
                if iid is None:
                    iid = ns.next_id
                    ns.next_id += 1
                    ns.str_to_int[sid] = iid
                    ns.int_to_str[iid] = sid
                int_ids.append(iid)
                ns.meta[sid] = sanitize_metadata(meta)
            ns.index.add_with_ids(vectors, np.array(int_ids, dtype=np.int64))
            self._save(namespace, ns)

    def delete(self, namespace, ids) -> None:
        ns = self._load(namespace)
        with ns.lock:
            int_ids = [ns.str_to_int.pop(i) for i in ids if i in ns.str_to_int]
            for i in ids:
                ns.meta.pop(i, None)
            for iid in int_ids:
                ns.int_to_str.pop(iid, None)
            if int_ids:
                ns.index.remove_ids(np.array(int_ids, dtype=np.int64))
            self._save(namespace, ns)

    def delete_namespace(self, namespace) -> None:
        with self._lock:
            self._ns.pop(namespace, None)
            for p in self._paths(namespace):
                p.unlink(missing_ok=True)

    def search(self, namespace, query, k, where=None, include_vectors=False) -> list[VectorHit]:
        ns = self._load(namespace)
        with ns.lock:
            total = ns.index.ntotal
            if total == 0 or k <= 0:
                return []
            q = np.ascontiguousarray(query, dtype=np.float32).reshape(1, -1)
            # Over-fetch when filtering, expanding until we have enough matches.
            fetch = min(total, k if not where else max(k * 4, 50))
            while True:
                scores, iids = ns.index.search(q, fetch)
                hits: list[VectorHit] = []
                for score, iid in zip(scores[0], iids[0]):
                    if iid == -1:
                        continue
                    sid = ns.int_to_str.get(int(iid))
                    if sid is None:
                        continue
                    meta = ns.meta.get(sid, {})
                    if not matches(meta, where):
                        continue
                    vec = ns.index.reconstruct(int(iid)) if include_vectors else None
                    hits.append(VectorHit(sid, float(score), dict(meta), vec))
                    if len(hits) >= k:
                        return hits
                if fetch >= total:
                    return hits
                fetch = min(total, fetch * 4)

    def get_vectors(self, namespace, ids) -> dict[str, np.ndarray]:
        ns = self._load(namespace)
        with ns.lock:
            return {i: ns.index.reconstruct(ns.str_to_int[i]) for i in ids if i in ns.str_to_int}

    def count(self, namespace) -> int:
        return self._load(namespace).index.ntotal
