export type Role = "admin" | "user";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Collection {
  id: string;
  name: string;
  description: string;
  visibility: "private" | "organization";
  owner_id: string;
  created_at: string;
  updated_at: string;
  document_count: number;
  chunk_count: number;
  size_bytes: number;
  can_write: boolean;
}

export type DocumentStatus = "pending" | "processing" | "completed" | "failed";

export interface DocumentItem {
  id: string;
  collection_id: string;
  owner_id: string;
  filename: string;
  file_type: string;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error_message: string | null;
  page_count: number;
  chunk_count: number;
  chunking_strategy: string | null;
  embedding_model: string | null;
  vector_store: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

export interface ProcessingLog {
  id: number;
  level: string;
  stage: string;
  message: string;
  duration_ms: number | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentItem {
  meta: Record<string, unknown>;
  logs: ProcessingLog[];
  collection_name: string | null;
}

export interface ChunkPreview {
  id: string;
  chunk_index: number;
  text: string;
  page_number: number | null;
  section: string | null;
  token_count: number;
}

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  document_name: string;
  file_type?: string | null;
  collection_id?: string | null;
  page_number: number | null;
  page_end?: number | null;
  section: string | null;
  snippet: string;
  score: number | null;
  vector_score?: number | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  meta: {
    grounded?: boolean;
    rewritten_query?: string | null;
    latency_ms?: number;
    retrieval?: Record<string, unknown>;
  };
  feedback: number;
  created_at: string;
  pending?: boolean;
  status?: string;
  error?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  collection_ids: string[];
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export interface RetrievalOptions {
  top_k?: number;
  similarity_threshold?: number;
  strategy?: "semantic" | "hybrid" | "mmr" | "keyword";
  reranker?: "none" | "lexical" | "llm";
  use_query_rewriting?: boolean;
  multi_query?: boolean;
  document_ids?: string[];
}

export type StreamEvent =
  | { type: "meta"; conversation_id: string; title: string }
  | { type: "status"; stage: string; message: string; queries?: string[]; sources?: number }
  | { type: "token"; content: string }
  | {
      type: "final";
      answer: string;
      citations: Citation[];
      grounded: boolean;
      rewritten_query: string | null;
      latency_ms: number;
      retrieval: Record<string, unknown>;
      message_id: string;
      conversation_id: string;
    }
  | { type: "error"; message: string }
  | { type: "done" };

export interface DashboardStats {
  total_documents: number;
  processed_documents: number;
  failed_documents: number;
  pending_documents: number;
  status_breakdown: Record<DocumentStatus, number>;
  total_chunks: number;
  total_collections: number;
  storage_bytes: number;
  file_types: { file_type: string; count: number }[];
  embedding_status: { model: string; count: number }[];
  conversations: number;
  feedback: { positive: number; negative: number; none: number };
  activity: { date: string; uploaded: number; completed: number; failed: number }[];
  recent_documents: DocumentItem[];
}

export interface EvalMetrics {
  precision: number | null;
  recall: number | null;
  hit_rate: number | null;
  mrr: number | null;
  context_relevance: number | null;
  retrieval_latency_ms: number | null;
  answer_relevance?: number | null;
  faithfulness?: number | null;
  citation_accuracy?: number | null;
  answer_correctness?: number | null;
  hallucination_rate?: number | null;
  refusal_accuracy?: number | null;
  latency_ms?: number | null;
}

export interface EvalConfigResult {
  chunking: string;
  retrieval: string;
  chunks: number;
  index_ms: number;
  metrics: EvalMetrics;
  questions: Record<string, unknown>[];
}

export interface EvaluationRun {
  id: string;
  status: "running" | "completed" | "failed";
  config: Record<string, unknown>;
  results: {
    dataset_size?: number;
    provider?: string;
    embedding_model?: string;
    duration_s?: number;
    configs?: EvalConfigResult[];
    best?: { chunking: string; retrieval: string; score: number } | null;
  };
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface AppSettings {
  llm_provider: string;
  chat_model: string;
  utility_model: string;
  embedding_model: string;
  embedding_dimension: number;
  vector_store: string;
  chunking: { strategy: string; chunk_size: number; chunk_overlap: number; strategies: string[] };
  retrieval: {
    strategy: string;
    top_k: number;
    similarity_threshold: number;
    reranker: string;
    query_rewriting: boolean;
    multi_query_count: number;
    strategies: string[];
    rerankers: string[];
  };
  upload: { max_size_mb: number; allowed_extensions: string[] };
  model_status: Record<string, unknown>;
}

export interface AuditLog {
  id: number;
  user_id: string | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}
