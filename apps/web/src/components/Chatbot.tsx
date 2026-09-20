/**
 * Chatbot.tsx — Phase 5.5b floating navigation assistant.
 *
 * Phase 5 had this component mounted as an embedded widget on the landing
 * page only. Phase 5.5a extended the backend to accept an optional
 * `project_slug` field on every chat request, and Phase 5.5b (this file)
 * turns the widget into a globally-rendered, navigation-persistent
 * floating assistant that:
 *
 *   1. Renders as a FAB bottom-right on every page (it lives in Base.astro).
 *   2. Slides in a side panel when the FAB is clicked.
 *   3. Survives Astro View Transitions navigations because Base.astro mounts
 *      it under the `transition:persist` directive — the React island's
 *      DOM nodes and React state are preserved across page changes.
 *   4. Auto-detects the active project slug from `window.location.pathname`
 *      and re-detects on every `astro:page-load` event, so the chat knows
 *      which project the visitor is browsing.
 *   5. Sends that `project_slug` (or `null`) on every chat request so the
 *      backend can bias retrieval toward the current project.
 *   6. Closes on backdrop click or ESC.
 *   7. Persists `messages` to localStorage (hard refresh survival) and
 *      `session_id` to sessionStorage (per-tab persistence).
 *
 * The component's inner chat UI (messages list, form, retry, project cards,
 * SSE handling, history cap, etc.) is the same code as Phase 5; we wrapped it
 * in a panel/FAB shell and added the persistence + URL-detection layer.
 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import "./Chatbot.css";

type ProjectCard = {
  slug: string;
  title: string;
  summary: string;
  relevance: number;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  projects?: ProjectCard[];
};

/** Discriminated union of every SSE event the backend may emit. */
type StreamEvent =
  | { type: "content"; text: string }
  | { type: "projects"; items: ProjectCard[] }
  | { type: "done" }
  | { type: "error"; error: string; message: string };

interface ChatbotProps {
  locale: "es" | "en";
  strings: {
    inputPlaceholder: string;
    send: string;
    thinking: string;
    errorTitle: string;
    errorRetry: string;
    cardView: string;
    emptyMessage: string;
    /** Title shown in the panel header. */
    assistantTitle: string;
    /** ARIA label for the FAB button when the panel is closed. */
    openChatAria: string;
    /** ARIA label for the close button (FAB or panel header button). */
    closeChatAria: string;
  };
}

/** Max history pairs (user+assistant). 6 pairs = 12 messages. */
const HISTORY_CAP_PAIRS = 6;
/** sessionStorage key for the per-tab session id. */
const SESSION_STORAGE_KEY = "portafolio:session_id";
/** localStorage key for the message history (refresh survival). */
const MESSAGES_STORAGE_KEY = "portafolio:chat_messages";
/** Cap how many messages we keep in localStorage to avoid bloating it. */
const MESSAGES_PERSIST_CAP = 30;
/** Default backend URL when PUBLIC_API_URL is missing (mirrors .env.example). */
const FALLBACK_API_URL = "http://localhost:8000";

/** Type guard used when rehydrating messages from localStorage. */
const isValidStoredMessage = (value: unknown): value is Message => {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.role !== "user" && v.role !== "assistant") return false;
  if (typeof v.content !== "string") return false;
  if (v.projects !== undefined && !Array.isArray(v.projects)) return false;
  return true;
};

/** Build the empty-state assistant line. Defined as a constant factory so the
 *  `Message` type flows through `loadPersistedMessages` cleanly. */
const emptyMessageSeed = (emptyMessage: string): Message => ({
  role: "assistant",
  content: emptyMessage,
});

/** Pull the project slug from a pathname like `/proyectos/proj-cloud-migration/`. */
const extractProjectSlug = (pathname: string): string | null => {
  const match = pathname.match(/\/(?:en\/)?proyectos\/(proj-[a-z0-9-]+)\/?/);
  return match ? match[1] : null;
};

/**
 * Read messages from localStorage, gracefully degrading on parse errors or
 * missing keys. We intentionally accept an empty array back so callers can
 * fall back to seeding the empty-state assistant line.
 */
const loadPersistedMessages = (emptyMessage: string): Message[] => {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(MESSAGES_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const valid: Message[] = parsed.filter(isValidStoredMessage);
    if (valid.length === 0) return [];
    // Ensure the first message is the empty-state assistant line; if it
    // somehow got stripped (corruption / older schema), prepend it so the
    // chat never opens with the user greeting the bot to silence.
    if (valid[0].role !== "assistant" || valid[0].content !== emptyMessage) {
      return [emptyMessageSeed(emptyMessage), ...valid].slice(-MESSAGES_PERSIST_CAP);
    }
    return valid.slice(-MESSAGES_PERSIST_CAP);
  } catch {
    return [];
  }
};

/** Write messages to localStorage, dropping the cap. */
const persistMessages = (msgs: Message[]) => {
  if (typeof localStorage === "undefined") return;
  try {
    const trimmed = msgs.slice(-MESSAGES_PERSIST_CAP);
    localStorage.setItem(MESSAGES_STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // Storage quota / private-mode errors are non-fatal — we keep the
    // in-memory messages and the chat still works for this session.
  }
};

export default function Chatbot({ locale, strings }: ChatbotProps) {
  // -- UI state (panel vs. FAB) -------------------------------------------------
  const [isPanelOpen, setIsPanelOpen] = useState<boolean>(false);

  // -- URL-derived context -----------------------------------------------------
  const [projectSlug, setProjectSlug] = useState<string | null>(null);

  // -- Chat state (unchanged from Phase 5) --------------------------------------
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);
  // Track whether the initial mount rehydration has happened so we don't
  // re-seed the empty-state line on every View Transitions rehydration.
  const [hasRehydrated, setHasRehydrated] = useState<boolean>(false);

  const listRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // -- Mount: session_id, rehydrated history, initial project slug --------------
  useEffect(() => {
    let id = "";
    try {
      id = sessionStorage.getItem(SESSION_STORAGE_KEY) ?? "";
    } catch {
      // sessionStorage can be unavailable in private mode / strict storage
      // settings; fall through and just hold an in-memory id for this tab.
    }
    if (!id) {
      id =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      try {
        sessionStorage.setItem(SESSION_STORAGE_KEY, id);
      } catch {
        // Persistence is best-effort; in-memory id is enough for this session.
      }
    }
    setSessionId(id);

    // Rehydrate messages from localStorage if present; otherwise seed the
    // empty-state assistant line so the chat never opens blank.
    const persisted = loadPersistedMessages(strings.emptyMessage);
    if (persisted.length > 0) {
      setMessages(persisted);
    } else {
      setMessages([{ role: "assistant", content: strings.emptyMessage }]);
    }
    setHasRehydrated(true);

    // Initial project slug from the URL (no SPA navigation has happened yet).
    setProjectSlug(extractProjectSlug(window.location.pathname));
  }, [strings.emptyMessage]);

  // -- Re-detect project slug on every Astro View Transitions navigation ------
  useEffect(() => {
    const detectProject = () => {
      setProjectSlug(extractProjectSlug(window.location.pathname));
    };
    // astro:page-load fires after every Astro navigation (including the very
    // first page load). This is the supported hook for View Transitions
    // integrations.
    document.addEventListener("astro:page-load", detectProject);
    return () => document.removeEventListener("astro:page-load", detectProject);
  }, []);

  // -- Body scroll lock + ESC to close -----------------------------------------
  useEffect(() => {
    if (!isPanelOpen) return;

    // Lock background scroll on mobile so the panel feels app-like.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsPanelOpen(false);
      }
    };
    document.addEventListener("keydown", handleKey);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
    };
  }, [isPanelOpen]);

  // -- Persist messages to localStorage whenever they change -------------------
  useEffect(() => {
    // Skip the first render before mount has rehydrated/seeded anything; we
    // don't want to overwrite localStorage with a transient empty array.
    if (!hasRehydrated) return;
    persistMessages(messages);
  }, [messages, hasRehydrated]);

  // -- Abort any in-flight stream on unmount so we never setState after teardown.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // -- Auto-scroll the message list to the bottom on each new chunk / message.
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  /**
   * Build the conversation history for the next request: drop the seeded
   * empty-state line, drop empty assistant placeholders, then cap to the
   * last N user+assistant pairs. The new question is sent separately in
   * `question`, so the history is "everything that happened before this turn".
   */
  const buildHistory = (allMessages: Message[]) => {
    const cleaned = allMessages.filter(
      (m) =>
        m.content !== "" &&
        !(m.role === "assistant" && m.content === strings.emptyMessage),
    );
    const capped = cleaned.slice(-HISTORY_CAP_PAIRS * 2);
    return capped.map(({ role, content }) => ({ role, content }));
  };

  /** Replace the trailing assistant message with a user-facing error line. */
  const failLastAssistant = (errorMessage: string) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last.role !== "assistant") return prev;
      next[next.length - 1] = {
        ...last,
        content: `${strings.errorTitle}: ${errorMessage}`,
      };
      return next;
    });
  };

  /**
   * Send a message (or resend a previously failed question via retry).
   * Centralized so the retry button and the form submit both go through
   * the same streaming pipeline.
   */
  const sendMessage = async (rawText: string) => {
    const text = rawText.trim();
    if (!text || isStreaming || !sessionId) return;

    // Append user message + a fresh empty assistant bubble that we'll fill
    // from SSE events. We snapshot the previous messages *before* this
    // append so history reflects "everything before this turn".
    const previousMessages = messages;
    const userMsg: Message = { role: "user", content: text };
    const placeholder: Message = { role: "assistant", content: "" };
    setMessages([...previousMessages, userMsg, placeholder]);
    setInput("");
    setIsStreaming(true);
    setLastFailedQuestion(text);

    const history = buildHistory(previousMessages);
    const apiUrl =
      (import.meta.env.PUBLIC_API_URL as string | undefined) ?? FALLBACK_API_URL;

    const controller = new AbortController();
    abortRef.current = controller;

    /**
     * Apply a single SSE event to the trailing assistant message.
     * `done` and `error` events also flip streaming flags here.
     */
    const processEvent = (parsed: StreamEvent) => {
      if (parsed.type === "done") {
        setIsStreaming(false);
        setLastFailedQuestion(null);
        return;
      }
      if (parsed.type === "error") {
        failLastAssistant(parsed.message || parsed.error || "Unknown error");
        setIsStreaming(false);
        // Keep lastFailedQuestion set so the retry button stays visible.
        return;
      }
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        const last = next[next.length - 1];
        if (last.role !== "assistant") return prev;
        if (parsed.type === "content") {
          next[next.length - 1] = {
            ...last,
            content: last.content + parsed.text,
          };
        } else if (parsed.type === "projects") {
          next[next.length - 1] = {
            ...last,
            projects: parsed.items,
          };
        }
        return next;
      });
    };

    try {
      const response = await fetch(`${apiUrl}/api/chat/stream-projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          question: text,
          lang: locale,
          session_id: sessionId,
          history,
          // Phase 5.5a: optional project context hint. Null when not on a
          // project page; the backend treats it as "no preference".
          project_slug: projectSlug,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // SSE wire format: events separated by a blank line (`\n\n`); each
      // event is one or more `field: value` lines (we only consume `data:`).
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const rawEvent = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of rawEvent.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try {
              processEvent(JSON.parse(payload) as StreamEvent);
            } catch {
              // Skip malformed payloads; the stream may contain keep-alive
              // comments or partial JSON before the next event arrives.
            }
          }
          sep = buffer.indexOf("\n\n");
        }
      }

      // Drain any trailing bytes that didn't end with \n\n.
      if (buffer.trim()) {
        for (const line of buffer.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            processEvent(JSON.parse(payload) as StreamEvent);
          } catch {
            /* ignore */
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      failLastAssistant((err as Error).message || "Network error");
      setIsStreaming(false);
      // Keep lastFailedQuestion set so the retry button stays visible.
    } finally {
      abortRef.current = null;
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    void sendMessage(input);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter submits, Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  };

  const projectHref = (slug: string) =>
    locale === "en" ? `/en/proyectos/${slug}/` : `/proyectos/${slug}/`;

  const closePanel = () => setIsPanelOpen(false);
  const togglePanel = () => setIsPanelOpen((prev) => !prev);

  // Derived: is the trailing assistant bubble currently an error line?
  const lastMessage = messages[messages.length - 1];
  const trailingError =
    !isStreaming &&
    lastMessage?.role === "assistant" &&
    lastMessage.content.startsWith(strings.errorTitle);

  return (
    <div className="chatbot-fab-wrapper">
      {/* Backdrop: dark overlay behind the panel; click to close. */}
      {isPanelOpen && (
        <div
          className="chatbot-backdrop"
          onClick={closePanel}
          aria-hidden="true"
        />
      )}

      {/* Floating Action Button. Stays visible when the panel is open
          (Intercom-style) but its icon flips to a close glyph and its
          aria-label changes, so screen readers announce it as "close". */}
      <button
        type="button"
        className="chatbot-fab"
        onClick={togglePanel}
        aria-label={isPanelOpen ? strings.closeChatAria : strings.openChatAria}
        aria-expanded={isPanelOpen}
        aria-controls="chatbot-panel"
      >
        {isPanelOpen ? (
          // Close glyph — simple × rendered with CSS so we don't pull in
          // an icon dependency for two glyphs.
          <span className="chatbot-fab__icon chatbot-fab__icon--close" aria-hidden="true">
            ×
          </span>
        ) : (
          // Chat glyph — speech-bubble Unicode so we don't need an SVG.
          <span className="chatbot-fab__icon chatbot-fab__icon--chat" aria-hidden="true">
            💬
          </span>
        )}
      </button>

      {/* Slide-in side panel. */}
      <aside
        id="chatbot-panel"
        className="chatbot-panel"
        role="complementary"
        aria-label={strings.assistantTitle}
        aria-hidden={!isPanelOpen}
      >
        <header className="chatbot-panel-header">
          <h2 className="chatbot-panel-title">{strings.assistantTitle}</h2>
          <button
            type="button"
            className="chatbot-panel-close"
            onClick={closePanel}
            aria-label={strings.closeChatAria}
          >
            ×
          </button>
        </header>
        <div className="chatbot-panel-body">
          <div className="chatbot-list" ref={listRef}>
            {messages.map((msg, idx) => {
              const isUser = msg.role === "user";
              const showRetry =
                isUser &&
                lastFailedQuestion === msg.content &&
                trailingError &&
                idx === messages.length - 2;
              return (
                <div
                  key={idx}
                  className={`chatbot-row chatbot-row--${msg.role}`}
                >
                  <div className={`chatbot-bubble chatbot-bubble--${msg.role}`}>
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                    {msg.projects && msg.projects.length > 0 && (
                      <div className="chatbot-cards">
                        {msg.projects.map((p) => (
                          <a
                            key={p.slug}
                            className="chatbot-card"
                            href={projectHref(p.slug)}
                          >
                            <h4 className="chatbot-card__title">{p.title}</h4>
                            <p className="chatbot-card__summary">{p.summary}</p>
                            <span className="chatbot-card__cta">
                              {strings.cardView} →
                            </span>
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                  {showRetry && (
                    <button
                      type="button"
                      className="chatbot-retry"
                      onClick={() => void sendMessage(msg.content)}
                      disabled={isStreaming}
                    >
                      {strings.errorRetry}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <form className="chatbot-form" onSubmit={handleSubmit}>
            <textarea
              className="chatbot-input"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={strings.inputPlaceholder}
              disabled={isStreaming}
              aria-label={strings.inputPlaceholder}
            />
            <button
              type="submit"
              className="chatbot-send"
              disabled={isStreaming || input.trim() === ""}
            >
              {strings.send}
            </button>
            {isStreaming && (
              <span className="chatbot-thinking" aria-live="polite">
                {strings.thinking}
              </span>
            )}
          </form>
        </div>
      </aside>
    </div>
  );
}