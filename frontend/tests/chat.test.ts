import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ChatRefused,
  isNickname,
  makeNickname,
  mergeMessages,
  sendMessage,
  storedNickname,
  type ChatMessage,
} from "../lib/chat";

const msg = (id: number, body = `m${id}`): ChatMessage => ({
  id,
  nickname: "Nova-0001",
  body,
  created_at: "2026-11-15T05:00:00+00:00",
});

test("generated nicknames have the shape the server accepts", () => {
  for (let i = 0; i < 200; i++) assert.ok(isNickname(makeNickname()));
  assert.equal(
    makeNickname(() => 0),
    "Stargazer-0000",
  );
  for (const bad of ["Admin", "Pendejo-1234", "Nova-12", "nova-1234", ""])
    assert.equal(isNickname(bad), false);
});

test("the nickname is kept in the browser and survives without storage", () => {
  const box = new Map<string, string>();
  const storage = {
    getItem: (k: string) => box.get(k) ?? null,
    setItem: (k: string, v: string) => void box.set(k, v),
  };
  const first = storedNickname(storage);
  assert.equal(storedNickname(storage), first);
  box.set("nebo.chat.nickname", "Hacker-0000");
  assert.notEqual(storedNickname(storage), "Hacker-0000");
  const blocked = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {},
  };
  assert.ok(isNickname(storedNickname(blocked)));
});

test("merged messages stay in order without duplicates", () => {
  const merged = mergeMessages([msg(1), msg(3)], [msg(3, "again"), msg(2)]);
  assert.deepEqual(
    merged.map((m) => m.id),
    [1, 2, 3],
  );
  assert.equal(merged[2].body, "again");
  const same = [msg(1)];
  assert.equal(mergeMessages(same, []), same);
});

test("a refused message carries the server's reason", async () => {
  const previous = global.fetch;
  global.fetch = async () =>
    new Response(
      JSON.stringify({
        code: "personal_data",
        detail: "Links are not allowed.",
      }),
      { status: 422 },
    );
  try {
    await assert.rejects(
      sendMessage("general", "Nova-0001", "visit spam.com"),
      (e: unknown) =>
        e instanceof ChatRefused &&
        e.code === "personal_data" &&
        e.message === "Links are not allowed.",
    );
  } finally {
    global.fetch = previous;
  }
});
