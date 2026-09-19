/**
 * Chatbot.tsx — Phase 5 React island for the portafolio RAG frontend.
 *
 * Talks to the FastAPI backend over Server-Sent Events at
 * `${PUBLIC_API_URL}/api/chat/stream-projects`. Hydrated `client:idle`
 * (configured in `index.astro`) so it doesn't block first paint.
 *
 * Decisions documented inline per the Phase 5 spec:
 *   - Hydration: `client:idle` (configured at the mount site).
 *   - History cap: last 6 user+assistant pairs (12 messages).
 *   - session_id: generated via `crypto.randomUUID()` on first mount,
 *     persisted in `sessionStorage` keyed `portafolio:session_id`.
 *   - ProjectCard in chat: small inline card mirroring the structure of
 *     `ProjectCard.astro` but limited to the SSE payload fields
 *     (slug, title, summary, relevance). Links are locale-aware
 *     (`/proyectos/<slug>/` for ES, `/en/proyectos/<slug>/` for EN).
 *   - Error UX: a retry button under the failing user message re-sends
 *     the same question via the same `sendMessage` helper.
 *   - Input UX: Enter submits, Shift+Enter inserts a newline.
 *   - Empty state: a single assistant message seeded with the
 *     `empty_message` i18n string is shown on first mount.
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
  };
}

/** Max history pairs (user+assistant). 6 pairs = 12 messages. */
const HISTORY_CAP_PAIRS = 6;
/** sessionStorage key for the per-tab session id. */
const SESSION_STORAGE_KEY = "portafolio:session_id";
/** Default backend URL when PUBLIC_API_URL is missing (mirrors .env.example). */
const FALLBACK_API_URL = "http://localhost:8000";

export default function Chatbot({ locale, strings }: ChatbotProps) {
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);

  const listRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // On mount: read or generate session_id; seed empty assistant message.
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
    setMessages([{ role: "assistant", content: strings.emptyMessage }]);
  }, [strings.emptyMessage]);

  // Abort any in-flight stream on unmount so we never call setState after teardown.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Auto-scroll the message list to the bottom on each new chunk / message.
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

  // Derived: is the trailing assistant bubble currently an error line?
  const lastMessage = messages[messages.length - 1];
  const prevMessage = messages[messages.length - 2];
  const trailingError =
    !isStreaming &&
    lastMessage?.role === "assistant" &&
    lastMessage.content.startsWith(strings.errorTitle);

  return (
    <div className="chatbot">
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
  );
}
