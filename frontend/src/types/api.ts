export interface User {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  is_active?: boolean;
  created_at: string;
}

export interface AdminUser extends User {
  is_active: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: {
    sources?: string[];
    handoff?: boolean;
    handoff_reason?: string | null;
    insufficient_information?: boolean;
  } | null;
  created_at: string;
}

export interface SendMessageResponse {
  user_message: Message;
  assistant_message: Message;
  sources: string[];
  handoff: boolean;
  handoff_reason: string | null;
  ticket_number: string | null;
}

export interface OrderItem {
  product_id: string;
  product_name: string;
  quantity: number;
  price: number | null;
  final_sale: boolean;
}

export type OrderStatus =
  | "pending"
  | "processing"
  | "shipped"
  | "in_transit"
  | "delivered"
  | "cancelled"
  | "returned"
  | "exception";

export interface Order {
  id: string;
  order_number: string;
  status: OrderStatus;
  placed_at: string;
  shipped_at: string | null;
  delivered_at: string | null;
  carrier: string | null;
  tracking_number: string | null;
  estimated_delivery: string | null;
  total_amount: number | null;
  currency: string;
  items: OrderItem[];
}

export type TicketCategory =
  | "order_issue"
  | "shipping"
  | "return"
  | "refund"
  | "damaged_product"
  | "product_question"
  | "payment"
  | "account"
  | "other";

export type TicketPriority = "low" | "medium" | "high" | "urgent";
export type TicketStatus = "open" | "in_progress" | "waiting_for_customer" | "resolved" | "closed";

export interface Ticket {
  id: string;
  ticket_number: string;
  subject: string;
  description: string;
  category: TicketCategory;
  priority: TicketPriority;
  status: TicketStatus;
  created_by_ai: boolean;
  handoff_reason: string | null;
  order_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TicketMessage {
  id: string;
  author_role: "customer" | "support_agent" | "system";
  content: string;
  created_at: string;
}

export interface TicketDetail extends Ticket {
  messages: TicketMessage[];
}

// --- Knowledge Base admin (Feature 13/14) ---
export type KBDocumentStatus = "draft" | "published" | "archived";
export type KBIndexStatus = "not_indexed" | "queued" | "processing" | "completed" | "failed";

export interface KBVersion {
  id: string;
  version: number;
  content_type: string;
  source_filename: string | null;
  created_at: string;
}

export interface KBDocument {
  id: string;
  title: string;
  category: string;
  status: KBDocumentStatus;
  current_version: number;
  index_status: KBIndexStatus;
  index_error: string | null;
  last_indexed_at: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  archived_at: string | null;
}

export interface KBDocumentDetail extends KBDocument {
  content: string;
  content_type: string;
  versions: KBVersion[];
}

export interface KBDashboard {
  documents: number;
  published: number;
  drafts: number;
  archived: number;
  failed_index: number;
  index_healthy: boolean;
  last_indexed_at: string | null;
}

export interface KBIndexJob {
  id: string;
  document_id: string | null;
  job_type: "single" | "full";
  status: "queued" | "processing" | "completed" | "failed";
  error: string | null;
  documents_indexed: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// --- feedback (Feature 15) ---
export type FeedbackRating = "positive" | "negative";
export type FeedbackReason = "incorrect_answer" | "didnt_solve_problem" | "missing_information" | "needed_human" | "other";

export interface Feedback {
  id: string;
  message_id: string;
  conversation_id: string;
  rating: FeedbackRating;
  reason: FeedbackReason | null;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeedbackSubmitResponse {
  feedback: Feedback;
  suggest_handoff: boolean;
}

// --- analytics (Feature 16) ---
export interface AnalyticsSummary {
  conversations: { total: number; active: number; new: number };
  resolution: { ai_resolved: number; human_handoff: number; unresolved: number };
  feedback: { positive: number; negative: number; satisfaction_rate: number | null };
  performance: { average_response_ms: number | null; p50_ms: number | null; p95_ms: number | null; streaming_completion_ms: number | null };
  rag: {
    retrieval_success: number;
    retrieval_attempts: number;
    low_confidence_queries: number;
    no_source_responses: number;
    top_retrieved_documents: { source_file: string; count: number }[];
  };
  safety: {
    blocked_requests: number;
    prompt_injection_attempts: number;
    pii_protection_events: number;
    policy_conflicts: number;
  };
}

export interface AnalyticsTimeseries {
  days: string[];
  conversations: number[];
  ai_resolved: number[];
  human_handoff: number[];
  positive_feedback: number[];
  negative_feedback: number[];
}

export interface AnalyticsDashboard {
  range: { start: string; end: string };
  summary: AnalyticsSummary;
  timeseries: AnalyticsTimeseries;
}

// --- AI trace viewer (Feature 17) ---
export interface TraceSummary {
  trace_id: string;
  request_id: string;
  conversation_id: string;
  timestamp: number;
  timestamp_iso: string | null;
  duration_ms: number | null;
  model: string;
  retrieval_count: number;
  retrieval_outcome: "success" | "none";
  tool_calls: number;
  safety_event: boolean;
  handoff: boolean;
  status: "answered" | "handoff" | "insufficient_information" | "error";
}

export interface TraceDetail extends TraceSummary {
  durations_ms: Record<string, number>;
  timeline: { stage: string; offset_ms: number }[];
  user_message: string;
  final_response: string;
  retrieved_sources: { source_file: string; heading: string; score: number; is_active_official: boolean }[];
  tool_call_details: { name: string; success: boolean }[];
  injection_patterns_flagged: string[];
  conflict_detected: boolean;
  handoff_reason: string | null;
  insufficient_information: boolean;
  error: string | null;
  history_turns: number;
}

// --- evaluation dashboard (Feature 18) ---
export interface EvaluationCategoryBreakdown {
  [category: string]: { passed: number; total: number };
}

export interface EvaluationRun {
  id: string;
  run_number: number;
  status: "queued" | "running" | "completed" | "failed";
  use_mock_llm: boolean;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  category_breakdown: EvaluationCategoryBreakdown | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface EvaluationResult {
  id: string;
  case_id: string;
  category: string;
  passed: boolean;
  checks: Record<string, boolean> | null;
  notes: string[] | null;
  answer_preview: string | null;
}

export interface EvaluationRunDetail extends EvaluationRun {
  results: EvaluationResult[];
}

export interface EvaluationComparison {
  run_a: { id: string; run_number: number; total: number; passed: number };
  run_b: { id: string; run_number: number; total: number; passed: number };
  by_category: Record<string, { run_a: { passed: number; total: number }; run_b: { passed: number; total: number } }>;
}

export interface Phase4Organization { id:string; name:string; slug:string; status:string; plan:string; role:string; }
export interface Phase4Product { id:string; sku:string; name:string; description:string|null; category:string|null; price:number; currency:string; inventory_status:string; attributes:Record<string,unknown>|null; image_url:string|null; active:boolean; }
export interface Phase4Persona { id:string; name:string; description:string|null; tone:string; style:string; formality:string; response_length:string; language:string; brand_voice:string|null; greeting:string|null; closing:string|null; custom_instructions:string|null; status:string; active_version:number; }


export interface EnterpriseTool { name:string; description:string; permission:string; risk_level:string; category?:"read_only"|"mutating"|"external"; }
export interface AIActionItem { id:string; conversation_id:string|null; tool_name:string; arguments:any; permission_result:string; execution_status:string; result:any; risk_level:string; duration_ms:number|null; error:string|null; created_at:string;
  category?:"read_only"|"mutating"|"external"|null; origin?:"ai"|"staff"|null; reason?:string|null; approval_status?:"not_required"|"pending"|"approved"|"rejected"|null;
  actor_id?:string|null; approved_by?:string|null; approved_at?:string|null; ticket_id?:string|null; order_number?:string|null; }
export interface WorkspaceConversation { id:string; title:string; status:string; updated_at:string; last_message:string; }
export interface WorkspaceDetail { conversation:any; messages:any[]; classification:any; quality:any; suggested_reply:string; internal_notes:any[]; tickets:any[]; summary?:string; next_action?:string; suggested_reply_basis?:string[]; customer?:{customer_id:string|null;name:string|null;conversations:number;open_tickets:number}; related_orders?:{order_number:string;status:string;carrier:string|null;estimated_delivery:string|null;items:string[]}[]; related_tickets?:{id:string;ticket_number:string;status:string;priority:string;subject:string;this_conversation:boolean}[]; timeline?:{at:string;type:string;label:string}[]; sources?:string[]; }
export interface AIIntelligence { intent:string; sentiment:string; priority:string; topic:string; risk_level:string; confidence:number; }
export interface AICitation { id:string; document:string; title?:string; heading?:string|null; passage?:string|null; document_version?:string|null; source_type?:string; updated_at?:string|null; relevance_score?:number|null; }
export interface AIQuality { grounding_score:number; policy_check:string; pii_check:string; confidence:string; decision:string; }
export interface AIIntelligenceAnalytics { conversations:number; ai_resolved:number; human_handoffs:number; negative_sentiment:number; high_priority:number; average_confidence:number|null; top_intents:any[]; top_topics:any[]; sentiment_distribution:any; tool_calls:number; successful_tool_calls:number; failed_tool_calls:number; quality_decisions:any; average_grounding:number|null; }

export interface EnterpriseKBVersion {
  id:string; document_id:string; version:number; content:string; content_type:string;
  source_filename:string|null; status:string; metadata:any; created_by:string|null; created_at:string; published_at:string|null;
}
export interface PromptTemplate { id:string; name:string; description:string|null; active_version:number; versions?:any[]; created_at:string; updated_at:string; }
export interface AIUsageSummary { requests:number; input_tokens:number|null; output_tokens:number|null; total_tokens:number|null; estimated_cost:number|null; average_latency_ms:number|null; error_rate:number; daily:any[]; }
export interface Customer360 { customer:any; orders:any[]; tickets:any[]; conversations:any[]; intelligence:any; last_interaction:string|null; timeline:any[]; }
export interface GlobalSearchResult { type:string; id:string; title:string; subtitle:string; }
