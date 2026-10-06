"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

import { AppShell } from "@/components/layout/app-shell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Spinner,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";
import type {
  WorkspaceConversation,
  WorkspaceDetail,
} from "@/types/api";

type Agent = {
  id: string;
  full_name: string;
};

function Section({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`space-y-3 ${className}`}>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-stone-900">
          {title}
        </h2>
      </div>

      {children}
    </section>
  );
}

function formatDate(value?: string | null) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function normalizeText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (value === null || value === undefined) {
    return "";
  }

  return String(value);
}

function displayValue(
  value: unknown,
  fallback = "—"
): string {
  const text = normalizeText(value).trim();

  if (!text) {
    return fallback;
  }

  return text;
}

/*
 * ============================================================
 * MAIN CLIENT WORKSPACE
 * ============================================================
 *
 * IMPORTANT:
 *
 * useSearchParams() must live inside a component that is rendered
 * below <Suspense>.
 *
 * This prevents the Next.js build error:
 *
 * "useSearchParams() should be wrapped in a suspense boundary
 * at page /support-workspace"
 *
 * It also preserves direct URL opening:
 *
 * /support-workspace?conversationId=<UUID>
 */
function SupportWorkspaceContent() {
  /*
   * ============================================================
   * URL / SEARCH PARAMS
   * ============================================================
   */

  const { user } = useAuth();
  const isAdmin = !!user?.roles.some((role) => ["admin", "super_admin"].includes(role));

  const searchParams = useSearchParams();

  const requestedConversationId =
    searchParams.get("conversationId")?.trim() ?? "";

  /*
   * ============================================================
   * STATE
   * ============================================================
   */

  const [items, setItems] = useState<
    WorkspaceConversation[]
  >([]);

  const [listLoading, setListLoading] =
    useState(true);

  const [selected, setSelected] =
    useState<WorkspaceDetail | null>(null);

  const [opening, setOpening] =
    useState(false);

  const [note, setNote] = useState("");

  const [reply, setReply] = useState("");

  const [aiDraft, setAiDraft] =
    useState("");

  const [draftLoading, setDraftLoading] =
    useState(false);

  const [agents, setAgents] =
    useState<Agent[]>([]);

  const [busy, setBusy] =
    useState("");

  const [error, setError] =
    useState("");

  const [notice, setNotice] =
    useState("");

  const [lastSentReply, setLastSentReply] =
    useState("");

  const [ticketDraftStatus, setTicketDraftStatus] = useState("");
  const [ticketDraftPriority, setTicketDraftPriority] = useState("");
  const [ticketDraftAgent, setTicketDraftAgent] = useState("");

  /*
   * Prevent the requested conversation from
   * being opened repeatedly.
   */
  const [
    requestedConversationOpened,
    setRequestedConversationOpened,
  ] = useState(false);

  /*
   * ============================================================
   * ERROR HANDLING
   * ============================================================
   */

  const fail = useCallback(
    (
      errorValue: unknown,
      fallback: string
    ) => {
      if (errorValue instanceof ApiError) {
        setError(
          errorValue.message || fallback
        );
        return;
      }

      if (
        errorValue &&
        typeof errorValue === "object" &&
        "message" in errorValue
      ) {
        const message = String(
          (
            errorValue as {
              message?: unknown;
            }
          ).message ?? ""
        );

        setError(
          message || fallback
        );

        return;
      }

      setError(fallback);
    },
    []
  );

  /*
   * ============================================================
   * LOAD CONVERSATIONS
   * ============================================================
   */

  const loadConversations =
    useCallback(async () => {
      setListLoading(true);
      setError("");

      try {
        const data =
          await api.workspaceConversations();

        setItems(
          Array.isArray(data)
            ? data
            : []
        );
      } catch (e) {
        fail(
          e,
          "Could not load support conversations."
        );
      } finally {
        setListLoading(false);
      }
    }, [fail]);

  /*
   * ============================================================
   * LOAD SUPPORT AGENTS
   * ============================================================
   */

  const loadAgents =
    useCallback(async () => {
      try {
        const data =
          await api.workspaceAgents();

        setAgents(
          Array.isArray(data)
            ? data
            : []
        );
      } catch (e) {
        console.error(
          "[Support Workspace] Could not load agents:",
          e
        );
      }
    }, []);

  /*
   * ============================================================
   * OPEN CONVERSATION
   * ============================================================
   */

  const open = useCallback(
    async (
      id: string,
      keepReply = false,
      preservedReply?: string
    ) => {
      if (!id) {
        return;
      }

      setOpening(true);
      setDraftLoading(true);
      setError("");
      setNotice("");

      if (!keepReply) {
        setReply("");
        setAiDraft("");
        setLastSentReply("");
      }

      try {
        const d =
          await api.workspaceConversation(id);

        /*
         * ======================================================
         * AI DRAFT
         * ======================================================
         */

        const draft =
          typeof d.suggested_reply ===
          "string"
            ? d.suggested_reply
            : "";

        setSelected(d);
        setAiDraft(draft);

        /*
         * Preserve human-edited reply after:
         *
         * - assignment
         * - escalation
         * - resolve
         * - internal note
         * - send
         * - refresh
         */

        if (
          keepReply &&
          typeof preservedReply ===
            "string" &&
          preservedReply.trim().length > 0
        ) {
          setReply(
            preservedReply
          );
        } else {
          setReply(draft);
        }

        /*
         * ======================================================
         * DEBUG LOGS
         * ======================================================
         */

        console.log(
          "[Support Workspace] opened conversation:",
          id
        );

        console.log(
          "[Support Workspace] selected conversation:",
          d.conversation
        );

        console.log(
          "[Support Workspace] selected conversation id:",
          d.conversation?.id
        );

        console.log(
          "[Support Workspace] selected conversation title:",
          d.conversation?.title
        );

        console.log(
          "[Support Workspace] suggested_reply:",
          draft
        );

        console.log(
          "[Support Workspace] reply set to:",
          keepReply &&
            typeof preservedReply ===
              "string" &&
            preservedReply.trim()
              .length > 0
            ? preservedReply
            : draft
        );

        console.log(
          "[Support Workspace] full tickets:",
          d.tickets
        );

        console.log(
          "[Support Workspace] selected tickets count:",
          d.tickets?.length ?? 0
        );

        console.log(
          "[Support Workspace] first ticket:",
          d.tickets?.[0]
        );

        console.log(
          "[Support Workspace] related tickets:",
          d.related_tickets
        );

        /*
         * ======================================================
         * AR-63666 DIAGNOSTIC
         * ======================================================
         */

        const matchingRelatedTicket =
          d.related_tickets?.find(
            (item) =>
              item.ticket_number ===
              "AR-63666"
          );

        const matchingDirectTicket =
          d.tickets?.find(
            (item) =>
              item.ticket_number ===
              "AR-63666"
          );

        if (
          matchingRelatedTicket ||
          matchingDirectTicket
        ) {
          console.log(
            "[Support Workspace] AR-63666 found:",
            {
              direct:
                matchingDirectTicket,
              related:
                matchingRelatedTicket,
            }
          );
        }
      } catch (e) {
        fail(
          e,
          "Could not open the conversation."
        );
      } finally {
        setOpening(false);
        setDraftLoading(false);
      }
    },
    [fail]
  );

  /*
   * ============================================================
   * INITIAL LOAD
   * ============================================================
   */

  useEffect(() => {
    void loadConversations();
    void loadAgents();
  }, [
    loadConversations,
    loadAgents,
  ]);

  /*
   * ============================================================
   * OPEN CONVERSATION FROM URL
   * ============================================================
   *
   * Example:
   *
   * /support-workspace?conversationId=5a4ded45-1684-4981-a250-a3c6e5bf4954
   */

  useEffect(() => {
    if (
      !requestedConversationId ||
      requestedConversationOpened ||
      listLoading ||
      opening
    ) {
      return;
    }

    const exists = items.some(
      (item) =>
        item.id ===
        requestedConversationId
    );

    if (!exists) {
      console.warn(
        "[Support Workspace] Requested conversation ID was not found in conversation list:",
        requestedConversationId
      );

      setError(
        `Conversation ${requestedConversationId} was not found in the workspace conversation list.`
      );

      setRequestedConversationOpened(
        true
      );

      return;
    }

    setRequestedConversationOpened(
      true
    );

    void open(
      requestedConversationId
    );
  }, [
    requestedConversationId,
    requestedConversationOpened,
    listLoading,
    opening,
    items,
    open,
  ]);

  /*
   * ============================================================
   * AUTO-OPEN FIRST CONVERSATION
   * ============================================================
   *
   * Only when no conversationId exists in the URL.
   */

  useEffect(() => {
    if (
      requestedConversationId
    ) {
      return;
    }

    if (
      !selected &&
      items.length > 0 &&
      !opening
    ) {
      void open(items[0].id);
    }
  }, [
    requestedConversationId,
    items,
    selected,
    opening,
    open,
  ]);

  /*
   * ============================================================
   * CURRENT TICKET
   * ============================================================
   */

  const ticket =
    selected?.tickets?.[0] ?? null;

  useEffect(() => {
    if (!ticket) {
      setTicketDraftStatus("");
      setTicketDraftPriority("");
      setTicketDraftAgent("");
      return;
    }

    setTicketDraftStatus(ticket.status || "");
    setTicketDraftPriority(ticket.priority || "");
    setTicketDraftAgent(ticket.assigned_agent_id || "");
  }, [ticket?.id, ticket?.status, ticket?.priority, ticket?.assigned_agent_id]);

  async function applyTicketChanges() {
    if (!ticket || !isAdmin) return;

    setBusy("ticket-save");
    setError("");
    setNotice("");

    try {
      await api.updateTicket(ticket.id, {
        status: ticketDraftStatus || undefined,
        priority: ticketDraftPriority || undefined,
        assigned_agent_id: ticketDraftAgent || null,
      });

      const refreshed = await api.workspaceConversation(selectedConversationId);
      setSelected(refreshed);
      setNotice("Ticket changes saved successfully.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save ticket changes.");
    } finally {
      setBusy("");
    }
  }

  /*
   * ============================================================
   * TICKET DIAGNOSTICS
   * ============================================================
   */

  useEffect(() => {
    console.log(
      "[Support Workspace] selected tickets:",
      selected?.tickets
    );

    console.log(
      "[Support Workspace] selected tickets count:",
      selected?.tickets?.length ?? 0
    );

    console.log(
      "[Support Workspace] first ticket:",
      ticket
    );

    if (!ticket) {
      console.log(
        "[Support Workspace] ticket: none"
      );
      return;
    }

    console.log(
      "[Support Workspace] ticket number:",
      ticket.ticket_number
    );

    console.log(
      "[Support Workspace] ticket status:",
      ticket.status
    );

    console.log(
      "[Support Workspace] ticket priority:",
      ticket.priority
    );

    console.log(
      "[Support Workspace] ticket assigned agent:",
      ticket.assigned_agent_id
    );
  }, [
    ticket,
    selected?.tickets,
  ]);

  /*
   * ============================================================
   * SELECTED CONVERSATION ID
   * ============================================================
   */

  const selectedConversationId =
    selected?.conversation?.id ?? "";

  /*
   * ============================================================
   * CURRENT CUSTOMER
   * ============================================================
   */

  const customer =
    selected?.customer ?? null;

  /*
   * ============================================================
   * RUN ACTION + REFRESH
   * ============================================================
   */

  async function run(
    label: string,
    fn: () => Promise<unknown>,
    success: string,
    keepReply = true
  ) {
    if (!selected) {
      return;
    }

    setBusy(label);
    setError("");
    setNotice("");

    try {
      await fn();

      setNotice(success);

      await open(
        selected.conversation.id,
        keepReply,
        keepReply
          ? reply
          : undefined
      );
    } catch (e) {
      fail(
        e,
        "That action failed."
      );
    } finally {
      setBusy("");
    }
  }

  /*
   * ============================================================
   * RESET AI DRAFT
   * ============================================================
   */

  const resetToAiDraft =
    () => {
      setReply(aiDraft);
      setError("");
      setNotice(
        "AI draft restored."
      );
      setLastSentReply("");
    };

  /*
   * ============================================================
   * REPLY CHANGE
   * ============================================================
   */

  const handleReplyChange = (
    event: ChangeEvent<HTMLTextAreaElement>
  ) => {
    setReply(
      event.target.value
    );

    setNotice("");
    setError("");
    setLastSentReply("");
  };

  /*
   * ============================================================
   * APPROVE + SEND
   * ============================================================
   */

  const handleApproveAndSend =
    async () => {
      if (!selected) {
        return;
      }

      const humanReply =
        reply.trim();

      if (!humanReply) {
        setError(
          "Enter a reply before sending."
        );
        return;
      }

      if (!ticket) {
        setError(
          "This conversation has no directly linked ticket. The reply API currently requires a linked ticket."
        );
        return;
      }

      setBusy("send");
      setError("");
      setNotice("");

      try {
        await api.workspaceReply(
          ticket.id,
          humanReply
        );

        setLastSentReply(
          humanReply
        );

        setReply(
          humanReply
        );

        await open(
          selected.conversation.id,
          true,
          humanReply
        );

        setNotice(
          "Reply sent to the customer."
        );
      } catch (e) {
        fail(
          e,
          "Could not send the reply."
        );
      } finally {
        setBusy("");
      }
    };

  /*
   * ============================================================
   * ADD INTERNAL NOTE
   * ============================================================
   *
   * IMPORTANT:
   *
   * Correct API method:
   * workspaceAddNote()
   *
   * NOT:
   * workspaceNote()
   */

  const handleAddNote =
    async () => {
      if (!selected) {
        return;
      }

      const text =
        note.trim();

      if (!text) {
        setError(
          "Enter an internal note first."
        );
        return;
      }

      await run(
        "note",
        () =>
          api.workspaceAddNote(
            selected.conversation.id,
            text
          ),
        "Internal note added.",
        true
      );

      setNote("");
    };

  /*
   * ============================================================
   * ASSIGN AGENT
   * ============================================================
   *
   * Support agents keep the existing immediate assignment behavior.
   * Admins use the explicit Apply / Save editor below.
   */

  const handleAssign =
    async (
      agentId: string
    ) => {
      if (!ticket || isAdmin || !agentId) {
        return;
      }

      await run(
        "assign",
        () =>
          api.workspaceAssign(
            ticket.id,
            agentId
          ),
        "Agent assigned.",
        true
      );
    };

  /*
   * ============================================================
   * ESCALATE
   * ============================================================
   */

  const handleEscalate =
    async () => {
      if (!ticket) {
        setError(
          "This conversation has no linked ticket to escalate."
        );
        return;
      }

      await run(
        "escalate",
        () =>
          api.workspaceEscalate(
            ticket.id
          ),
        "Ticket escalated.",
        true
      );
    };

  /*
   * ============================================================
   * RESOLVE
   * ============================================================
   */

  const handleResolve =
    async () => {
      if (!ticket) {
        setError(
          "This conversation has no linked ticket to resolve."
        );
        return;
      }

      await run(
        "resolve",
        () =>
          api.workspaceResolve(
            ticket.id
          ),
        "Ticket resolved.",
        true
      );
    };

  /*
   * ============================================================
   * SEND BUTTON STATE
   * ============================================================
   */

  const canSend =
    Boolean(reply.trim()) &&
    busy !== "send" &&
    !draftLoading;

  /*
   * ============================================================
   * CURRENT ASSIGNED AGENT
   * ============================================================
   */

  const assignedAgent =
    useMemo(() => {
      if (!ticket?.assigned_agent_id) {
        return null;
      }

      return (
        agents.find(
          (agent) =>
            agent.id ===
            ticket.assigned_agent_id
        ) ?? null
      );
    }, [
      agents,
      ticket,
    ]);

  /*
   * ============================================================
   * RENDER
   * ============================================================
   */

  return (
    <AppShell>
      <div className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">

        {/* =====================================================
            HEADER
        ====================================================== */}

        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="mb-1 text-sm text-stone-500">
              Support
            </div>

            <h1 className="text-2xl font-semibold tracking-tight text-stone-950">
              Human + AI Support Workspace
            </h1>

            <p className="mt-1 max-w-3xl text-sm text-stone-600">
              AI drafts and classifies the conversation.
              Human agents review, edit, approve, and send
              customer-facing replies.
            </p>
          </div>

          <Link
            href="/"
            className="text-sm font-medium text-stone-700 underline-offset-4 hover:underline"
          >
            Back to dashboard
          </Link>
        </div>

        {/* =====================================================
            GLOBAL ERROR / NOTICE
        ====================================================== */}

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {notice && !error && (
          <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            {notice}
          </div>
        )}

        {/* =====================================================
            MAIN WORKSPACE
        ====================================================== */}

        <div className="grid gap-5 lg:grid-cols-[330px_minmax(0,1fr)]">

          {/* ===================================================
              CONVERSATION LIST
          ==================================================== */}

          <Card className="overflow-hidden p-0">
            <div className="border-b border-stone-200 px-4 py-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-stone-900">
                  Conversations
                </h2>

                <span className="text-xs text-stone-500">
                  {items.length}
                </span>
              </div>
            </div>

            {listLoading ? (
              <div className="flex items-center justify-center px-4 py-12">
                <Spinner />
              </div>
            ) : items.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="No conversations"
                  description="There are no support conversations available."
                />
              </div>
            ) : (
              <div className="max-h-[calc(100vh-220px)] overflow-y-auto">
                {items.map(
                  (conversation) => {
                    const active =
                      selected?.conversation
                        ?.id ===
                      conversation.id;

                    return (
                      <button
                        key={
                          conversation.id
                        }
                        type="button"
                        onClick={() =>
                          void open(
                            conversation.id
                          )
                        }
                        className={`block w-full border-b border-stone-100 px-4 py-4 text-left transition ${
                          active
                            ? "bg-stone-100"
                            : "hover:bg-stone-50"
                        }`}
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-stone-900">
                            {displayValue(
                              conversation.title,
                              "Untitled conversation"
                            )}
                          </div>

                          {conversation.status && (
                            <div className="mt-2">
                              <Badge>
                                {
                                  conversation.status
                                }
                              </Badge>
                            </div>
                          )}
                        </div>
                      </button>
                    );
                  }
                )}
              </div>
            )}
          </Card>

          {/* ===================================================
              DETAIL
          ==================================================== */}

          <div className="min-w-0">
            {!selected ? (
              <Card className="p-8">
                <EmptyState
                  title="Select a conversation"
                  description="Choose a customer conversation from the list to open the support workspace."
                />
              </Card>
            ) : (
              <div className="space-y-5">

                {/* =============================================
                    CONVERSATION
                ============================================== */}

                <Card className="p-5">
                  <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="text-xs font-medium uppercase tracking-wide text-stone-400">
                        Conversation
                      </div>

                      <h2 className="mt-1 text-lg font-semibold text-stone-950">
                        {displayValue(
                          selected.conversation
                            ?.title,
                          "Conversation"
                        )}
                      </h2>

                      {selectedConversationId && (
                        <div className="mt-1 text-[11px] text-stone-400">
                          ID:{" "}
                          <span className="font-mono">
                            {
                              selectedConversationId
                            }
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      {selected.conversation
                        ?.status && (
                        <Badge>
                          {
                            selected
                              .conversation
                              .status
                          }
                        </Badge>
                      )}

                      {opening && (
                        <Spinner />
                      )}
                    </div>
                  </div>

                  {/* =================================================
                      MESSAGES
                  ================================================== */}

                  {selected.messages &&
                  selected.messages.length > 0 ? (
                    <div className="space-y-3">
                      {selected.messages.map(
                        (message) => {
                          const isUser =
                            message.role ===
                            "user";

                          return (
                            <div
                              key={
                                message.id
                              }
                              className={`flex ${
                                isUser
                                  ? "justify-start"
                                  : "justify-end"
                              }`}
                            >
                              <div
                                className={`max-w-[85%] rounded-xl px-4 py-3 text-sm leading-6 ${
                                  isUser
                                    ? "bg-stone-100 text-stone-900"
                                    : "bg-stone-900 text-white"
                                }`}
                              >
                                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide opacity-60">
                                  {isUser
                                    ? "Customer"
                                    : "Assistant"}
                                </div>

                                <div className="whitespace-pre-wrap">
                                  {
                                    message.content
                                  }
                                </div>

                                {message.created_at && (
                                  <div className="mt-2 text-[10px] opacity-50">
                                    {formatDate(
                                      message.created_at
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        }
                      )}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-stone-200 p-6 text-center text-sm text-stone-500">
                      No messages available.
                    </div>
                  )}
                </Card>

                {/* =============================================
                    AI SUMMARY + CLASSIFICATION
                ============================================== */}

                <div className="grid gap-5 xl:grid-cols-2">

                  <Card className="p-5">
                    <Section title="AI Summary">
                      <div className="rounded-lg bg-stone-50 p-4 text-sm leading-6 text-stone-700">
                        {displayValue(
                          selected.summary,
                          "No AI summary available."
                        )}
                      </div>

                      {selected.next_action && (
                        <div>
                          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-400">
                            Next action
                          </div>

                          <div className="text-sm text-stone-700">
                            {
                              selected.next_action
                            }
                          </div>
                        </div>
                      )}
                    </Section>
                  </Card>

                  <Card className="p-5">
                    <Section title="Sentiment & Intent">
                      <div className="flex flex-wrap gap-2">

                        {selected.classification
                          ?.sentiment && (
                          <Badge>
                            Sentiment:{" "}
                            {
                              selected
                                .classification
                                .sentiment
                            }
                          </Badge>
                        )}

                        {selected.classification
                          ?.intent && (
                          <Badge>
                            Intent:{" "}
                            {
                              selected
                                .classification
                                .intent
                            }
                          </Badge>
                        )}

                        {selected.classification
                          ?.topic && (
                          <Badge>
                            Topic:{" "}
                            {
                              selected
                                .classification
                                .topic
                            }
                          </Badge>
                        )}

                        {selected.classification
                          ?.priority && (
                          <Badge>
                            Priority:{" "}
                            {
                              selected
                                .classification
                                .priority
                            }
                          </Badge>
                        )}

                        {selected.classification
                          ?.risk_level && (
                          <Badge>
                            Risk:{" "}
                            {
                              selected
                                .classification
                                .risk_level
                            }
                          </Badge>
                        )}

                      </div>

                      {typeof selected.classification
                        ?.confidence ===
                        "number" && (
                        <div className="text-xs text-stone-500">
                          Classification confidence:{" "}
                          {Math.round(
                            selected
                              .classification
                              .confidence *
                              100
                          )}
                          %
                        </div>
                      )}
                    </Section>
                  </Card>
                </div>

                {/* =============================================
                    AI QUALITY
                ============================================== */}

                {selected.quality && (
                  <Card className="p-5">
                    <Section title="AI Response Quality Guard">
                      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Grounding
                          </div>

                          <div className="mt-1 font-semibold text-stone-900">
                            {typeof selected
                              .quality
                              .grounding_score ===
                              "number"
                              ? `${Math.round(
                                  selected
                                    .quality
                                    .grounding_score *
                                    100
                                )}%`
                              : "—"}
                          </div>
                        </div>

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Policy
                          </div>

                          <div className="mt-1 font-semibold text-stone-900">
                            {
                              selected
                                .quality
                                .policy_check
                            }
                          </div>
                        </div>

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            PII
                          </div>

                          <div className="mt-1 font-semibold text-stone-900">
                            {
                              selected
                                .quality
                                .pii_check
                            }
                          </div>
                        </div>

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Decision
                          </div>

                          <div className="mt-1 font-semibold text-stone-900">
                            {
                              selected
                                .quality
                                .decision
                            }
                          </div>
                        </div>

                      </div>
                    </Section>
                  </Card>
                )}

                {/* =============================================
                    AI SUGGESTED REPLY
                ============================================== */}

                <Card className="p-5">
                  <Section title="AI-generated reply (editable)">

                    {draftLoading ? (
                      <div className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-600">
                        <Spinner />
                        Generating AI draft…
                      </div>
                    ) : aiDraft ? (
                      <>
                        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                          <span className="font-medium text-stone-700">
                            Based on:
                          </span>

                          {selected.suggested_reply_basis
                            ?.length ? (
                            selected.suggested_reply_basis.map(
                              (basis) => (
                                <Badge
                                  key={
                                    basis
                                  }
                                >
                                  {basis}
                                </Badge>
                              )
                            )
                          ) : (
                            <Badge>
                              conversation context
                            </Badge>
                          )}
                        </div>

                        <label
                          className="sr-only"
                          htmlFor="agent-reply"
                        >
                          Reply to customer
                        </label>

                        <textarea
                          id="agent-reply"
                          name="agent-reply"
                          value={reply}
                          onChange={
                            handleReplyChange
                          }
                          placeholder="AI-generated reply will appear here. You can edit it before sending."
                          aria-label="Reply to customer"
                          className="mb-2 min-h-[160px] w-full resize-y rounded-lg border border-stone-300 p-3 text-sm leading-6 outline-none transition focus:border-stone-500 focus:ring-2 focus:ring-stone-200"
                        />

                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-stone-500">
                          <span>
                            {reply.length}{" "}
                            characters
                          </span>

                          {reply !==
                          aiDraft ? (
                            <span className="font-medium text-amber-700">
                              Edited by human agent
                            </span>
                          ) : (
                            <span className="font-medium text-stone-600">
                              Original AI draft
                            </span>
                          )}
                        </div>

                        {lastSentReply && (
                          <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">
                              Last sent reply
                            </div>

                            <div className="whitespace-pre-wrap text-sm leading-6 text-emerald-950">
                              {
                                lastSentReply
                              }
                            </div>
                          </div>
                        )}

                        <div className="flex flex-wrap items-center gap-2">

                          <Button
                            variant="secondary"
                            size="sm"
                            type="button"
                            disabled={
                              !aiDraft ||
                              busy ===
                                "send"
                            }
                            onClick={
                              resetToAiDraft
                            }
                          >
                            Reset to AI draft
                          </Button>

                          <Button
                            size="sm"
                            type="button"
                            disabled={
                              !canSend
                            }
                            title={
                              !reply.trim()
                                ? "Enter a reply before sending"
                                : undefined
                            }
                            onClick={
                              handleApproveAndSend
                            }
                          >
                            {busy ===
                              "send" && (
                              <Spinner />
                            )}

                            Approve &amp; Send
                          </Button>

                        </div>

                        {!ticket && (
                          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
                            No ticket is directly
                            linked to this conversation.
                            The reply API currently
                            requires a linked ticket.
                          </p>
                        )}
                      </>
                    ) : (
                      <div className="rounded-lg border border-dashed border-stone-200 p-5 text-sm text-stone-500">
                        No AI draft was returned
                        for this conversation.
                      </div>
                    )}

                  </Section>
                </Card>

                {/* =============================================
                    TICKET
                ============================================== */}

                {ticket && (
                  <Card className="p-5">
                    <Section title="Ticket">

                      <div className="rounded-lg border border-stone-200 p-4">

                        {/* TICKET HEADER */}

                        <div className="flex flex-wrap items-center gap-2">

                          <div className="mr-2 font-semibold text-stone-950">
                            {displayValue(
                              ticket.ticket_number,
                              "Ticket"
                            )}
                          </div>

                          <Badge>
                            {displayValue(
                              ticket.status,
                              "unknown"
                            )}
                          </Badge>

                          <Badge
                            tone={
                              ticket.priority ===
                              "high"
                                ? "danger"
                                : "neutral"
                            }
                          >
                            {displayValue(
                              ticket.priority,
                              "unknown"
                            )}
                          </Badge>

                        </div>

                        {/* ASSIGNMENT */}

                        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">

                          <label
                            className="text-sm font-medium text-stone-700"
                            htmlFor="assign-agent"
                          >
                            Assign agent
                          </label>

                          <select
                            id="assign-agent"
                            value={ticketDraftAgent}
                            disabled={
                              busy ===
                              "assign"
                            }
                            onChange={(e) => {
                              const value = e.target.value;
                              if (isAdmin) {
                                setTicketDraftAgent(value);
                              } else if (value) {
                                void handleAssign(value);
                              }
                            }}
                            className="min-w-[220px] rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-stone-500 focus:ring-2 focus:ring-stone-200"
                          >
                            <option value="">
                              Assign agent
                            </option>

                            {agents.map(
                              (agent) => (
                                <option
                                  key={
                                    agent.id
                                  }
                                  value={
                                    agent.id
                                  }
                                >
                                  {
                                    agent.full_name
                                  }
                                </option>
                              )
                            )}
                          </select>

                          {busy ===
                            "assign" && (
                            <Spinner />
                          )}

                        </div>

                        {assignedAgent && (
                          <div className="mt-2 text-xs text-stone-500">
                            Assigned agent:{" "}
                            <span className="font-medium text-stone-700">
                              {
                                assignedAgent.full_name
                              }
                            </span>
                          </div>
                        )}

                        {isAdmin && (
                          <div className="mt-4 rounded-lg border border-stone-200 bg-stone-50 p-4">
                            <div className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                              Ticket changes
                            </div>

                            <div className="mt-3 grid gap-3 sm:grid-cols-2">
                              <label className="text-sm font-medium text-stone-700">
                                Status
                                <select
                                  value={ticketDraftStatus}
                                  onChange={(e) => setTicketDraftStatus(e.target.value)}
                                  className="mt-1 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-normal"
                                >
                                  <option value="open">Open</option>
                                  <option value="in_progress">In progress</option>
                                  <option value="waiting_for_customer">Waiting for customer</option>
                                  <option value="resolved">Resolved</option>
                                  <option value="closed">Closed</option>
                                </select>
                              </label>

                              <label className="text-sm font-medium text-stone-700">
                                Priority
                                <select
                                  value={ticketDraftPriority}
                                  onChange={(e) => setTicketDraftPriority(e.target.value)}
                                  className="mt-1 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-normal"
                                >
                                  <option value="low">Low</option>
                                  <option value="medium">Medium</option>
                                  <option value="high">High</option>
                                  <option value="urgent">Urgent</option>
                                </select>
                              </label>
                            </div>

                            <div className="mt-3 flex justify-end">
                              <Button
                                type="button"
                                size="sm"
                                disabled={busy === "ticket-save"}
                                onClick={() => void applyTicketChanges()}
                              >
                                {busy === "ticket-save" && <Spinner />}
                                Apply / Save
                              </Button>
                            </div>
                          </div>
                        )}

                        {/* TICKET ACTIONS */}

                        <div className="mt-4 flex flex-wrap gap-2">

                          <Button
                            variant="secondary"
                            size="sm"
                            type="button"
                            disabled={
                              busy ===
                              "escalate"
                            }
                            onClick={
                              handleEscalate
                            }
                          >
                            {busy ===
                              "escalate" && (
                              <Spinner />
                            )}

                            Escalate
                          </Button>

                          <Button
                            variant="secondary"
                            size="sm"
                            type="button"
                            disabled={
                              busy ===
                              "resolve"
                            }
                            onClick={
                              handleResolve
                            }
                          >
                            {busy ===
                              "resolve" && (
                              <Spinner />
                            )}

                            Resolve
                          </Button>

                        </div>

                        {/* TICKET DEBUG INFORMATION */}

                        <div className="mt-4 rounded-lg bg-stone-50 p-3 text-xs text-stone-500">

                          <div>
                            Ticket ID:{" "}
                            <span className="font-mono text-stone-700">
                              {
                                ticket.id
                              }
                            </span>
                          </div>

                          <div>
                            Conversation ID:{" "}
                            <span className="font-mono text-stone-700">
                              {
                                selectedConversationId
                              }
                            </span>
                          </div>

                          <div>
                            Status received:{" "}
                            <span className="font-medium text-stone-700">
                              {
                                displayValue(
                                  ticket.status
                                )
                              }
                            </span>
                          </div>

                          <div>
                            Priority received:{" "}
                            <span className="font-medium text-stone-700">
                              {
                                displayValue(
                                  ticket.priority
                                )
                              }
                            </span>
                          </div>

                        </div>

                      </div>

                    </Section>
                  </Card>
                )}

                {/* =============================================
                    RELATED TICKETS
                ============================================== */}

                {selected.related_tickets &&
                selected.related_tickets.length > 0 ? (
                  <Card className="p-5">
                    <Section title="Related tickets">

                      <div className="space-y-2">
                        {selected.related_tickets.map(
                          (related) => (
                            <div
                              key={
                                related.id
                              }
                              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-stone-200 p-3"
                            >

                              <div>
                                <div className="font-medium text-stone-900">
                                  {
                                    related.ticket_number
                                  }
                                </div>

                                <div className="text-xs text-stone-500">
                                  {
                                    related.subject
                                  }
                                </div>
                              </div>

                              <div className="flex items-center gap-2">

                                <Badge>
                                  {
                                    related.status
                                  }
                                </Badge>

                                <Badge
                                  tone={
                                    related.priority ===
                                    "high"
                                      ? "danger"
                                      : "neutral"
                                  }
                                >
                                  {
                                    related.priority
                                  }
                                </Badge>

                                {related.this_conversation && (
                                  <Badge>
                                    Current
                                  </Badge>
                                )}

                              </div>

                            </div>
                          )
                        )}
                      </div>

                    </Section>
                  </Card>
                ) : null}

                {/* =============================================
                    CUSTOMER CONTEXT
                ============================================== */}

                {customer && (
                  <Card className="p-5">
                    <Section title="Customer context">

                      <div className="grid gap-3 sm:grid-cols-3">

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Customer
                          </div>

                          <div className="mt-1 font-medium text-stone-900">
                            {displayValue(
                              customer.name
                            )}
                          </div>
                        </div>

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Conversations
                          </div>

                          <div className="mt-1 font-medium text-stone-900">
                            {
                              customer.conversations
                            }
                          </div>
                        </div>

                        <div className="rounded-lg bg-stone-50 p-3">
                          <div className="text-xs text-stone-500">
                            Open tickets
                          </div>

                          <div className="mt-1 font-medium text-stone-900">
                            {
                              customer.open_tickets
                            }
                          </div>
                        </div>

                      </div>

                    </Section>
                  </Card>
                )}

                {/* =============================================
                    INTERNAL NOTES
                ============================================== */}

                <Card className="p-5">
                  <Section title="Internal notes">

                    <div className="space-y-3">

                      {selected.internal_notes &&
                      selected.internal_notes.length > 0 ? (
                        selected.internal_notes.map(
                          (internalNote) => (
                            <div
                              key={
                                internalNote.id
                              }
                              className="rounded-lg border border-amber-200 bg-amber-50 p-3"
                            >
                              <div className="whitespace-pre-wrap text-sm leading-6 text-amber-950">
                                {
                                  internalNote.content
                                }
                              </div>

                              {internalNote.created_at && (
                                <div className="mt-2 text-[11px] text-amber-700">
                                  {formatDate(
                                    internalNote.created_at
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        )
                      ) : (
                        <div className="text-sm text-stone-500">
                          No internal notes yet.
                        </div>
                      )}

                      <div className="pt-2">

                        <label
                          className="mb-2 block text-xs font-semibold uppercase tracking-wide text-stone-400"
                          htmlFor="internal-note"
                        >
                          Add note
                        </label>

                        <textarea
                          id="internal-note"
                          value={note}
                          onChange={(e) =>
                            setNote(
                              e.target.value
                            )
                          }
                          placeholder="Add an internal note for support staff…"
                          className="min-h-[100px] w-full resize-y rounded-lg border border-stone-300 p-3 text-sm leading-6 outline-none focus:border-stone-500 focus:ring-2 focus:ring-stone-200"
                        />

                        <div className="mt-2">

                          <Button
                            variant="secondary"
                            size="sm"
                            type="button"
                            disabled={
                              !note.trim() ||
                              busy ===
                                "note"
                            }
                            onClick={
                              handleAddNote
                            }
                          >
                            {busy ===
                              "note" && (
                              <Spinner />
                            )}

                            Add internal note
                          </Button>

                        </div>
                      </div>

                    </div>

                  </Section>
                </Card>

                {/* =============================================
                    TIMELINE
                ============================================== */}

                {selected.timeline &&
                selected.timeline.length > 0 ? (
                  <Card className="p-5">
                    <Section title="Timeline">

                      <div className="space-y-3">

                        {selected.timeline.map(
                          (
                            event,
                            index
                          ) => (
                            <div
                              key={`${event.at}-${event.type}-${event.label}-${index}`}
                              className="flex gap-3"
                            >

                              <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-stone-400" />

                              <div className="min-w-0">

                                <div className="text-xs font-semibold uppercase tracking-wide text-stone-400">
                                  {
                                    event.type
                                  }
                                </div>

                                <div className="mt-1 text-sm font-medium text-stone-800">
                                  {
                                    event.label
                                  }
                                </div>

                                <div className="mt-1 text-[11px] text-stone-400">
                                  {formatDate(
                                    event.at
                                  )}
                                </div>

                              </div>
                            </div>
                          )
                        )}

                      </div>

                    </Section>
                  </Card>
                ) : (
                  <Card className="p-5">
                    <Section title="Timeline">
                      <div className="text-sm text-stone-500">
                        No timeline events.
                      </div>
                    </Section>
                  </Card>
                )}

                {/* =============================================
                    RAG / SOURCES
                ============================================== */}

                {selected.suggested_reply_basis &&
                selected.suggested_reply_basis.length > 0 ? (
                  <Card className="p-5">
                    <Section title="AI sources">

                      <div className="flex flex-wrap gap-2">
                        {selected.suggested_reply_basis.map(
                          (source) => (
                            <Badge
                              key={
                                source
                              }
                            >
                              {source}
                            </Badge>
                          )
                        )}
                      </div>

                    </Section>
                  </Card>
                ) : null}

              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

/*
 * ============================================================
 * PAGE EXPORT
 * ============================================================
 *
 * The Suspense boundary is required because
 * SupportWorkspaceContent() uses useSearchParams().
 *
 * This is the important fix for:
 *
 * "useSearchParams() should be wrapped in a suspense boundary"
 */

export default function SupportWorkspacePage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">
            <Card className="flex min-h-[300px] items-center justify-center p-8">
              <div className="flex items-center gap-3 text-sm text-stone-600">
                <Spinner />
                Loading support workspace…
              </div>
            </Card>
          </div>
        </AppShell>
      }
    >
      <SupportWorkspaceContent />
    </Suspense>
  );
}