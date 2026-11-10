import type {
  AppSettings,
  AuditLog,
  Collection,
  ConversationDetail,
  ConversationSummary,
  DashboardStats,
  DocumentDetail,
  DocumentItem,
  ChunkPreview,
  EvaluationRun,
  RetrievalOptions,
  StreamEvent,
  User,
} from "@/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "rag.token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const tokenStore = {
  get: (): string | null => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => window.localStorage.setItem(TOKEN_KEY, t),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
};

function authHeaders(): Record<string, string> {
  const t = tokenStore.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function parseError(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    if (Array.isArray(body.errors) && body.errors.length) {
      message = body.errors.map((e: { loc: string[]; msg: string }) => `${e.loc.slice(-1)[0]}: ${e.msg}`).join("; ");
    }
  } catch {
    /* non-JSON body */
  }
  if (res.status === 401 && typeof window !== "undefined") {
    tokenStore.clear();
    window.dispatchEvent(new Event("rag:unauthorized"));
  }
  return new ApiError(res.status, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders(), ...(init.headers as Record<string, string>) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null | string[]>) => {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string, full_name: string) =>
    request<{ access_token: string; user: User }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    }),
  me: () => request<User>("/api/auth/me"),
  users: () => request<User[]>("/api/users"),
  setRole: (id: string, role: string) =>
    request<User>(`/api/users/${id}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
  setActive: (id: string, is_active: boolean) =>
    request<User>(`/api/users/${id}/active`, { method: "PATCH", body: JSON.stringify({ is_active }) }),

  // collections
  collections: () => request<Collection[]>("/api/collections"),
  createCollection: (body: { name: string; description: string; visibility: string }) =>
    request<Collection>("/api/collections", { method: "POST", body: JSON.stringify(body) }),
  updateCollection: (id: string, body: Partial<{ name: string; description: string; visibility: string }>) =>
    request<Collection>(`/api/collections/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCollection: (id: string) => request<void>(`/api/collections/${id}`, { method: "DELETE" }),

  // documents
  documents: (p: { collection_id?: string; search?: string; status?: string; file_type?: string; offset?: number; limit?: number }) =>
    request<{ items: DocumentItem[]; total: number }>(`/api/documents${qs(p)}`),
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  upload: (files: File[], collectionId?: string, strategy?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (collectionId) fd.append("collection_id", collectionId);
    if (strategy) fd.append("chunking_strategy", strategy);
    return request<{ documents: DocumentItem[]; rejected: { filename: string; reason: string }[] }>(
      "/api/documents/upload",
      { method: "POST", body: fd },
    );
  },
  reprocess: (id: string, body: { chunking_strategy?: string; chunk_size?: number; chunk_overlap?: number }) =>
    request<DocumentItem>(`/api/documents/${id}/reprocess`, { method: "POST", body: JSON.stringify(body) }),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  preview: (id: string, page?: number | null) =>
    request<{ document_id: string; filename: string; page: number | null; page_count: number; chunks: ChunkPreview[] }>(
      `/api/documents/${id}/preview${qs({ page: page ?? undefined })}`,
    ),
  /** Fetch the original file with auth and return an object URL (for inline viewing). */
  fileUrl: async (id: string): Promise<{ url: string; type: string }> => {
    const res = await fetch(`${API_URL}/api/documents/${id}/file`, { headers: authHeaders() });
    if (!res.ok) throw await parseError(res);
    const blob = await res.blob();
    return { url: URL.createObjectURL(blob), type: blob.type };
  },

  // chat
  history: () => request<ConversationSummary[]>("/api/chat/history"),
  conversation: (id: string) => request<ConversationDetail>(`/api/chat/${id}`),
  deleteConversation: (id: string) => request<void>(`/api/chat/${id}`, { method: "DELETE" }),
  renameConversation: (id: string, title: string) =>
    request<ConversationSummary>(`/api/chat/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  feedback: (messageId: string, rating: number) =>
    request(`/api/chat/messages/${messageId}/feedback`, { method: "POST", body: JSON.stringify({ rating }) }),
  suggestions: (collection_ids: string[]) => request<string[]>(`/api/chat/suggestions${qs({ collection_ids })}`),

  /** Streaming chat over Server-Sent Events (POST, so we parse the stream manually). */
  streamChat: async (
    body: {
      message: string;
      conversation_id?: string | null;
      collection_ids?: string[];
      options?: RetrievalOptions;
      regenerate?: boolean;
    },
    onEvent: (e: StreamEvent) => void,
    signal?: AbortSignal,
  ) => {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...authHeaders() },
        body: JSON.stringify({ ...body, stream: true }),
        signal,
      });
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
    }
    if (!res.ok || !res.body) throw await parseError(res);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const line = raw.split("\n").find((l) => l.startsWith("data: "));
        if (line) onEvent(JSON.parse(line.slice(6)) as StreamEvent);
      }
    }
  },

  // dashboard / admin
  stats: () => request<DashboardStats>("/api/dashboard/stats"),
  auditLogs: (limit = 200) => request<AuditLog[]>(`/api/audit-logs${qs({ limit })}`),
  settings: () => request<AppSettings>("/api/settings"),
  checkModels: () => request<Record<string, unknown>>("/api/settings/check-models", { method: "POST" }),
  health: () => request<Record<string, unknown>>("/api/health"),

  // evaluation
  evaluationRuns: () => request<EvaluationRun[]>("/api/evaluation/runs"),
  evaluationRun: (id: string) => request<EvaluationRun>(`/api/evaluation/runs/${id}`),
  runEvaluation: (body: {
    chunking_strategies: string[];
    retrieval_strategies: string[];
    top_k: number;
    evaluate_generation: boolean;
  }) => request<EvaluationRun>("/api/evaluation/run", { method: "POST", body: JSON.stringify(body) }),
  evaluationDataset: () => request<Record<string, unknown>[]>("/api/evaluation/dataset"),
};

export function formatBytes(n: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function formatDate(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(s: string): string {
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`).getTime();
  const sec = Math.round((Date.now() - d) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
