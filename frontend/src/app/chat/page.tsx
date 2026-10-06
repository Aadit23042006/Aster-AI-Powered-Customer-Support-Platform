"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  Send,
  Menu,
  X,
  ExternalLink,
  AlertTriangle,
  Square,
  RotateCcw,
  ThumbsUp,
  ThumbsDown,
  Copy,
  Check,
  Pencil,
  Trash2,
  Share2,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import { Badge, Button, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import type {
  Conversation,
  FeedbackReason,
  Message,
} from "@/types/api";

const SUGGESTED = [
  "Where is my order?",
  "What's your return policy?",
  "How long does shipping take?",
  "Talk to a human",
];

// ============================================================================
// Chat Page Inner
// ============================================================================

function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeId = searchParams.get("c");

  const [conversations, setConversations] = useState<
    Conversation[] | null
  >(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingText, setStreamingText] = useState<string | null>(
    null
  );
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedText, setLastFailedText] = useState<string | null>(
    null
  );
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shareNotice, setShareNotice] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // -------------------------------------------------------------------------
  // Prevent multiple send() calls from running at the same time.
  // -------------------------------------------------------------------------

  const sendLockRef = useRef(false);

  // -------------------------------------------------------------------------
  // Conversation loading
  // -------------------------------------------------------------------------

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.listConversations();

      setConversations(list);

      return list;
    } catch {
      setConversations([]);

      return [];
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadConversations();
  }, [loadConversations]);

  // -------------------------------------------------------------------------
  // Message loading
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!activeId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      return;
    }

    setLoadingMessages(true);

    api.listMessages(activeId)
      .then(setMessages)
      .catch(() => setMessages([]))
      .finally(() => {
        setLoadingMessages(false);
      });

    const draftKey = `draft:${activeId}`;
    const draft = sessionStorage.getItem(draftKey);

    if (draft) {
      sessionStorage.removeItem(draftKey);

      send(draft, activeId);
    }

    // send() intentionally omitted from dependencies.
    // This effect should only react to active conversation changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // -------------------------------------------------------------------------
  // Auto-scroll
  // -------------------------------------------------------------------------

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages, sending, streamingText]);

  // -------------------------------------------------------------------------
  // New conversation
  // -------------------------------------------------------------------------

  async function newConversation() {
    try {
      const conv = await api.createConversation();

      await loadConversations();

      router.push(`/chat?c=${conv.id}`);

      setDrawerOpen(false);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not create a new conversation."
      );
    }
  }

  // -------------------------------------------------------------------------
  // Chat history actions
  // -------------------------------------------------------------------------

  async function deleteConversationById(conversationId: string) {
    try {
      await api.deleteConversation(conversationId);
      const remaining = (await loadConversations()).filter(
        (conversation) => conversation.id !== conversationId
      );
      setConversations(remaining);

      if (conversationId === activeId) {
        setMessages([]);
        setEditingMessageId(null);
          router.push("/chat");
      }
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not delete chat history."
      );
    } finally {
      setDeleteTarget(null);
    }
  }

  function exitSelectMode() {
    setSelectMode(false);
    setSelectedIds(new Set());
  }

  function toggleSelected(conversationId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(conversationId)) next.delete(conversationId);
      else next.add(conversationId);
      return next;
    });
  }

  function toggleSelectAll() {
    const all = conversations ?? [];
    setSelectedIds((prev) =>
      prev.size === all.length && all.length > 0
        ? new Set()
        : new Set(all.map((conversation) => conversation.id))
    );
  }

  async function bulkDeleteSelected() {
    if (selectedIds.size === 0) return;
    setBulkDeleting(true);
    try {
      const ids = Array.from(selectedIds);
      await api.bulkDeleteConversations({ ids });
      const remaining = await loadConversations();
      setConversations(remaining);

      if (activeId && ids.includes(activeId)) {
        setMessages([]);
        setEditingMessageId(null);
        router.push("/chat");
      }
      exitSelectMode();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not delete chat history."
      );
    } finally {
      setBulkDeleting(false);
      setBulkDeleteOpen(false);
    }
  }

  async function shareConversation() {
    if (!activeId) return;

    const shareUrl = `${window.location.origin}/chat?c=${encodeURIComponent(activeId)}`;
    const title = conversations?.find((item) => item.id === activeId)?.title || "Aster Support AI Conversation";

    setSharing(true);
    setShareNotice(null);

    try {
      if (navigator.share) {
        await navigator.share({ title, text: "Aster Support AI conversation", url: shareUrl });
        setShareNotice("Share dialog opened.");
      } else {
        await navigator.clipboard.writeText(shareUrl);
        setShareNotice("Conversation link copied.");
      }
    } catch (e) {
      // AbortError means the user simply closed the native share sheet.
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError("Could not share the conversation.");
    } finally {
      setSharing(false);
      window.setTimeout(() => setShareNotice(null), 2500);
    }
  }

  function startEditingMessage(message: Message) {
    if (message.role !== "user" || sending) return;
    setEditingMessageId(message.id);
    setInput(message.content);
    setError(null);
  }

  // -------------------------------------------------------------------------
  // Stop generation
  // -------------------------------------------------------------------------

  function stopGeneration() {
    abortRef.current?.abort();
  }

  // -------------------------------------------------------------------------
  // Append assistant message safely
  // -------------------------------------------------------------------------

  function appendAssistantMessageOnce(
    assistantMessage: Message
  ) {
    setMessages((prev) => {
      const alreadyExists = prev.some(
        (message) =>
          message.id === assistantMessage.id ||
          (
            message.role === "assistant" &&
            message.content.trim() ===
              assistantMessage.content.trim()
          )
      );

      if (alreadyExists) {
        return prev;
      }

      return [...prev, assistantMessage];
    });
  }

  // =========================================================================
  // SEND MESSAGE
  // =========================================================================

  async function send(
    text: string,
    convId?: string
  ) {
    const id = convId || activeId;
    const trimmedText = text.trim();

    if (!id || !trimmedText) {
      return;
    }

    // -----------------------------------------------------------------------
    // HARD REQUEST LOCK
    // -----------------------------------------------------------------------

    if (sendLockRef.current) {
      return;
    }

    sendLockRef.current = true;

    setError(null);
    setLastFailedText(null);
    setSending(true);
    setStreamingText("");

    // -----------------------------------------------------------------------
    // Add optimistic temporary user message.
    // -----------------------------------------------------------------------

    const temporaryMessageId =
      `temp-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2)}`;

    setMessages((prev) => {
      return [
        ...prev,
        {
          id: temporaryMessageId,
          role: "user",
          content: trimmedText,
          meta: null,
          created_at: new Date().toISOString(),
        },
      ];
    });

    setInput("");

    const controller = new AbortController();

    abortRef.current = controller;

    try {
      await api.streamMessage(
        id,
        trimmedText,
        {
          // -----------------------------------------------------------------
          // SSE START
          // -----------------------------------------------------------------

          onStart: (data) => {
            setMessages((prev) => {
              const withoutTemporaryMessages =
                prev.filter(
                  (message) =>
                    !message.id.startsWith("temp-")
                );

              const userMessageAlreadyExists =
                withoutTemporaryMessages.some(
                  (message) =>
                    message.id === data.user_message.id ||
                    (
                      message.role === "user" &&
                      message.content.trim() === data.user_message.content.trim() &&
                      message.created_at === data.user_message.created_at
                    )
                );

              if (userMessageAlreadyExists) {
                return withoutTemporaryMessages;
              }

              return [...withoutTemporaryMessages, data.user_message];
            });
          },

          // -----------------------------------------------------------------
          // SSE DELTA
          // -----------------------------------------------------------------

          onDelta: (chunk) => {
            if (!chunk) {
              return;
            }

            setStreamingText(
              (prev) => (prev ?? "") + chunk
            );
          },

          // -----------------------------------------------------------------
          // SSE DONE
          // -----------------------------------------------------------------

          onDone: (data) => {
            const assistantMessage =
              data.assistant_message;

            appendAssistantMessageOnce(
              assistantMessage
            );

            setStreamingText(null);
          },
        },
        controller.signal
      );

      await loadConversations();
    } catch {
      // ---------------------------------------------------------------------
      // User pressed "Stop generating".
      // ---------------------------------------------------------------------

      if (controller.signal.aborted) {
        setStreamingText(null);

        try {
          const refreshedMessages =
            await api.listMessages(id);

          setMessages(refreshedMessages);
        } catch {
          // Best effort only.
        }

        return;
      }

      // ---------------------------------------------------------------------
      // Streaming failed.
      //
      // Try regular non-streaming endpoint once.
      // ---------------------------------------------------------------------

      try {
        const resp = await api.sendMessage(
          id,
          trimmedText,
          []
        );

        setMessages((prev) => {
          const withoutTemporaryMessages =
            prev.filter(
              (message) =>
                !message.id.startsWith("temp-")
            );

          const next = [
            ...withoutTemporaryMessages,
          ];

          const userExists = next.some(
            (message) =>
              message.id === resp.user_message.id
          );

          if (!userExists) {
            next.push(resp.user_message);
          }

          const assistantExists = next.some(
            (message) =>
              message.id ===
                resp.assistant_message.id ||
              (
                message.role === "assistant" &&
                message.content.trim() ===
                  resp.assistant_message.content.trim()
              )
          );

          if (!assistantExists) {
            next.push(
              resp.assistant_message
            );
          }

          return next;
        });

        await loadConversations();
      } catch (fallbackErr) {
        setError(
          fallbackErr instanceof ApiError
            ? fallbackErr.message
            : "Failed to send message. Please try again."
        );

        setMessages((prev) =>
          prev.filter(
            (message) =>
              !message.id.startsWith("temp-")
          )
        );

        setLastFailedText(trimmedText);
      }

      setStreamingText(null);
    } finally {
      setSending(false);

      if (abortRef.current === controller) {
        abortRef.current = null;
      }

      sendLockRef.current = false;
    }
  }

  // =========================================================================
  // SUBMIT
  // =========================================================================

  async function onSubmit(
    e: React.FormEvent
  ) {
    e.preventDefault();

    // -----------------------------------------------------------------------
    // HARD DUPLICATE-SUBMIT PROTECTION
    // -----------------------------------------------------------------------

    if (sendLockRef.current || sending) {
      return;
    }

    const trimmedInput =
      input.trim();

    if (!trimmedInput) {
      return;
    }

    if (!activeId) {
      try {
        const conv =
          await api.createConversation();

        await loadConversations();

        sessionStorage.setItem(
          `draft:${conv.id}`,
          trimmedInput
        );

        setInput("");

        router.push(
          `/chat?c=${conv.id}`
        );
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not create a conversation."
        );
      }

      return;
    }

    if (editingMessageId) {
      if (!window.confirm("Replace this question and regenerate the conversation from here?")) {
        return;
      }

      try {
        const messageIndex = messages.findIndex(
          (message) => message.id === editingMessageId
        );

        await api.editMessage(activeId, editingMessageId, trimmedInput);
        setMessages(messageIndex >= 0 ? messages.slice(0, messageIndex) : []);
        setEditingMessageId(null);
        await send(trimmedInput);
      } catch (e) {
        setError(
          e instanceof ApiError ? e.message : "Could not edit the question."
        );
      }

      return;
    }

    await send(trimmedInput);
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-7.5rem)] gap-4 md:h-[calc(100vh-6rem)]">

        {/* ----------------------------------------------------------------- */}
        {/* Conversation list                                                 */}
        {/* ----------------------------------------------------------------- */}

        <div
          className={cn(
            "w-72 shrink-0 flex-col rounded-xl border border-stone-200 bg-white",
            drawerOpen
              ? "fixed inset-y-4 left-4 z-40 flex md:static"
              : "hidden md:flex"
          )}
        >
          <div className="flex items-center justify-between border-b border-stone-200 p-3">
            <Button
              size="sm"
              variant="secondary"
              onClick={newConversation}
              className="w-full justify-start"
            >
              <Plus className="h-4 w-4" />
              New conversation
            </Button>

            <button
              className="ml-2 md:hidden"
              onClick={() =>
                setDrawerOpen(false)
              }
              type="button"
              aria-label="Close conversations"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {(conversations?.length ?? 0) > 0 && (
            <div className="flex items-center justify-between gap-2 border-b border-stone-200 px-3 py-2 text-xs">
              {selectMode ? (
                <>
                  <label className="flex cursor-pointer items-center gap-2 text-stone-700">
                    <input
                      type="checkbox"
                      checked={
                        selectedIds.size > 0 &&
                        selectedIds.size === (conversations?.length ?? 0)
                      }
                      onChange={toggleSelectAll}
                      aria-label="Select all conversations"
                    />
                    Select all ({selectedIds.size})
                  </label>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={selectedIds.size === 0}
                      onClick={() => setBulkDeleteOpen(true)}
                      className="rounded-md bg-red-600 px-2 py-1 font-medium text-white disabled:opacity-40"
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      onClick={exitSelectMode}
                      className="rounded-md px-2 py-1 text-stone-600 hover:bg-stone-100"
                    >
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setSelectMode(true)}
                  className="rounded-md px-2 py-1 text-stone-600 hover:bg-stone-100"
                >
                  Select
                </button>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-2">
            {conversations?.length === 0 && (
              <p className="p-3 text-xs text-stone-400">
                No conversations yet.
              </p>
            )}

            {conversations?.map((conversation) => (
              <div
                key={conversation.id}
                className={cn(
                  "mb-1 flex items-center gap-1 rounded-lg",
                  conversation.id === activeId
                    ? "bg-stone-900 text-white"
                    : "text-stone-700 hover:bg-stone-100"
                )}
              >
                {selectMode && (
                  <input
                    type="checkbox"
                    className="ml-2 shrink-0"
                    checked={selectedIds.has(conversation.id)}
                    onChange={() => toggleSelected(conversation.id)}
                    aria-label={`Select ${conversation.title}`}
                  />
                )}
                <button
                  onClick={() => {
                    if (selectMode) {
                      toggleSelected(conversation.id);
                      return;
                    }
                    router.push(`/chat?c=${conversation.id}`);
                    setDrawerOpen(false);
                  }}
                  className="min-w-0 flex-1 truncate px-3 py-2 text-left text-sm"
                  type="button"
                  title={conversation.title}
                >
                  {conversation.title}
                </button>
                {!selectMode && (
                <button
                  onClick={() => setDeleteTarget(conversation)}
                  className={cn(
                    "mr-1 rounded-md p-1.5",
                    conversation.id === activeId
                      ? "text-white/80 hover:bg-white/10 hover:text-white"
                      : "text-stone-400 hover:bg-stone-200 hover:text-red-600"
                  )}
                  type="button"
                  title="Delete chat history"
                  aria-label={`Delete ${conversation.title}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {drawerOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/30 md:hidden"
            onClick={() =>
              setDrawerOpen(false)
            }
          />
        )}

        {/* ----------------------------------------------------------------- */}
        {/* Chat pane                                                          */}
        {/* ----------------------------------------------------------------- */}

        <div className="flex flex-1 flex-col rounded-xl border border-stone-200 bg-white">
          <div className="flex items-center gap-2 border-b border-stone-200 p-3 md:hidden">
            <button
              onClick={() =>
                setDrawerOpen(true)
              }
              type="button"
              aria-label="Open conversations"
            >
              <Menu className="h-5 w-5 text-stone-600" />
            </button>

            <span className="text-sm font-medium">
              Conversations
            </span>
          </div>

          <div className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-stone-900">
                {activeId ? (conversations?.find((item) => item.id === activeId)?.title || "AI Conversation") : "AI Chat"}
              </p>
              {shareNotice && (
                <p className="text-xs text-stone-500">{shareNotice}</p>
              )}
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!activeId || sharing}
              onClick={() => void shareConversation()}
              title="Share conversation"
            >
              <Share2 className="h-4 w-4" />
              Share
            </Button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 md:p-6">
            {!activeId && (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <p className="text-sm font-medium text-stone-900">
                  Start a new conversation
                </p>

                <p className="mt-1 max-w-xs text-sm text-stone-500">
                  Ask about an order, our policies,
                  or anything else.
                </p>

                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {SUGGESTED.map(
                    (question) => (
                      <button
                        key={question}
                        onClick={async () => {
                          try {
                            const conv =
                              await api.createConversation();

                            await loadConversations();

                            sessionStorage.setItem(
                              `draft:${conv.id}`,
                              question
                            );

                            router.push(
                              `/chat?c=${conv.id}`
                            );
                          } catch (e) {
                            setError(
                              e instanceof ApiError
                                ? e.message
                                : "Could not create a conversation."
                            );
                          }
                        }}
                        className="rounded-full border border-stone-200 px-3 py-1.5 text-xs text-stone-600 hover:bg-stone-50"
                        type="button"
                      >
                        {question}
                      </button>
                    )
                  )}
                </div>
              </div>
            )}

            {activeId && loadingMessages && (
              <div className="flex items-center justify-center py-3">
                <Spinner className="h-5 w-5 text-stone-400" />
              </div>
            )}

            {activeId &&
              !loadingMessages && (
                <div className="mx-auto max-w-2xl space-y-4">
                  {messages.map(
                    (message) => (
                      <MessageBubble
                        key={message.id}
                        message={message}
                        onEdit={startEditingMessage}
                        conversationId={activeId}
                      />
                    )
                  )}

                  {/* Streaming response */}

                  {sending &&
                    streamingText !== null &&
                    streamingText.length > 0 && (
                      <div className="flex flex-col items-start">
                        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-stone-100 px-4 py-2.5 text-sm text-stone-900">
                          {streamingText}

                          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-stone-400 align-middle" />
                        </div>
                      </div>
                    )}

                  {/* Thinking state */}

                  {sending &&
                    (!streamingText ||
                      streamingText.length ===
                        0) && (
                      <div className="flex items-center gap-2 text-sm text-stone-400">
                        <Spinner className="h-4 w-4" />
                        Thinking…
                      </div>
                    )}

                  {/* Stop generation */}

                  {sending && (
                    <button
                      onClick={
                        stopGeneration
                      }
                      className="flex items-center gap-1.5 rounded-full border border-stone-300 px-3 py-1 text-xs text-stone-600 hover:bg-stone-50"
                      type="button"
                    >
                      <Square className="h-3 w-3 fill-current" />
                      Stop generating
                    </button>
                  )}

                  {/* Retry */}

                  {lastFailedText &&
                    !sending && (
                      <button
                        onClick={() => {
                          const failedText =
                            lastFailedText;

                          setLastFailedText(
                            null
                          );

                          send(failedText);
                        }}
                        className="flex items-center gap-1.5 rounded-full border border-red-300 px-3 py-1 text-xs text-red-600 hover:bg-red-50"
                        type="button"
                      >
                        <RotateCcw className="h-3 w-3" />
                        Retry
                      </button>
                    )}

                  <div ref={bottomRef} />
                </div>
              )}
          </div>

          {/* ----------------------------------------------------------------- */}
          {/* Error                                                             */}
          {/* ----------------------------------------------------------------- */}

          {error && (
            <div className="mx-4 mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* Composer                                                          */}
          {/* ----------------------------------------------------------------- */}

          {editingMessageId && (
            <div className="flex items-center justify-between border-t border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600 md:px-4">
              <span>Editing your question. Send to regenerate from this point.</span>
              <button
                type="button"
                onClick={() => {
                  setEditingMessageId(null);
                  setInput("");
                }}
                className="font-medium text-stone-900 underline"
              >
                Cancel
              </button>
            </div>
          )}



          <form
            onSubmit={onSubmit}
            className="flex gap-2 border-t border-stone-200 p-3 md:p-4"
          >
            <input
              value={input}
              onChange={(event) =>
                setInput(event.target.value)
              }
              placeholder={
                editingMessageId
                  ? "Edit your question…"
                  : "Type your message…"
              }
              className="flex-1 rounded-lg border border-stone-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-stone-400 disabled:bg-stone-50"
              disabled={sending}
            />

            <Button
              type="submit"
              disabled={
                sending ||
                !input.trim()
              }
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      </div>

      {deleteTarget && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-conversation-title"
          onClick={() => setDeleteTarget(null)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-stone-200 bg-white p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-conversation-title" className="text-base font-semibold text-stone-900">
              Do you want to delete this conversation?
            </h2>
            <p className="mt-2 text-sm text-stone-500">
              This will permanently delete the selected conversation history.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setDeleteTarget(null)}>
                No
              </Button>
              <Button type="button" onClick={() => void deleteConversationById(deleteTarget.id)}>
                Yes, Delete
              </Button>
            </div>
          </div>
        </div>
      )}
      {bulkDeleteOpen && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="bulk-delete-title"
          onClick={() => !bulkDeleting && setBulkDeleteOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-stone-200 bg-white p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="bulk-delete-title" className="text-base font-semibold text-stone-900">
              Delete {selectedIds.size} conversation{selectedIds.size === 1 ? "" : "s"}?
            </h2>
            <p className="mt-2 text-sm text-stone-500">
              This will permanently delete the selected conversation history.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={bulkDeleting}
                onClick={() => setBulkDeleteOpen(false)}
              >
                No
              </Button>
              <Button
                type="button"
                disabled={bulkDeleting}
                onClick={() => void bulkDeleteSelected()}
              >
                {bulkDeleting ? "Deleting..." : "Yes, Delete"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

// ============================================================================
// Message Bubble
// ============================================================================

function MessageBubble({
  message,
  onEdit,
  conversationId,
}: {
  message: Message;
  onEdit: (message: Message) => void;
  conversationId: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const isUser =
    message.role === "user";

  return (
    <div
      className={cn(
        "flex flex-col",
        isUser
          ? "items-end"
          : "items-start"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm",
          isUser
            ? "bg-stone-900 text-white"
            : "bg-stone-100 text-stone-900"
        )}
      >
        {message.content}
      </div>

      <div className={cn("mt-1 flex items-center gap-1", isUser ? "justify-end" : "justify-start")}>
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(message.content);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1200);
            } catch {
              // Clipboard access may be unavailable in insecure contexts.
            }
          }}
          className="rounded-md p-1 text-stone-400 hover:bg-stone-200 hover:text-stone-700"
          title={isUser ? "Copy question" : "Copy answer"}
          aria-label={isUser ? "Copy question" : "Copy answer"}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        {isUser && !message.id.startsWith("temp-") && (
          <button
            type="button"
            onClick={() => onEdit(message)}
            className="rounded-md p-1 text-stone-400 hover:bg-stone-200 hover:text-stone-700"
            title="Edit question"
            aria-label="Edit question"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Sources */}

      {!isUser &&
        message.meta?.sources &&
        message.meta.sources.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {message.meta.sources.map(
              (source) => (
                <Link
                  key={source}
                  href={
                    conversationId
                      ? `/source-explorer?c=${encodeURIComponent(conversationId)}`
                      : "/source-explorer"
                  }
                >
                  <Badge tone="neutral">{source}</Badge>
                </Link>
              )
            )}
          </div>
        )}

      {/* Human handoff */}

      {!isUser &&
        message.meta?.handoff && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />

            <span>
              {message.meta
                .handoff_reason ||
                "A support specialist has been looped in."}
            </span>

            <Link
              href="/tickets"
              className="ml-auto flex items-center gap-1 font-medium underline"
            >
              View tickets
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        )}

      {/* Feedback */}

      {!isUser &&
        !message.id.startsWith(
          "temp-"
        ) && (
          <MessageFeedback
            messageId={message.id}
          />
        )}

      <span className="mt-1 text-[11px] text-stone-400">
        {formatDateTime(
          message.created_at
        )}
      </span>
    </div>
  );
}

// ============================================================================
// Negative feedback reasons
// ============================================================================

const NEGATIVE_REASONS: {
  value: FeedbackReason;
  label: string;
}[] = [
  {
    value: "incorrect_answer",
    label: "Incorrect answer",
  },
  {
    value: "didnt_solve_problem",
    label: "Didn't solve my problem",
  },
  {
    value: "missing_information",
    label: "Missing information",
  },
  {
    value: "needed_human",
    label: "Needed a human",
  },
  {
    value: "other",
    label: "Other",
  },
];

// ============================================================================
// Message Feedback
// ============================================================================

function MessageFeedback({
  messageId,
}: {
  messageId: string;
}) {
  const [rating, setRating] = useState<
    "positive" | "negative" | null
  >(null);

  const [askingReason, setAskingReason] =
    useState(false);

  const [suggestHandoff, setSuggestHandoff] =
    useState(false);

  const [submitting, setSubmitting] =
    useState(false);

  async function submit(
    nextRating:
      | "positive"
      | "negative",
    reason?: FeedbackReason
  ) {
    setSubmitting(true);

    try {
      const resp =
        await api.submitFeedback(
          messageId,
          {
            rating: nextRating,
            reason,
          }
        );

      setRating(
        resp.feedback.rating
      );

      setSuggestHandoff(
        resp.suggest_handoff
      );

      setAskingReason(false);
    } catch {
      // Feedback is best-effort.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-1">
        {/* Positive */}

        <button
          onClick={() =>
            submit("positive")
          }
          disabled={submitting}
          className={cn(
            "rounded-md p-1 hover:bg-stone-200 disabled:opacity-50",
            rating === "positive"
              ? "text-emerald-600"
              : "text-stone-400"
          )}
          aria-label="Helpful"
          type="button"
        >
          <ThumbsUp
            className="h-3.5 w-3.5"
            fill={
              rating === "positive"
                ? "currentColor"
                : "none"
            }
          />
        </button>

        {/* Negative */}

        <button
          onClick={() =>
            setAskingReason(
              (value) => !value
            )
          }
          disabled={submitting}
          className={cn(
            "rounded-md p-1 hover:bg-stone-200 disabled:opacity-50",
            rating === "negative"
              ? "text-red-600"
              : "text-stone-400"
          )}
          aria-label="Not helpful"
          type="button"
        >
          <ThumbsDown
            className="h-3.5 w-3.5"
            fill={
              rating === "negative"
                ? "currentColor"
                : "none"
            }
          />
        </button>
      </div>

      {/* Negative feedback reasons */}

      {askingReason && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {NEGATIVE_REASONS.map(
            (reason) => (
              <button
                key={reason.value}
                onClick={() =>
                  submit(
                    "negative",
                    reason.value
                  )
                }
                className="rounded-full border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600 hover:bg-stone-100"
                type="button"
              >
                {reason.label}
              </button>
            )
          )}
        </div>
      )}

      {/* Handoff suggestion */}

      {suggestHandoff && (
        <div className="mt-2 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />

          <span>
            Sounds like we haven&apos;t
            gotten this right. Want to
            talk to a support specialist?
          </span>

          <Link
            href="/tickets"
            className="ml-auto flex items-center gap-1 font-medium underline"
          >
            Open a ticket
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Page
// ============================================================================

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatPageInner />
    </Suspense>
  );
}