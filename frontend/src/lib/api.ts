import type {
  AnalyticsDashboard,
  Conversation,
  EvaluationComparison,
  EvaluationRun,
  EvaluationRunDetail,
  Feedback,
  FeedbackReason,
  FeedbackSubmitResponse,
  KBDashboard,
  KBDocument,
  KBDocumentDetail,
  KBIndexJob,
  Message,
  Order,
  Paginated,
  SendMessageResponse,
  Ticket,
  TicketDetail,
  TicketMessage,
  TraceDetail,
  TraceSummary,
  User,
  AdminUser,
  EnterpriseTool,
  AIActionItem,
  WorkspaceConversation,
  WorkspaceDetail,
  AIIntelligence,
  AICitation,
  AIQuality,
  AIIntelligenceAnalytics,
} from "@/types/api";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const ACCESS_KEY = "ar_access_token";
const REFRESH_KEY = "ar_refresh_token";

/* ============================================================================
   AUTH TOKEN HELPERS
============================================================================ */

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(
  access: string,
  refresh: string
) {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.setItem(
    ACCESS_KEY,
    access
  );

  localStorage.setItem(
    REFRESH_KEY,
    refresh
  );
}

export function clearTokens() {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

/* ============================================================================
   API ERROR
============================================================================ */

export class ApiError extends Error {
  status: number;

  constructor(
    status: number,
    message: string
  ) {
    super(message);

    this.name = "ApiError";
    this.status = status;
  }
}

/* ============================================================================
   GENERIC REQUEST
============================================================================ */

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true
): Promise<T> {
  const token = getAccessToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",

    ...(options.headers as
      | Record<string, string>
      | undefined),
  };

  if (token) {
    headers["Authorization"] =
      `Bearer ${token}`;
  }

  const res = await fetch(
    `${API_URL}${path}`,
    {
      ...options,
      headers,
    }
  );

  /*
   * Automatic access-token refresh.
   */
  if (
    res.status === 401 &&
    retry &&
    getRefreshToken()
  ) {
    const refreshed =
      await tryRefresh();

    if (refreshed) {
      return request<T>(
        path,
        options,
        false
      );
    }

    clearTokens();

    if (
      typeof window !== "undefined"
    ) {
      window.location.href =
        "/login";
    }

    throw new ApiError(
      401,
      "Session expired"
    );
  }

  /*
   * Convert backend errors into ApiError.
   */
  if (!res.ok) {
    let detail =
      res.statusText ||
      "Request failed.";

    try {
      const body =
        await res.json();

      if (
        body &&
        typeof body.detail ===
          "string"
      ) {
        detail = body.detail;
      } else if (
        body &&
        typeof body.message ===
          "string"
      ) {
        detail = body.message;
      }
    } catch {
      /*
       * Response did not contain JSON.
       */
    }

    throw new ApiError(
      res.status,
      detail
    );
  }

  /*
   * HTTP 204 has no response body.
   */
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

/* ============================================================================
   REFRESH TOKEN
============================================================================ */

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = (async () => {
    const refresh_token = getRefreshToken();

  if (!refresh_token) {
    return false;
  }

  try {
    const res =
      await fetch(
        `${API_URL}/auth/refresh`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify({
            refresh_token,
          }),
        }
      );

    if (!res.ok) {
      return false;
    }

    const body =
      await res.json();

    if (
      !body.access_token ||
      !body.refresh_token
    ) {
      return false;
    }

    setTokens(
      body.access_token,
      body.refresh_token
    );

    return true;
  } catch {
    return false;
  }
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

/* ============================================================================
   PHASE 4 TYPES
============================================================================ */

export interface Phase4KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  visibility: string;
  status: string;
}

export interface Phase4ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface Phase4Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  created_at: string;
}

export interface Phase4WebhookDelivery {
  id: string;
  event_id: string;
  event: string;
  status: string;
  status_code: number | null;
  retry_count: number;
  response_time_ms: number | null;
  created_at: string;
}

export interface Phase4RecommendationHistoryItem {
  recommendation_id: string;
  query: string;
  created_at: string;
  product_ids: string[];
  products: import("@/types/api").Phase4Product[];
}

/* ============================================================================
   SUPPORT WORKSPACE TYPES
============================================================================ */

/*
 * Response returned after posting a human support reply.
 *
 * The backend may return additional fields, so the optional
 * properties make the frontend tolerant of those responses.
 */
export interface WorkspaceReplyResponse {
  id?: string;
  ticket_id?: string;
  ticket_message_id?: string;
  content?: string;
  status?: string;
  created_at?: string;
  message?: TicketMessage | null;
}

/*
 * Generic workspace action response.
 */
export interface WorkspaceActionResponse {
  id?: string;
  ticket_id?: string;
  status?: string;
  priority?: string;
  assigned_agent_id?: string | null;
  message?: string;
}

/* ============================================================================
   API
============================================================================ */

export const api = {
  // ==========================================================================
  // AUTH
  // ==========================================================================

  signup: (
    full_name: string,
    email: string,
    password: string,
    confirm_password: string
  ) =>
    request<{
      access_token: string;
      refresh_token: string;
    }>(
      "/auth/signup",
      {
        method: "POST",

        body: JSON.stringify({
          full_name,
          email,
          password,
          confirm_password,
        }),
      }
    ),

  login: (
    email: string,
    password: string
  ) =>
    request<{
      access_token: string;
      refresh_token: string;
    }>(
      "/auth/login",
      {
        method: "POST",

        body: JSON.stringify({
          email,
          password,
        }),
      }
    ),

  logout: async () => {
    const refresh_token = getRefreshToken();

    if (refresh_token) {
      try {
        // Logout intentionally bypasses the generic request() helper. If the
        // access token is expired, request() would refresh it first and then
        // retry the logout body with the old (already rotated) refresh token.
        // Calling the logout endpoint directly revokes the exact persisted
        // refresh token the user is signing out with.
        await fetch(`${API_URL}/auth/logout`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ refresh_token }),
        });
      } catch {
        // Logout is best-effort; local credentials are still cleared below.
      }
    }

    clearTokens();
  },

  forgotPassword: (
    email: string
  ) =>
    request<{ detail: string }>(
      "/auth/forgot-password",
      {
        method: "POST",

        body: JSON.stringify({
          email,
        }),
      }
    ),

  me: () =>
    request<User>(
      "/auth/me"
    ),

  updateProfile: (
    full_name: string
  ) =>
    request<User>(
      "/users/me",
      {
        method: "PATCH",

        body: JSON.stringify({
          full_name,
        }),
      }
    ),

  // ==========================================================================
  // USER MANAGEMENT (ADMIN)
  // ==========================================================================

  adminUsers: (params?: { page?: number; page_size?: number; search?: string }) => {
    const query = new URLSearchParams();
    if (params?.page) query.set("page", String(params.page));
    if (params?.page_size) query.set("page_size", String(params.page_size));
    if (params?.search) query.set("search", params.search);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ items: AdminUser[]; total: number; page: number; page_size: number }>(`/admin/users${suffix}`);
  },

  deleteAdminUser: (id: string) =>
    request<void>(`/admin/users/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ==========================================================================
  // CONVERSATIONS
  // ==========================================================================

  listConversations: () =>
    request<Conversation[]>(
      "/conversations"
    ),

  createConversation: (
    title?: string
  ) =>
    request<Conversation>(
      "/conversations",
      {
        method: "POST",

        body: JSON.stringify({
          title,
        }),
      }
    ),

  getConversation: (
    id: string
  ) =>
    request<Conversation>(
      `/conversations/${id}`
    ),

  renameConversation: (
    id: string,
    title: string
  ) =>
    request<Conversation>(
      `/conversations/${id}`,
      {
        method: "PATCH",

        body: JSON.stringify({
          title,
        }),
      }
    ),

  archiveConversation: (
    id: string
  ) =>
    request<Conversation>(
      `/conversations/${id}/archive`,
      {
        method: "POST",
      }
    ),

  refreshSession: () =>
    tryRefresh(),

  deleteConversation: (
    id: string
  ) =>
    request<void>(
      `/conversations/${id}`,
      {
        method: "DELETE",
      }
    ),

  bulkDeleteConversations: (
    body: { ids?: string[]; all?: boolean }
  ) =>
    request<{ deleted: number }>(
      "/conversations/bulk-delete",
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    ),

  listMessages: (
    id: string
  ) =>
    request<Message[]>(
      `/conversations/${id}/messages`
    ),

  editMessage: (
    conversationId: string,
    messageId: string,
    message: string
  ) =>
    request<void>(
      `/conversations/${conversationId}/messages/${messageId}`,
      {
        method: "PATCH",

        body: JSON.stringify({
          message,
        }),
      }
    ),

  sendMessage: (
    id: string,
    message: string,
    attachmentIds: string[] = []
  ) =>
    request<SendMessageResponse>(
      `/conversations/${id}/messages`,
      {
        method: "POST",

        body: JSON.stringify({
          message,
          attachment_ids: attachmentIds,
        }),
      }
    ),

  // ==========================================================================
  // STREAMING CONVERSATIONS
  // ==========================================================================

  streamMessage: async (
    id: string,
    message: string,
    handlers: {
      onStart?: (data: {
        conversation_id: string;
        user_message: Message;
      }) => void;

      onDelta: (
        text: string
      ) => void;

      onDone: (
        data: SendMessageResponse
      ) => void;
      attachmentIds?: string[];
    },
    signal?: AbortSignal
  ): Promise<void> => {
    const token =
      getAccessToken();

    const res =
      await fetch(
        `${API_URL}/conversations/${id}/messages/stream`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",

            ...(token
              ? {
                  Authorization:
                    `Bearer ${token}`,
                }
              : {}),
          },

          body: JSON.stringify({
            message,
            attachment_ids: handlers.attachmentIds ?? [],
          }),

          signal,
        }
      );

    if (!res.ok || !res.body) {
      let detail =
        res.statusText ||
        "Streaming request failed.";

      try {
        const body =
          await res.json();

        detail =
          body.detail ||
          detail;
      } catch {
        /*
         * No JSON body.
         */
      }

      throw new ApiError(
        res.status,
        detail
      );
    }

    const reader =
      res.body.getReader();

    const decoder =
      new TextDecoder();

    let buffer = "";

    let doneReceived = false;

    while (true) {
      const {
        done,
        value,
      } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(
        value,
        {
          stream: true,
        }
      );

      let sepIndex: number;

      while (
        (sepIndex =
          buffer.indexOf(
            "\n\n"
          )) !== -1
      ) {
        const block =
          buffer.slice(
            0,
            sepIndex
          );

        buffer =
          buffer.slice(
            sepIndex + 2
          );

        let eventType =
          "message";

        let data: unknown =
          null;

        for (
          const line of
            block.split("\n")
        ) {
          if (
            line.startsWith(
              "event: "
            )
          ) {
            eventType =
              line.slice(
                "event: ".length
              );
          } else if (
            line.startsWith(
              "data: "
            )
          ) {
            try {
              data = JSON.parse(
                line.slice(
                  "data: ".length
                )
              );
            } catch {
              data = null;
            }
          }
        }

        if (data == null) {
          continue;
        }

        if (
          eventType === "start"
        ) {
          handlers.onStart?.(
            data as {
              conversation_id: string;
              user_message: Message;
            }
          );
        } else if (
          eventType === "delta"
        ) {
          handlers.onDelta(
            (
              data as {
                text: string;
              }
            ).text
          );
        } else if (
          eventType === "done"
        ) {
          if (
            doneReceived
          ) {
            continue;
          }

          doneReceived =
            true;

          handlers.onDone(
            data as SendMessageResponse
          );
        }
      }
    }

    buffer += decoder.decode();
  },

  // ==========================================================================
  // ORDERS
  // ==========================================================================

  listOrders: () =>
    request<Order[]>(
      "/orders"
    ),

  getOrder: (
    id: string
  ) =>
    request<Order>(
      `/orders/${id}`
    ),

  // ==========================================================================
  // TICKETS
  // ==========================================================================

  listTickets: () =>
    request<Ticket[]>(
      "/tickets"
    ),

  createTicket: (
    payload: {
      subject: string;
      description: string;
      category: string;
      priority?: string;
      order_id?: string;
    }
  ) =>
    request<Ticket>(
      "/tickets",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  getTicket: (
    id: string
  ) =>
    request<TicketDetail>(
      `/tickets/${id}`
    ),

  addTicketMessage: (
    id: string,
    content: string
  ) =>
    request<TicketMessage>(
      `/tickets/${id}/messages`,
      {
        method: "POST",

        body: JSON.stringify({
          content,
        }),
      }
    ),

  // ==========================================================================
  // KNOWLEDGE BASE
  // ==========================================================================

  kbSummary: () =>
    request<KBDashboard>(
      "/admin/knowledge/summary"
    ),

  kbList: (
    params?: {
      status?: string;
      category?: string;
      search?: string;
      page?: number;
    }
  ) => {
    const qs =
      new URLSearchParams();

    if (params?.status) {
      qs.set(
        "status",
        params.status
      );
    }

    if (params?.category) {
      qs.set(
        "category",
        params.category
      );
    }

    if (params?.search) {
      qs.set(
        "search",
        params.search
      );
    }

    if (params?.page) {
      qs.set(
        "page",
        String(params.page)
      );
    }

    const suffix =
      qs.toString()
        ? `?${qs.toString()}`
        : "";

    return request<
      Paginated<KBDocument>
    >(
      `/admin/knowledge${suffix}`
    );
  },

  kbGet: (
    id: string
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}`
    ),

  kbCreate: (
    payload: {
      title: string;
      category: string;
      content: string;
      content_type: string;
    }
  ) =>
    request<KBDocumentDetail>(
      "/admin/knowledge",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  kbUpdate: (
    id: string,
    payload: {
      title?: string;
      category?: string;
      content?: string;
      content_type?: string;
    }
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}`,
      {
        method: "PATCH",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  kbDelete: (
    id: string
  ) =>
    request<void>(
      `/admin/knowledge/${id}`,
      {
        method: "DELETE",
      }
    ),

  kbPublish: (
    id: string
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}/publish`,
      {
        method: "POST",
      }
    ),

  kbUnpublish: (
    id: string
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}/unpublish`,
      {
        method: "POST",
      }
    ),

  kbArchive: (
    id: string
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}/archive`,
      {
        method: "POST",
      }
    ),

  kbRestore: (
    id: string
  ) =>
    request<KBDocumentDetail>(
      `/admin/knowledge/${id}/restore`,
      {
        method: "POST",
      }
    ),

  kbReindex: (
    id: string
  ) =>
    request<KBIndexJob>(
      `/admin/knowledge/${id}/reindex`,
      {
        method: "POST",
      }
    ),

  kbReindexAll: () =>
    request<KBIndexJob>(
      "/admin/knowledge/reindex-all",
      {
        method: "POST",
      }
    ),

  kbIndexJobs: (
    documentId?: string
  ) => {
    const qs = documentId
      ? `?document_id=${encodeURIComponent(
          documentId
        )}`
      : "";

    return request<
      Paginated<KBIndexJob>
    >(
      `/admin/index-jobs${qs}`
    );
  },

  kbUpload: async (
    title: string,
    category: string,
    file: File
  ): Promise<KBDocumentDetail> => {
    const token =
      getAccessToken();

    const form =
      new FormData();

    form.append(
      "title",
      title
    );

    form.append(
      "category",
      category
    );

    form.append(
      "file",
      file
    );

    const res =
      await fetch(
        `${API_URL}/admin/knowledge/upload`,
        {
          method: "POST",

          headers: token
            ? {
                Authorization:
                  `Bearer ${token}`,
              }
            : {},

          body: form,
        }
      );

    if (!res.ok) {
      let detail =
        res.statusText ||
        "Upload failed.";

      try {
        const body =
          await res.json();

        detail =
          body.detail ||
          detail;
      } catch {
        /*
         * No JSON body.
         */
      }

      throw new ApiError(
        res.status,
        detail
      );
    }

    return res.json();
  },

  // ==========================================================================
  // PHASE 4
  // ==========================================================================

  phase4Organizations: () =>
    request<
      import("@/types/api").Phase4Organization[]
    >(
      "/api/v1/organizations"
    ),

  phase4CreateOrganization: (
    name: string
  ) =>
    request(
      "/api/v1/organizations",
      {
        method: "POST",

        body: JSON.stringify({
          name,
        }),
      }
    ),

  phase4Languages: () =>
    request<Record<string, string>>(
      "/api/v1/languages"
    ),

  phase4DetectLanguage: (
    text: string
  ) =>
    request<{
      language: string;
      name: string;
    }>(
      "/api/v1/languages/detect",
      {
        method: "POST",

        body: JSON.stringify({
          text,
        }),
      }
    ),

  phase4GetLanguage: () =>
    request<{
      preferred_language: string;
    }>(
      "/api/v1/users/me/preferences/language"
    ),

  phase4SetLanguage: (
    preferred_language: string
  ) =>
    request<{
      preferred_language: string;
    }>(
      "/api/v1/users/me/preferences/language",
      {
        method: "PATCH",

        body: JSON.stringify({
          preferred_language,
        }),
      }
    ),

  phase4Products: (
    q?: string
  ) =>
    request<
      import("@/types/api").Phase4Product[]
    >(
      `/api/v1/products${
        q
          ? `?q=${encodeURIComponent(
              q
            )}`
          : ""
      }`
    ),

  // ==========================================================================
  // PRODUCT RECOMMENDATIONS
  // ==========================================================================

  phase4Recommend: (
    payload: {
      query: string;
      budget?: number;
      category?: string;
      limit?: number;
    }
  ) =>
    request<{
      query: string;
      products: import("@/types/api").Phase4Product[];
      recommendation_id: string;
    }>(
      "/api/v1/recommendations",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  phase4RecommendationHistory:
    () =>
      request<
        Phase4RecommendationHistoryItem[]
      >(
        "/api/v1/recommendations"
      ),

  phase4DeleteRecommendation: (
    recommendationId: string
  ) =>
    request<void>(
      `/api/v1/recommendations/${recommendationId}`,
      {
        method: "DELETE",
      }
    ),

  // ==========================================================================
  // PERSONAS
  // ==========================================================================

  phase4Personas: () =>
    request<
      import("@/types/api").Phase4Persona[]
    >(
      "/api/v1/personas"
    ),

  phase4CreatePersona: (
    payload: Record<string, unknown>
  ) =>
    request<
      import("@/types/api").Phase4Persona
    >(
      "/api/v1/personas",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  phase4UpdatePersona: (
    id: string,
    payload: Record<string, unknown>
  ) =>
    request<
      import("@/types/api").Phase4Persona
    >(
      `/api/v1/personas/${id}`,
      {
        method: "PATCH",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  phase4PublishPersona: (
    id: string
  ) =>
    request<
      import("@/types/api").Phase4Persona
    >(
      `/api/v1/personas/${id}/publish`,
      {
        method: "POST",
      }
    ),

  // ==========================================================================
  // CUSTOM KNOWLEDGE BASES
  // ==========================================================================

  phase4KBs: () =>
    request<Phase4KnowledgeBase[]>(
      "/api/v1/knowledge-bases"
    ),

  phase4CreateKB: (
    payload: {
      name: string;
      description?: string;
      visibility?: string;
    }
  ) =>
    request(
      "/api/v1/knowledge-bases",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  // ==========================================================================
  // API KEYS
  // ==========================================================================

  phase4Keys: () =>
    request<Phase4ApiKey[]>(
      "/api/v1/api-keys"
    ),

  phase4CreateKey: (
    payload: {
      name: string;
      scopes: string[];
      expires_in_days?: number;
    }
  ) =>
    request<
      Phase4ApiKey & {
        secret: string;
      }
    >(
      "/api/v1/api-keys",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  phase4RevokeKey: (
    id: string
  ) =>
    request(
      `/api/v1/api-keys/${id}`,
      {
        method: "DELETE",
      }
    ),

  // ==========================================================================
  // WEBHOOKS
  // ==========================================================================

  phase4Webhooks: () =>
    request<Phase4Webhook[]>(
      "/api/v1/webhooks"
    ),

  phase4CreateWebhook: (
    payload: {
      url: string;
      events: string[];
    }
  ) =>
    request<
      Phase4Webhook & {
        secret: string;
      }
    >(
      "/api/v1/webhooks",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  phase4DeleteWebhook: (
    id: string
  ) =>
    request(
      `/api/v1/webhooks/${id}`,
      {
        method: "DELETE",
      }
    ),

  phase4WebhookDeliveries: () =>
    request<
      Phase4WebhookDelivery[]
    >(
      "/api/v1/webhooks/deliveries"
    ),

  // ==========================================================================
  // FEEDBACK
  // ==========================================================================

  submitFeedback: (
    messageId: string,
    payload: {
      rating:
        | "positive"
        | "negative";

      reason?: FeedbackReason;

      comment?: string;
    }
  ) =>
    request<FeedbackSubmitResponse>(
      `/messages/${messageId}/feedback`,
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  getFeedback: (
    messageId: string
  ) =>
    request<Feedback | null>(
      `/messages/${messageId}/feedback`
    ),

  // ==========================================================================
  // ANALYTICS
  // ==========================================================================

  analyticsDashboard: (
    range: string,
    startDate?: string,
    endDate?: string
  ) => {
    const qs =
      new URLSearchParams({
        range,
      });

    if (startDate) {
      qs.set(
        "start_date",
        startDate
      );
    }

    if (endDate) {
      qs.set(
        "end_date",
        endDate
      );
    }

    return request<AnalyticsDashboard>(
      `/admin/analytics?${qs.toString()}`
    );
  },

  // ==========================================================================
  // TRACE VIEWER
  // ==========================================================================

  listTraces: (
    params: {
      conversationId?: string;
      status?: string;
      handoff?: boolean;
      safetyEvent?: boolean;
      page?: number;
    }
  ) => {
    const qs =
      new URLSearchParams();

    if (params.conversationId) {
      qs.set(
        "conversation_id",
        params.conversationId
      );
    }

    if (params.status) {
      qs.set(
        "status",
        params.status
      );
    }

    if (
      params.handoff !==
      undefined
    ) {
      qs.set(
        "handoff",
        String(
          params.handoff
        )
      );
    }

    if (
      params.safetyEvent !==
      undefined
    ) {
      qs.set(
        "safety_event",
        String(
          params.safetyEvent
        )
      );
    }

    if (params.page) {
      qs.set(
        "page",
        String(params.page)
      );
    }

    const suffix =
      qs.toString()
        ? `?${qs.toString()}`
        : "";

    return request<
      Paginated<TraceSummary>
    >(
      `/admin/traces${suffix}`
    );
  },

  getTrace: (
    traceId: string
  ) =>
    request<TraceDetail>(
      `/admin/traces/${traceId}`
    ),

  // ==========================================================================
  // EVALUATION
  // ==========================================================================

  listEvaluationRuns: () =>
    request<
      Paginated<EvaluationRun>
    >(
      "/admin/evaluations"
    ),

  runEvaluation: (
    payload: {
      use_mock_llm?: boolean;
      case_ids?: string[];
    }
  ) =>
    request<EvaluationRun>(
      "/admin/evaluations/run",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  getEvaluationRun: (
    id: string
  ) =>
    request<EvaluationRunDetail>(
      `/admin/evaluations/${id}`
    ),

  compareEvaluationRuns: (
    runA: string,
    runB: string
  ) =>
    request<EvaluationComparison>(
      `/admin/evaluations/compare?run_a=${encodeURIComponent(
        runA
      )}&run_b=${encodeURIComponent(
        runB
      )}`
    ),

  playgroundCompare: (
    payload: {
      kind:
        | "models"
        | "prompts"
        | "retrieval";

      question: string;

      expected_answer?: string;

      models?: string[];

      prompt_versions?: {
        prompt_id: string;
        version: number;
      }[];

      top_k_values?: number[];
    }
  ) =>
    request<any>(
      "/admin/evaluations/compare",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  evaluationTestCases: () =>
    request<any[]>(
      "/admin/evaluations/test-cases"
    ),

  createEvaluationTestCase: (
    payload: {
      question: string;
      expected_answer?: string;
      category?: string;
    }
  ) =>
    request<any>(
      "/admin/evaluations/test-cases",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  deleteEvaluationTestCase: (
    id: string
  ) =>
    request<void>(
      `/admin/evaluations/test-cases/${id}`,
      {
        method: "DELETE",
      }
    ),

  runEvaluationTestCases: () =>
    request<any>(
      "/admin/evaluations/test-cases/run",
      {
        method: "POST",
      }
    ),

  // ==========================================================================
  // ACTION CENTER
  // ==========================================================================

  enterpriseTools: () =>
    request<{
      tools: EnterpriseTool[];
    }>(
      "/action-center/tools"
    ),

  enterpriseActions: (
    params?: {
      status?: string;
      approval_status?: string;
      tool_name?: string;
      limit?: number;
      offset?: number;
    }
  ) => {
    const qs =
      new URLSearchParams();

    Object.entries(
      params ?? {}
    ).forEach(
      ([key, value]) => {
        if (
          value !== undefined &&
          value !== ""
        ) {
          qs.set(
            key,
            String(value)
          );
        }
      }
    );

    const query =
      qs.toString();

    return request<AIActionItem[]>(
      `/action-center/actions${
        query
          ? `?${query}`
          : ""
      }`
    );
  },

  approveEnterpriseAction: (
    id: string
  ) =>
    request<any>(
      `/action-center/actions/${id}/approve`,
      {
        method: "POST",
      }
    ),

  rejectEnterpriseAction: (
    id: string,
    note?: string
  ) =>
    request<any>(
      `/action-center/actions/${id}/reject`,
      {
        method: "POST",

        body: JSON.stringify({
          note:
            note ?? null,
        }),
      }
    ),

  executeEnterpriseAction: (
    payload: {
      tool_name: string;
      arguments: Record<
        string,
        unknown
      >;
      conversation_id?: string;
    }
  ) =>
    request<any>(
      "/action-center/execute",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  // ==========================================================================
  // FEATURE 2 — HUMAN + AI SUPPORT WORKSPACE
  // ==========================================================================

  /*
   * Get the support-workspace conversation list.
   */
  workspaceConversations: () =>
    request<WorkspaceConversation[]>(
      "/support-workspace/conversations"
    ),

  /*
   * Get complete workspace information for one conversation.
   *
   * Includes:
   * - conversation
   * - messages
   * - summary
   * - classification
   * - quality
   * - suggested_reply
   * - ticket information
   * - customer context
   * - related orders
   * - related tickets
   * - timeline
   * - internal notes
   */
  workspaceConversation: (
    id: string
  ) =>
    request<WorkspaceDetail>(
      `/support-workspace/conversations/${encodeURIComponent(
        id
      )}`
    ),

  /*
   * Get support agents.
   */
  workspaceAgents: () =>
    request<
      {
        id: string;
        full_name: string;
        roles: string[];
      }[]
    >(
      "/support-workspace/agents"
    ),

  /*
   * IMPORTANT:
   *
   * This method sends EXACTLY the string supplied by the
   * human agent.
   *
   * The frontend textarea -> handleApproveAndSend()
   * -> workspaceReply()
   * -> backend.
   *
   * There is deliberately NO suggested_reply fallback here.
   * There is deliberately NO trimming here.
   *
   * Therefore:
   *
   *   "I'll keep you updated regarding your request."
   *
   * remains exactly that string when sent.
   */
  workspaceReply: (
    ticketId: string,
    content: string
  ) => {
    const normalizedTicketId =
      String(ticketId);

    /*
     * Do not modify `content`.
     *
     * The human-editable textarea is the source of truth.
     */
    const humanContent =
      String(content);

    return request<
      WorkspaceReplyResponse
    >(
      `/support-workspace/tickets/${encodeURIComponent(
        normalizedTicketId
      )}/messages`,
      {
        method: "POST",

        body: JSON.stringify({
          content:
            humanContent,
        }),
      }
    );
  },

  /*
   * Add staff-only internal note.
   */
  workspaceAddNote: (
    conversationId: string,
    content: string
  ) =>
    request<any>(
      `/support-workspace/conversations/${encodeURIComponent(
        conversationId
      )}/notes`,
      {
        method: "POST",

        body: JSON.stringify({
          content,
        }),
      }
    ),

  /*
   * Assign / reassign ticket.
   */
  workspaceAssign: (
    ticketId: string,
    agentId: string
  ) =>
    request<WorkspaceActionResponse>(
      `/support-workspace/tickets/${encodeURIComponent(
        ticketId
      )}/assign`,
      {
        method: "POST",

        body: JSON.stringify({
          agent_id:
            agentId,
        }),
      }
    ),

  /*
   * Escalate ticket.
   */
  workspaceEscalate: (
    ticketId: string
  ) =>
    request<WorkspaceActionResponse>(
      `/support-workspace/tickets/${encodeURIComponent(
        ticketId
      )}/escalate`,
      {
        method: "POST",
      }
    ),

  /*
   * Resolve ticket.
   */
  workspaceResolve: (
    ticketId: string
  ) =>
    request<WorkspaceActionResponse>(
      `/support-workspace/tickets/${encodeURIComponent(
        ticketId
      )}/resolve`,
      {
        method: "POST",
      }
    ),

  /**
   * Apply ticket changes from the Support Workspace ticket editor.
   * The backend endpoint is the canonical ticket PATCH endpoint.
   */
  updateTicket: (
    ticketId: string,
    changes: {
      status?: string;
      priority?: string;
      assigned_agent_id?: string | null;
    }
  ) =>
    request<any>(
      `/tickets/${encodeURIComponent(ticketId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(changes),
      }
    ),

  // ==========================================================================
  // AI INTELLIGENCE
  // ==========================================================================

  conversationIntelligence: (
    id: string
  ) =>
    request<AIIntelligence>(
      `/conversations/${encodeURIComponent(
        id
      )}/intelligence`
    ),

  conversationCitations: (
    id: string
  ) =>
    request<AICitation[]>(
      `/conversations/${encodeURIComponent(
        id
      )}/citations`
    ),

  citation: (
    id: string
  ) =>
    request<AICitation>(
      `/citations/${encodeURIComponent(
        id
      )}`
    ),

  aiQuality: (
    id: string
  ) =>
    request<AIQuality>(
      `/ai-quality/conversations/${encodeURIComponent(
        id
      )}`
    ),

  aiIntelligenceAnalytics: () =>
    request<AIIntelligenceAnalytics>(
      "/analytics/ai-intelligence"
    ),

  // ==========================================================================
  // KNOWLEDGE BASE VERSIONS
  // ==========================================================================

  enterpriseKBVersions: (
    id: string
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/versions`
    ),

  enterpriseKBDiff: (
    id: string,
    fromVersion: number,
    toVersion: number
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/diff?from_version=${encodeURIComponent(
        fromVersion
      )}&to_version=${encodeURIComponent(
        toVersion
      )}`
    ),

  enterpriseKBRollback: (
    id: string,
    versionId: string
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/rollback/${encodeURIComponent(
        versionId
      )}`,
      {
        method: "POST",
      }
    ),

  enterpriseKBPublish: (
    id: string,
    versionId: string
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/versions/${encodeURIComponent(
        versionId
      )}/publish`,
      {
        method: "POST",
      }
    ),

  enterpriseKBArchive: (
    id: string,
    versionId: string
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/versions/${encodeURIComponent(
        versionId
      )}/archive`,
      {
        method: "POST",
      }
    ),

  enterpriseKBRestore: (
    id: string,
    versionId: string
  ) =>
    request<any>(
      `/admin/knowledge/${encodeURIComponent(
        id
      )}/versions/${encodeURIComponent(
        versionId
      )}/restore`,
      {
        method: "POST",
      }
    ),

  // ==========================================================================
  // EVALUATION PLAYGROUND
  // ==========================================================================

  playgroundModels: () =>
    request<{
      models: string[];
    }>(
      "/admin/evaluations/playground/models"
    ),

  playgroundRun: (
    payload: any
  ) =>
    request<any>(
      "/admin/evaluations/playground/run",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  playgroundRuns: () =>
    request<any>(
      "/admin/evaluations/playground/runs"
    ),

  // ==========================================================================
  // PROMPT MANAGEMENT
  // ==========================================================================

  prompts: () =>
    request<any[]>(
      "/admin/prompts"
    ),

  createPrompt: (
    payload: any
  ) =>
    request<any>(
      "/admin/prompts",
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  promptDetail: (
    id: string
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        id
      )}`
    ),

  createPromptVersion: (
    id: string,
    content: string
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        id
      )}/versions`,
      {
        method: "POST",

        body: JSON.stringify({
          content,
        }),
      }
    ),

  updatePromptVersion: (
    id: string,
    version: number,
    content: string
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ content }),
      }
    ),

  deletePromptVersion: (
    id: string,
    version: number
  ) =>
    request<{
      deleted: boolean;
      prompt_id: string;
      deleted_version: number;
      active_version: number | null;
    }>(
      `/admin/prompts/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`,
      {
        method: "DELETE",
      }
    ),

  publishPrompt: (
    id: string,
    version?: number
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        id
      )}/publish${
        version !== undefined
          ? `?version=${encodeURIComponent(
              version
            )}`
          : ""
      }`,
      {
        method: "POST",
      }
    ),

  rollbackPrompt: (
    id: string,
    version: number
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        id
      )}/rollback/${encodeURIComponent(
        version
      )}`,
      {
        method: "POST",
      }
    ),

  testPrompt: (
    id: string,
    input: any
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        id
      )}/test`,
      {
        method: "POST",

        body: JSON.stringify({
          input,
        }),
      }
    ),

  // ==========================================================================
  // AI USAGE
  // ==========================================================================

  aiUsage: (
    days = 30,
    model?: string,
    feature?: string
  ) => {
    const q =
      new URLSearchParams({
        days: String(days),
      });

    if (model) {
      q.set(
        "model",
        model
      );
    }

    if (feature) {
      q.set(
        "feature",
        feature
      );
    }

    return request<any>(
      `/admin/analytics/ai-usage?${q.toString()}`
    );
  },

  // ==========================================================================
  // MODEL ROUTER
  // ==========================================================================

  modelRouterPreview: (
    category: string,
    reason?: string
  ) =>
    request<any>(
      "/admin/ai/router/preview",
      {
        method: "POST",

        body: JSON.stringify({
          category,
          reason,
        }),
      }
    ),

  modelRouterEvents: () =>
    request<any[]>(
      "/admin/ai/router/events"
    ),

  // ==========================================================================
  // CUSTOMER 360
  // ==========================================================================

  customer360: (
    id: string
  ) =>
    request<any>(
      `/customers/${encodeURIComponent(
        id
      )}/360`
    ),

  // ==========================================================================
  // PROMPT EXPERIMENTS
  // ==========================================================================

  createExperiment: (
    promptId: string,
    payload: {
      name: string;
      variant_a_version: number;
      variant_b_version: number;
      traffic_split_b: number;
    }
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        promptId
      )}/experiments`,
      {
        method: "POST",

        body: JSON.stringify(
          payload
        ),
      }
    ),

  experiments: (
    promptId: string
  ) =>
    request<any[]>(
      `/admin/prompts/${encodeURIComponent(
        promptId
      )}/experiments`
    ),

  stopExperiment: (
    promptId: string,
    experimentId: string
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        promptId
      )}/experiments/${encodeURIComponent(
        experimentId
      )}/stop`,
      {
        method: "POST",
      }
    ),

  resolveExperiment: (
    promptId: string,
    experimentId: string,
    bucketKey: string
  ) =>
    request<any>(
      `/admin/prompts/${encodeURIComponent(
        promptId
      )}/experiments/${encodeURIComponent(
        experimentId
      )}/resolve?bucket_key=${encodeURIComponent(
        bucketKey
      )}`
    ),

  // ==========================================================================
  // GLOBAL SEARCH
  // ==========================================================================

  globalSearch: (
    q: string
  ) =>
    request<any>(
      `/search?q=${encodeURIComponent(
        q
      )}`
    ),

  // ==========================================================================
  // RECOMMENDATION EXPLANATION
  // ==========================================================================

  recommendationExplanation: (
    id: string
  ) =>
    request<any>(
      `/recommendations/${encodeURIComponent(
        id
      )}/explanation`
    ),

  recommendationExplanationAction: (
    id: string,
    productId: string,
    action: string
  ) =>
    request<any>(
      `/recommendations/${encodeURIComponent(
        id
      )}/explanation/actions?product_id=${encodeURIComponent(
        productId
      )}&action=${encodeURIComponent(
        action
      )}`,
      {
        method: "POST",
      }
    ),

  // ==========================================================================
  // SOURCE EXPLORER
  // ==========================================================================

  sourceExplorer: (
    id: string
  ) =>
    request<any[]>(
      `/conversations/${encodeURIComponent(
        id
      )}/source-explorer`
    ),
};