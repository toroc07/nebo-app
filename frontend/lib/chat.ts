// Public chat: one room per catalogue object plus a general room (contract: backend/app/chat.py
// and GET/POST /chat/{room}/messages). Nobody signs in: the browser keeps a generated nickname.
// Relative import (not "@/lib/api") so the node test runner can load this file directly.
import { origin, read } from "./api";

export const GENERAL_ROOM = "general";
/** How often an open chat asks for new messages. */
export const POLL_MS = 3000;
/** Messages kept on screen; older ones scroll away. */
const MAX_ON_SCREEN = 200;
const NICKNAME_KEY = "nebo.chat.nickname";

// Keep in sync with NICKNAME_WORDS in backend/app/chat.py: the server only accepts these.
export const NICKNAME_WORDS = [
  "Stargazer",
  "Comet",
  "Nebula",
  "Quasar",
  "Pulsar",
  "Photon",
  "Orbit",
  "Meteor",
  "Nova",
  "Galaxy",
  "Aurora",
  "Eclipse",
  "Zenith",
  "Voyager",
  "Cosmos",
  "Parsec",
] as const;

export type ChatMessage = {
  id: number;
  nickname: string;
  body: string;
  created_at: string;
};

export type ChatPage = {
  room: string;
  retention_hours: number;
  max_length: number;
  messages: ChatMessage[];
};

/** A message the server refused, with the reason to show (banned words, a link, too fast…). */
export class ChatRefused extends Error {
  constructor(
    public code: string,
    message: string,
    public retryAfter = 0,
  ) {
    super(message);
  }
}

export function makeNickname(random: () => number = Math.random): string {
  const word = NICKNAME_WORDS[Math.floor(random() * NICKNAME_WORDS.length)];
  const digits = String(Math.floor(random() * 10000)).padStart(4, "0");
  return `${word}-${digits}`;
}

export function isNickname(value: string | null | undefined): value is string {
  const match = /^([A-Z][a-z]+)-\d{4}$/.exec(value ?? "");
  return !!match && (NICKNAME_WORDS as readonly string[]).includes(match[1]);
}

/** The nickname kept in this browser, created on first use. Works without storage too. */
export function storedNickname(
  storage?: Pick<Storage, "getItem" | "setItem">,
): string {
  try {
    const store = storage ?? window.localStorage;
    const saved = store.getItem(NICKNAME_KEY);
    if (isNickname(saved)) return saved;
    const fresh = makeNickname();
    store.setItem(NICKNAME_KEY, fresh);
    return fresh;
  } catch {
    return makeNickname();
  }
}

export function fetchMessages(
  room: string,
  after: number,
  signal?: AbortSignal,
): Promise<ChatPage> {
  return read<ChatPage>(
    `/chat/${encodeURIComponent(room)}/messages?after=${after}`,
    signal,
  );
}

export async function sendMessage(
  room: string,
  nickname: string,
  body: string,
): Promise<ChatMessage> {
  let r: Response;
  try {
    r = await fetch(
      `${origin}/api/v1/chat/${encodeURIComponent(room)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nickname, body }),
      },
    );
  } catch {
    throw new ChatRefused(
      "offline",
      "Could not reach the chat. Check your connection.",
    );
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok)
    throw new ChatRefused(
      data.code ?? String(r.status),
      typeof data.detail === "string"
        ? data.detail
        : "The message could not be sent.",
      Number(r.headers.get("Retry-After")) || 0,
    );
  return data as ChatMessage;
}

/** Messages in order without duplicates (a sent message also comes back in the next poll). */
export function mergeMessages(
  current: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  if (!incoming.length) return current;
  const byId = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => a.id - b.id).slice(-MAX_ON_SCREEN);
}
