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
    /** Onboarding tutorial modal copy. All optional so older layouts that
     *  don't supply them still compile — the modal stays closed. */
    tutorialBadge?: string;
    tutorialTitle?: string;
    tutorialSub?: string;
    tutorialStep1Title?: string;
    tutorialStep1Desc?: string;
    tutorialStep2Title?: string;
    tutorialStep2Desc?: string;
    tutorialStep3Title?: string;
    tutorialStep3Desc?: string;
    tutorialNoShow?: string;
    tutorialStartChat?: string;
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

  // -- Onboarding tutorial modal state -----------------------------------------
  // `tutorialOpen` flips the overlay on after a 600ms delay (so the page
  // settles before we obscure it). `tutorialNoShow` mirrors the "don't show
  // again" checkbox; it's the only thing that persists to localStorage.
  const [tutorialOpen, setTutorialOpen] = useState<boolean>(false);
  const [tutorialNoShow, setTutorialNoShow] = useState<boolean>(false);

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

  // -- Onboarding tutorial: show once on first visit ---------------------------
  // We read a single localStorage flag and, if the visitor hasn't dismissed
  // it with "don't show again", pop the modal after 600ms so the page has
  // time to settle. Empty deps: re-running on prop changes would let a
  // language flip re-trigger the modal every time, which would be hostile.
  useEffect(() => {
    let alreadySeen = false;
    try {
      alreadySeen = localStorage.getItem("portafolio:chat_tutorial_seen") === "1";
    } catch {
      // localStorage may throw in private mode; treat as "not seen" so the
      // modal still appears at least once during this session.
    }
    if (alreadySeen) return;
    const timer = window.setTimeout(() => {
      setTutorialOpen(true);
    }, 600);
    return () => window.clearTimeout(timer);
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

  // Tutorial copy fallbacks. Same idea: optional i18n keys so older
  // layouts compile, but every new key has a sensible locale default so
  // the modal still renders if a layout hasn't been updated yet.
  const tutorialCopy = {
    badge: strings.tutorialBadge ?? (locale === "en" ? "Welcome" : "Bienvenida"),
    title: strings.tutorialTitle ?? (locale === "en"
      ? "Your portfolio, in <em>conversation</em>."
      : "Tu portafolio, en <em>conversación</em>."),
    sub: strings.tutorialSub ?? (locale === "en"
      ? "The editor answers questions about the indexed projects — by stack, domain or idea. Open the chat and try it out."
      : "El editor responde preguntas sobre los proyectos indexados — por stack, dominio o idea. Abrí el chat y probá."),
    step1Title: strings.tutorialStep1Title ?? (locale === "en" ? "Open the chat" : "Abrí el chat"),
    step1Desc: strings.tutorialStep1Desc ?? (locale === "en"
      ? "Tap the <strong>blue</strong> button at the bottom-right, or the <strong>«Ask the bot»</strong> button on the homepage."
      : "Tocá el botón <strong>azul</strong> abajo a la derecha, o el botón <strong>«Preguntale al bot»</strong> en la portada."),
    step2Title: strings.tutorialStep2Title ?? (locale === "en" ? "Ask anything" : "Preguntá lo que quieras"),
    step2Desc: strings.tutorialStep2Desc ?? (locale === "en"
      ? "By stack (<code>python</code>, <code>aws</code>), domain (<code>data</code>) or idea (<code>side projects</code>)."
      : "Por stack (<code>python</code>, <code>aws</code>), dominio (<code>data</code>) o idea (<code>side projects</code>)."),
    step3Title: strings.tutorialStep3Title ?? (locale === "en" ? "Get prose + reviews" : "Recibí prosa + reseñas"),
    step3Desc: strings.tutorialStep3Desc ?? (locale === "en"
      ? "The editor returns a response and, if there's a match, a list of projects with links to detail pages."
      : "El editor devuelve una respuesta y, si hay match, una lista de proyectos con enlace a la página de detalle."),
    noShow: strings.tutorialNoShow ?? (locale === "en" ? "Don't show again" : "No mostrar de nuevo"),
    startChat: strings.tutorialStartChat ?? (locale === "en" ? "Start chatting" : "Empezar a chatear"),
  };

  /** Close the tutorial overlay. Persist the "don't show again" choice ONLY
   *  when the checkbox was checked — otherwise the modal reappears on the
   *  next visit (intentional: dismissals without a flag are treated as
   *  "not ready", so the visitor can't permanently ignore the tutorial). */
  const dismissTutorial = () => {
    setTutorialOpen(false);
    if (tutorialNoShow) {
      try {
        localStorage.setItem("portafolio:chat_tutorial_seen", "1");
      } catch {
        // Private-mode storage errors are non-fatal.
      }
    }
  };

  /** Toggle the "don't show again" checkbox. Checking it persists the flag
   *  immediately so a future refresh skips the modal — the visitor doesn't
   *  have to dismiss twice for their choice to stick. */
  const handleTutorialNoShowChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    setTutorialNoShow(checked);
    if (checked) {
      try {
        localStorage.setItem("portafolio:chat_tutorial_seen", "1");
      } catch {
        // Private-mode storage errors are non-fatal.
      }
    }
  };

  // Derived: is the trailing assistant bubble currently an error line?
  const lastMessage = messages[messages.length - 1];
  const trailingError =
    !isStreaming &&
    lastMessage?.role === "assistant" &&
    lastMessage.content.startsWith(strings.errorTitle);

  return (
    <div className="chatbot-fab-wrapper">
      {/*
        Onboarding tutorial modal. Mounted as a sibling of the FAB wrapper
        so it covers the whole viewport without disturbing the FAB/panel
        state machine. The CSS in Chatbot.css handles the slide-in,
        backdrop blur, and `body:has(.chatbot-tutorial--visible) { overflow:
        hidden }` scroll lock, so we don't add any inline styles.
      */}
      <div
        className={`chatbot-tutorial${tutorialOpen ? " chatbot-tutorial--visible" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chatbot-tutorial-title"
        aria-describedby="chatbot-tutorial-sub"
        aria-hidden={!tutorialOpen}
      >
        <div className="chatbot-tutorial__panel">
          <header className="chatbot-tutorial__header">
            <span className="chatbot-tutorial__badge">
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
              </svg>
              {tutorialCopy.badge}
            </span>
            <h2
              id="chatbot-tutorial-title"
              className="chatbot-tutorial__title"
              dangerouslySetInnerHTML={{ __html: tutorialCopy.title }}
            />
            <p id="chatbot-tutorial-sub" className="chatbot-tutorial__sub">
              {tutorialCopy.sub}
            </p>
          </header>

          <ol className="chatbot-tutorial__steps">
            <li className="chatbot-tutorial__step">
              <span className="chatbot-tutorial__stepIcon" aria-hidden="true">
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                  <polyline points="10 17 15 12 10 7" />
                  <line x1="15" y1="12" x2="3" y2="12" />
                </svg>
              </span>
              <h3 className="chatbot-tutorial__stepTitle">{tutorialCopy.step1Title}</h3>
              <p
                className="chatbot-tutorial__stepDesc"
                dangerouslySetInnerHTML={{ __html: tutorialCopy.step1Desc }}
              />
            </li>
            <li className="chatbot-tutorial__step">
              <span className="chatbot-tutorial__stepIcon" aria-hidden="true">
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </span>
              <h3 className="chatbot-tutorial__stepTitle">{tutorialCopy.step2Title}</h3>
              <p
                className="chatbot-tutorial__stepDesc"
                dangerouslySetInnerHTML={{ __html: tutorialCopy.step2Desc }}
              />
            </li>
            <li className="chatbot-tutorial__step">
              <span className="chatbot-tutorial__stepIcon" aria-hidden="true">
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="9" y1="13" x2="15" y2="13" />
                  <line x1="9" y1="17" x2="13" y2="17" />
                </svg>
              </span>
              <h3 className="chatbot-tutorial__stepTitle">{tutorialCopy.step3Title}</h3>
              <p className="chatbot-tutorial__stepDesc">{tutorialCopy.step3Desc}</p>
            </li>
          </ol>

          {/*
            Decorative preview block — mirrors what the visitor will see in
            the actual chat. Pure illustration; non-interactive.
          */}
          <div className="chatbot-tutorial__preview" aria-hidden="true">
            <div className="chatbot-tutorial__previewHead">
              <span className="chatbot-tutorial__previewDot" style={{ background: "#EF4444" }} />
              <span className="chatbot-tutorial__previewDot" style={{ background: "#F59E0B" }} />
              <span className="chatbot-tutorial__previewDot" style={{ background: "#22C55E" }} />
              <span className="chatbot-tutorial__previewTitle">Editor</span>
              <span className="chatbot-tutorial__previewStatus">● en vivo</span>
            </div>
            <div className="chatbot-tutorial__previewBody">
              <div className="chatbot-tutorial__previewMsg chatbot-tutorial__previewMsg--user">
                muéstrame proyectos con python
              </div>
              <div className="chatbot-tutorial__previewMsg chatbot-tutorial__previewMsg--bot">
                Hay <strong>siete proyectos</strong> con <em>Python</em>: <em>proj-cloud-migration</em>, <em>HiRag15k</em>, <em>proj-finance-cli</em> y otros más.
              </div>
              <div className="chatbot-tutorial__previewResults">
                <div className="chatbot-tutorial__previewResult">
                  <div className="chatbot-tutorial__previewThumb">CM</div>
                  <div>
                    <strong>proj-cloud-migration</strong>
                    <span>Migración a AWS multi-cuenta</span>
                  </div>
                </div>
                <div className="chatbot-tutorial__previewResult">
                  <div className="chatbot-tutorial__previewThumb chatbot-tutorial__previewThumb--alt" style={{ background: "#06B6D4" }}>
                    R
                  </div>
                  <div>
                    <strong>HiRag15k</strong>
                    <span>Wrapper RAG open-source</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <footer className="chatbot-tutorial__footer">
            <label className="chatbot-tutorial__checkbox">
              <input
                type="checkbox"
                checked={tutorialNoShow}
                onChange={handleTutorialNoShowChange}
              />
              <span>{tutorialCopy.noShow}</span>
            </label>
            <button type="button" className="chatbot-tutorial__btn" onClick={dismissTutorial}>
              {tutorialCopy.startChat}
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
            </button>
          </footer>
        </div>
      </div>
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