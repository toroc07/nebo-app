"use client";
// Public chat, opened from a button in the top-left corner. The room follows the selected
// catalogue object; with nothing selected it is the general room. Messages are polled while the
// panel is open and the tab is visible; the server filters them and deletes them after 24 h.
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { MessageCircle, SendHorizontal, X } from "lucide-react";
import {
  ChatRefused,
  fetchMessages,
  mergeMessages,
  POLL_MS,
  sendMessage,
  storedNickname,
  type ChatMessage,
} from "@/lib/chat";
import s from "./chat.module.css";

const MAX_LENGTH = 280;

function timeOf(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ChatPanel({
  room,
  roomLabel,
}: {
  room: string;
  roomLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const [nickname, setNickname] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const lastId = useRef(0);

  // Read from storage after mount, so the server render and the first client render match.
  useEffect(() => setNickname(storedNickname()), []);

  // A new room starts empty.
  useEffect(() => {
    setMessages([]);
    setLoaded(false);
    setError("");
    lastId.current = 0;
  }, [room]);

  // Poll while open and visible. The first request brings the latest messages, the next ones only
  // what is newer than the last id received.
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) {
        try {
          const page = await fetchMessages(room, lastId.current, abort.signal);
          if (abort.signal.aborted) return;
          setMessages((current) => {
            const merged = mergeMessages(current, page.messages);
            lastId.current = merged.at(-1)?.id ?? lastId.current;
            return merged;
          });
          setLoaded(true);
        } catch {
          if (abort.signal.aborted) return;
          setLoaded(true);
        }
      }
      timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [open, room]);

  // Keep the newest message in view when it arrives, unless the reader scrolled up to read.
  useEffect(() => {
    const el = list.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 120)
      el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const body = draft.trim();
    if (!body || sending || !nickname) return;
    setSending(true);
    setError("");
    try {
      const sent = await sendMessage(room, nickname, body);
      setDraft("");
      setMessages((current) => mergeMessages(current, [sent]));
    } catch (err) {
      setError(
        err instanceof ChatRefused
          ? err.message
          : "The message could not be sent.",
      );
    } finally {
      setSending(false);
      input.current?.focus();
    }
  }

  return (
    <div className={s.chat}>
      <button
        ref={button}
        type="button"
        className={s.toggle}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? "Close the public chat" : "Open the public chat"}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <MessageCircle size={20} aria-hidden="true" />
        <span className={s.toggleText}>Chat</span>
      </button>
      {open && (
        <section
          id={panelId}
          className={s.panel}
          aria-label={`Public chat: ${roomLabel}`}
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
          }}
        >
          <header className={s.head}>
            <div>
              <h2 className={s.title}>{roomLabel}</h2>
              <p className={s.sub}>
                Public chat · you are <strong>{nickname || "…"}</strong>
              </p>
            </div>
            <button
              type="button"
              className={s.close}
              onClick={close}
              aria-label="Close the chat"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          <p className={s.rules}>
            Everyone can read this room. Messages are deleted after 24 hours. No
            links or personal data; offensive words are blocked.
          </p>
          <ol ref={list} className={s.list} role="log" aria-live="polite">
            {!loaded && <li className={s.empty}>Loading messages…</li>}
            {loaded && messages.length === 0 && (
              <li className={s.empty}>
                No messages in the last 24 hours. Share a fun fact!
              </li>
            )}
            {messages.map((m) => (
              <li
                key={m.id}
                className={m.nickname === nickname ? s.mine : s.message}
              >
                <span className={s.meta}>
                  <span className={s.nick}>
                    {m.nickname}
                    {m.nickname === nickname && " (you)"}
                  </span>
                  <time dateTime={m.created_at}>{timeOf(m.created_at)}</time>
                </span>
                <span className={s.body}>{m.body}</span>
              </li>
            ))}
          </ol>
          <form className={s.form} onSubmit={submit}>
            <label className={s.srOnly} htmlFor={`${panelId}-input`}>
              Message
            </label>
            <textarea
              id={`${panelId}-input`}
              ref={input}
              className={s.input}
              rows={2}
              maxLength={MAX_LENGTH}
              value={draft}
              placeholder="Write a message…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <div className={s.formRow}>
              <span className={s.count} aria-live="off">
                {draft.length}/{MAX_LENGTH}
              </span>
              <button
                type="submit"
                className={s.send}
                disabled={!draft.trim() || sending}
              >
                <SendHorizontal size={16} aria-hidden="true" />
                {sending ? "Sending…" : "Send"}
              </button>
            </div>
            {error && (
              <p className={s.error} role="alert">
                {error}
              </p>
            )}
          </form>
        </section>
      )}
    </div>
  );
}
