/**
 * Chatbot.tsx — Phase 5.5c floating navigation assistant.
 *
 * Phase 5 had this component mounted as an embedded widget on the landing
 * page only. Phase 5.5a extended the backend to accept an optional
 * `project_slug` field on every chat request, Phase 5.5b turned the widget
 * into a globally-rendered, navigation-persistent floating assistant that
 * survives Astro View Transitions, and Phase 5.5c (this file) layers a
 * first-time UX on top:
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
 *   8. (NEW 5.5c) When the visitor opens the chat for the first time — no
 *      prior user messages — the panel shows a tag-picker welcome view
 *      instead of the generic greeting. Submitting shows a filtered list of
 *      project cards; clicking one navigates to the detail page. After the
 *      first interaction a compact chip row appears above the input for
 *      quick re-trigger of any tag.
 *
 * The component's inner chat UI (messages list, form, retry, SSE handling,
 * history cap, etc.) is the same code as Phase 5/5.5b; we wrapped it in a
 * panel/FAB shell, added the persistence + URL-detection layer, and added
 * a router inside the panel body that switches between Welcome /
 * FilteredCards / ChatList views.
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

/**
 * Per-project conversation entry stored in localStorage. `projectSlug`
 * mirrors the URL context: `null` means generic (home / sobre-mi / index
 * pages) and a slug means the visitor was sitting on a project detail page.
 */
type StoredConversation = {
  projectSlug: string | null;
  messages: Message[];
};

/** Whole persisted shape: a list of conversations, one per project context. */
type StoredState = StoredConversation[];

/** Discriminated union of every SSE event the backend may emit. */
type StreamEvent =
  | { type: "content"; text: string }
  | { type: "projects"; items: ProjectCard[] }
  | { type: "done" }
  | { type: "error"; error: string; message: string };

/** Project metadata subset passed from Base.astro into the chat island. */
export type ChatProject = {
  slug: string;
  title_es: string;
  title_en: string;
  summary_es: string;
  summary_en: string;
  year: number;
  tags: string[];
};

/** Single tag + occurrence count for the picker / chips row. */
export type ChatTag = { tag: string; count: number };

interface ChatbotProps {
  locale: "es" | "en";
  /** Pre-computed in Base.astro from `getCollection('projects')`. */
  availableTags: ChatTag[];
  /** Slim project metadata for the FilteredCards view. */
  projects: ChatProject[];
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
    /** Phase 5.5c: welcome view copy. */
    welcomeGreeting: string;
    welcomeSubtitle: string;
    welcomeSubmit: string;
    welcomeSkip: string;
    /** Phase 5.5c: chip row + back button labels. */
    clearSelection: string;
    backToTags: string;
    /** Phase 5.5c: "Nueva búsqueda" affordance. Optional — falls back to
     *  a locale-aware default string if Base.astro doesn't supply them. */
    new_search?: string;
    /** ARIA label for the same button. */
    new_search_aria?: string;
  };
}

/** Max history pairs (user+assistant). 6 pairs = 12 messages. */
const HISTORY_CAP_PAIRS = 6;
/** sessionStorage key for the per-tab session id. */
const SESSION_STORAGE_KEY = "portafolio:session_id";
/**
 * localStorage key for the per-project message history (refresh survival).
 * Versioned: the previous `_messages` key held a flat `Message[]`, which
 * we don't try to migrate — bumping to `_v2` invalidates it cleanly.
 */
const STORAGE_KEY = "portafolio:chat_history_v2";
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

/** Type guard for one persisted conversation entry. */
const isValidStoredConversation = (value: unknown): value is StoredConversation => {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.projectSlug !== null && typeof v.projectSlug !== "string") return false;
  if (!Array.isArray(v.messages)) return false;
  return v.messages.every(isValidStoredMessage);
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
 * Read the conversation for `projectSlug` from localStorage, gracefully
 * degrading on parse errors, missing keys, or shape mismatches. The
 * `_v2` key holds a list of conversations; we look up the entry whose
 * `projectSlug` matches and return its messages (empty array on miss).
 */
const loadPersistedMessages = (
  projectSlug: string | null,
  emptyMessage: string,
): Message[] => {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const match = parsed.find(
      (c): c is StoredConversation =>
        isValidStoredConversation(c) && c.projectSlug === projectSlug,
    );
    if (!match) return [];
    const valid = match.messages;
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

/**
 * Write the conversation for `projectSlug`, leaving other conversations
 * intact. Empty `msgs` REMOVES the entry to keep storage tidy; a fully
 * empty list collapses to a single `removeItem` call.
 */
const persistMessages = (projectSlug: string | null, msgs: Message[]) => {
  if (typeof localStorage === "undefined") return;
  try {
    const trimmed = msgs.slice(-MESSAGES_PERSIST_CAP);
    const raw = localStorage.getItem(STORAGE_KEY);
    let list: StoredState = [];
    if (raw) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          list = parsed.filter(isValidStoredConversation);
        }
      } catch {
        // Unparseable blob: start fresh; we'll overwrite on the way out.
      }
    }
    list = list.filter((c) => c.projectSlug !== projectSlug);
    if (trimmed.length > 0) {
      list.push({ projectSlug, messages: trimmed });
    }
    if (list.length === 0) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    }
  } catch {
    // Storage quota / private-mode errors are non-fatal — we keep the
    // in-memory messages and the chat still works for this session.
  }
};

/** Drop the conversation for `projectSlug` (used on navigation / new search). */
const clearPersistedMessages = (projectSlug: string | null) => {
  if (typeof localStorage === "undefined") return;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    let list: StoredState = [];
    try {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        list = parsed.filter(isValidStoredConversation);
      }
    } catch {
      // Unparseable blob: just nuke the whole key; nothing to preserve.
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    const filtered = list.filter((c) => c.projectSlug !== projectSlug);
    if (filtered.length === 0) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
    }
  } catch {
    // Ignore — best-effort cleanup.
  }
};

/** Locale-aware project detail URL. ES: `/proyectos/<slug>/`. EN: `/en/proyectos/<slug>/`. */
const projectHref = (locale: "es" | "en", slug: string): string =>
  locale === "en" ? `/en/proyectos/${slug}/` : `/proyectos/${slug}/`;

/**
 * Compact project card used inside the FilteredProjectsView. Smaller than
 * the public `ProjectCard.astro` (no image / role / impact — just enough to
 * nudge the visitor to the detail page).
 */
function ChatProjectCard({
  project,
  locale,
}: {
  project: ChatProject;
  locale: "es" | "en";
}) {
  const title = locale === "en" ? project.title_en : project.title_es;
  const summary = locale === "en" ? project.summary_en : project.summary_es;
  return (
    <a className="chatbot-projects-card" href={projectHref(locale, project.slug)}>
      <h4 className="chatbot-projects-card-title">{title}</h4>
      <p className="chatbot-projects-card-year">{project.year}</p>
      <p className="chatbot-projects-card-summary">{summary}</p>
      {project.tags.length > 0 && (
        <div className="chatbot-projects-card-tags">
          {project.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="chatbot-projects-card-tag">
              {tag}
            </span>
          ))}
        </div>
      )}
    </a>
  );
}

/**
 * First-time UX: greeting + multi-select tag pills with occurrence counts
 * + a primary submit button + a secondary skip link that drops the visitor
 * into the chat view. Submitting transitions to FilteredProjectsView.
 */
function WelcomeView({
  availableTags,
  selectedTags,
  onToggleTag,
  onSubmit,
  onSkip,
  strings,
}: {
  availableTags: ChatTag[];
  selectedTags: Set<string>;
  onToggleTag: (tag: string) => void;
  onSubmit: () => void;
  onSkip: () => void;
  strings: ChatbotProps["strings"];
}) {
  return (
    <div className="chatbot-welcome">
      <h3 className="chatbot-welcome-greeting">{strings.welcomeGreeting}</h3>
      <p className="chatbot-welcome-subtitle">{strings.welcomeSubtitle}</p>
      <div className="chatbot-welcome-tags" role="group" aria-label={strings.welcomeSubtitle}>
        {availableTags.map(({ tag, count }) => {
          const selected = selectedTags.has(tag);
          return (
            <button
              key={tag}
              type="button"
              className={`chatbot-welcome-tag${selected ? " chatbot-welcome-tag--selected" : ""}`}
              aria-pressed={selected}
              onClick={() => onToggleTag(tag)}
            >
              <span>{tag}</span>
              <span className="chatbot-welcome-tag-count" aria-hidden="true">
                · {count}
              </span>
            </button>
          );
        })}
      </div>
      <div className="chatbot-welcome-actions">
        <button
          type="button"
          className="chatbot-welcome-submit"
          onClick={onSubmit}
          disabled={selectedTags.size === 0}
        >
          {strings.welcomeSubmit}
        </button>
        <button type="button" className="chatbot-welcome-skip" onClick={onSkip}>
          {strings.welcomeSkip}
        </button>
      </div>
    </div>
  );
}

/**
 * Filtered project cards view. Shows every project whose tags include ALL
 * of the visitor's selected tags. The header doubles as a "back" affordance
 * so the visitor can tweak their selection without losing it.
 */
function FilteredProjectsView({
  projects,
  locale,
  strings,
  selectedTagCount,
  onBack,
}: {
  projects: ChatProject[];
  locale: "es" | "en";
  strings: ChatbotProps["strings"];
  selectedTagCount: number;
  onBack: () => void;
}) {
  return (
    <>
      <button type="button" className="chatbot-back-button" onClick={onBack}>
        ← {strings.backToTags}
      </button>
      <div className="chatbot-projects-header">
        {projects.length} {projects.length === 1 ? "proyecto" : "proyectos"}
        {selectedTagCount > 0 && (
          <>
            {" "}
            · {selectedTagCount}{" "}
            {selectedTagCount === 1 ? "stack" : "stacks"}
          </>
        )}
      </div>
      <div className="chatbot-projects-list">
        {projects.length === 0 ? (
          <p className="chatbot-projects-empty">{strings.emptyMessage}</p>
        ) : (
          projects.map((p) => (
            <ChatProjectCard key={p.slug} project={p} locale={locale} />
          ))
        )}
      </div>
    </>
  );
}

/**
 * Compact chip row shown above the chat input after the first interaction.
 * Multi-select: each click toggles a tag in `selectedTags`. The "clear"
 * link resets the selection. `onChipActivate` lets the parent decide what
 * a tag-click does once the user has a free-form input available; we use
 * it to pre-fill the input without auto-sending.
 */
function ChatChipsRow({
  availableTags,
  selectedTags,
  onToggleTag,
  onClear,
  onChipActivate,
  strings,
}: {
  availableTags: ChatTag[];
  selectedTags: Set<string>;
  onToggleTag: (tag: string) => void;
  onClear: () => void;
  onChipActivate: (tag: string) => void;
  strings: ChatbotProps["strings"];
}) {
  return (
    <div className="chatbot-chips-row" role="group" aria-label="Stacks">
      {availableTags.map(({ tag }) => {
        const selected = selectedTags.has(tag);
        return (
          <button
            key={tag}
            type="button"
            className={`chatbot-chip${selected ? " chatbot-chip--selected" : ""}`}
            aria-pressed={selected}
            onClick={() => {
              onToggleTag(tag);
              onChipActivate(tag);
            }}
          >
            {tag}
          </button>
        );
      })}
      {selectedTags.size > 0 && (
        <button type="button" className="chatbot-chip-clear" onClick={onClear}>
          {strings.clearSelection}
        </button>
      )}
    </div>
  );
}

export default function Chatbot({ locale, availableTags, projects, strings }: ChatbotProps) {
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

  // -- Phase 5.5c: tag-picker state -------------------------------------------
  // `selectedTags` powers both the welcome-view multi-select pills and the
  // compact chip row above the input. `showFilteredCards` flips the panel
  // body to render the FilteredProjectsView after the visitor submits on
  // the welcome screen. `welcomeDismissed` tracks the skip path so the
  // visitor can type their own question instead of picking tags.
  const [selectedTags, setSelectedTags] = useState<Set<string>>(() => new Set());
  const [showFilteredCards, setShowFilteredCards] = useState<boolean>(false);
  const [welcomeDismissed, setWelcomeDismissed] = useState<boolean>(false);

  // "First interaction" = the visitor has sent at least one user message.
  // The seeded empty-state assistant line does not count, otherwise the
  // welcome view would never appear.
  const hasInteracted = messages.some((m) => m.role === "user");

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

    // Initial project slug from the URL — rehydration targets THIS project
    // context so a refresh on a project page restores its conversation.
    const initialSlug = extractProjectSlug(window.location.pathname);
    setProjectSlug(initialSlug);

    // Rehydrate messages for the initial project context. Empty array
    // means "no prior conversation for this slug" — we seed the empty-state
    // assistant line so the chat never opens blank.
    const persisted = loadPersistedMessages(initialSlug, strings.emptyMessage);
    if (persisted.length > 0) {
      setMessages(persisted);
    } else {
      setMessages([{ role: "assistant", content: strings.emptyMessage }]);
    }
    setHasRehydrated(true);
  }, [strings.emptyMessage]);

  // -- Re-detect project slug on every Astro View Transitions navigation ------
  // When the URL moves between project contexts (e.g. /proyectos/proj-a/ →
  // /proyectos/proj-b/, or any of those → /), drop the previous project's
  // conversation: the chat becomes project-scoped. `session_id` is NOT
  // touched — a long tab is one continuous conversation from the backend's
  // POV, only the in-message history is ephemeral per project.
  useEffect(() => {
    const onPageLoad = () => {
      const newSlug = extractProjectSlug(window.location.pathname);
      setProjectSlug((prev) => {
        if (newSlug !== prev) {
          // Project context changed: clear chat and persisted conversation.
          setMessages([{ role: "assistant", content: strings.emptyMessage }]);
          setSelectedTags(new Set());
          setShowFilteredCards(false);
          setWelcomeDismissed(false);
          setInput("");
          setLastFailedQuestion(null);
          // Drop the OLD conversation (not the new one) so storage reflects
          // the visitor's actual path. The new slug gets re-seeded on the
          // next persistMessages cycle.
          clearPersistedMessages(prev);
        }
        return newSlug;
      });
    };
    // astro:page-load fires after every Astro navigation (including the
    // very first page load). Run once on mount to pick up the initial
    // project slug, then listen for View Transitions navigations.
    onPageLoad();
    document.addEventListener("astro:page-load", onPageLoad);
    return () => document.removeEventListener("astro:page-load", onPageLoad);
  }, [strings.emptyMessage]);

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
    persistMessages(projectSlug, messages);
  }, [messages, projectSlug, hasRehydrated]);

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

  const closePanel = () => setIsPanelOpen(false);
  const togglePanel = () => setIsPanelOpen((prev) => !prev);

  /**
   * Reset the chat to its first-time UX without changing the URL. Used by
   * the "Nueva búsqueda" affordance so a visitor sitting on a project page
   * can pivot to a different topic / set of tags without navigating away.
   * Mirrors the navigation cleanup (project change) but skips the project
   * slug step — we're staying on the same page.
   */
  const handleNewSearch = () => {
    setMessages([{ role: "assistant", content: strings.emptyMessage }]);
    setSelectedTags(new Set());
    setShowFilteredCards(false);
    setWelcomeDismissed(false);
    setInput("");
    setLastFailedQuestion(null);
    // Also clear localStorage for the current project: each search is
    // ephemeral — we don't retain the previous query.
    clearPersistedMessages(projectSlug);
  };

  // Locale-aware fallback for the optional i18n keys. Keeping these here
  // (instead of forcing Base.astro to pass them) means existing layouts
  // don't need to be edited to ship the new button.
  const newSearchLabel =
    strings.new_search ?? (locale === "en" ? "New search" : "Nueva búsqueda");
  const newSearchAria =
    strings.new_search_aria ?? (locale === "en" ? "Start new search" : "Iniciar nueva búsqueda");

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
          <div className="chatbot-panel-actions">
            {hasInteracted && (
              <button
                type="button"
                className="chatbot-new-search"
                onClick={handleNewSearch}
                aria-label={newSearchAria}
                title={newSearchAria}
              >
                ↻ {newSearchLabel}
              </button>
            )}
            <button
              type="button"
              className="chatbot-panel-close"
              onClick={closePanel}
              aria-label={strings.closeChatAria}
            >
              ×
            </button>
          </div>
        </header>
        <div className="chatbot-panel-body">
          {(() => {
            // Phase 5.5c: pick one of three views for the panel body.
            //   1. FilteredCards — after the visitor submits on the welcome view.
            //   2. Welcome       — first time, no prior user messages, not yet dismissed.
            //   3. ChatList      — everything else (existing UI plus chips row).
            if (showFilteredCards) {
              const tagFilter = Array.from(selectedTags);
              const matched = projects.filter((p) =>
                tagFilter.every((t) => p.tags.includes(t)),
              );
              return (
                <FilteredProjectsView
                  projects={matched}
                  locale={locale}
                  strings={strings}
                  selectedTagCount={tagFilter.length}
                  onBack={() => setShowFilteredCards(false)}
                />
              );
            }
            if (!hasInteracted && !welcomeDismissed) {
              return (
                <WelcomeView
                  availableTags={availableTags}
                  selectedTags={selectedTags}
                  onToggleTag={(tag) => {
                    const next = new Set(selectedTags);
                    if (next.has(tag)) {
                      next.delete(tag);
                    } else {
                      next.add(tag);
                    }
                    setSelectedTags(next);
                  }}
                  onSubmit={() => setShowFilteredCards(true)}
                  onSkip={() => setWelcomeDismissed(true)}
                  strings={strings}
                />
              );
            }
            return (
              <>
                <ChatChipsRow
                  availableTags={availableTags}
                  selectedTags={selectedTags}
                  onToggleTag={(tag) => {
                    const next = new Set(selectedTags);
                    if (next.has(tag)) {
                      next.delete(tag);
                    } else {
                      next.add(tag);
                    }
                    setSelectedTags(next);
                  }}
                  onClear={() => setSelectedTags(new Set())}
                  onChipActivate={(tag) => setInput(tag)}
                  strings={strings}
                />
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
                                  href={projectHref(locale, p.slug)}
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
              </>
            );
          })()}
        </div>
      </aside>
    </div>
  );
}