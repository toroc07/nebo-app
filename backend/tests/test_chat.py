from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import chat, main
from app.targets import TARGETS
from tests.memory_store import MemoryStore

NICK = "Stargazer-4821"


# ----- filters ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "eres un pendejo",
        "P3ND3J0",
        "puuuuta madre",
        "p u t a",
        "f*ck this",
        "what the fuck",
        "this is bullshit",
        "mierda de imagen",
        "pendejazo",
        "Cabrón",
    ],
)
def test_banned_words_are_blocked_in_any_disguise(text):
    with pytest.raises(chat.ChatRejected) as error:
        chat.check_message(text)
    assert error.value.code == "blocked_words"


@pytest.mark.parametrize(
    "text",
    [
        "Barnard's Star moved 10.4 arcsec per year!",
        "El tren va retrasado pero la imagen de 2026-11-15 05:39 está genial",
        "the predicted cone is narrow; el cono de error es pequeño",
        "Niger is a country, and a pera is a pear",
        "RA 269.446 Dec +4.769 at MJD 61121.0",
        "WISE 0855 is around 250 K, 7.4 light years away",
        "Shiitake mushrooms are not stars",
    ],
)
def test_ordinary_astronomy_messages_pass(text):
    assert chat.check_message(text) == text


@pytest.mark.parametrize(
    "text, what",
    [
        ("look at https://evil.example", "links"),
        ("go to www.example.org", "links"),
        ("best pics on mysite.com", "links"),
        ("write me at someone@example.com", "email addresses"),
        ("follow me @stargazer_99", "social media handles"),
        ("call me 300 123 4567", "phone numbers"),
        ("whatsapp +57 (300) 123-4567", "phone numbers"),
    ],
)
def test_links_and_personal_data_are_blocked(text, what):
    with pytest.raises(chat.ChatRejected) as error:
        chat.check_message(text)
    assert error.value.code == "personal_data" and what in str(error.value)


def test_length_empty_and_invisible_characters():
    assert chat.check_message("  hola​   cielo \n") == "hola cielo"
    with pytest.raises(chat.ChatRejected, match="Write a message"):
        chat.check_message(" ​ ")
    with pytest.raises(chat.ChatRejected) as error:
        chat.check_message("a" * (chat.MAX_LENGTH + 1))
    assert error.value.code == "too_long"


def test_only_generated_nicknames_are_accepted():
    assert chat.check_nickname("Nebula-0007") == "Nebula-0007"
    for bad in ("Pendejo-1234", "Stargazer-12", "stargazer-1234", "Stargazer-1234 ", ""):
        with pytest.raises(chat.ChatRejected):
            chat.check_nickname(bad)


def test_flood_guard_allows_one_message_per_interval():
    guard = chat.FloodGuard(interval_s=60)
    assert guard.wait_s("1.2.3.4") == 0
    assert guard.wait_s("1.2.3.4") > 0
    assert guard.wait_s("5.6.7.8") == 0


# ----- API ----------------------------------------------------------------------------------


@pytest.fixture
def client():
    store = MemoryStore()
    store.upsert_targets(TARGETS)
    main.app.dependency_overrides[main.get_store] = lambda: store
    main._chat_flood = chat.FloodGuard(interval_s=0)
    try:
        yield TestClient(main.app), store
    finally:
        main.app.dependency_overrides.clear()
        main._chat_flood = chat.FloodGuard()


def test_rooms_are_general_or_a_catalogue_object(client):
    http, _ = client
    assert http.get("/api/v1/chat/general/messages").status_code == 200
    assert http.get("/api/v1/chat/barnards-star/messages").status_code == 200
    assert http.get("/api/v1/chat/not-a-target/messages").status_code == 404
    assert http.get("/api/v1/chat/Bad_Room/messages").status_code == 422


def test_post_then_poll_only_new_messages(client):
    http, _ = client
    url = "/api/v1/chat/barnards-star/messages"
    first = http.post(url, json={"nickname": NICK, "body": "It moves so fast!"})
    assert first.status_code == 201
    sent = first.json()
    assert sent["nickname"] == NICK and sent["body"] == "It moves so fast!"
    http.post(url, json={"nickname": NICK, "body": "10.4 arcsec per year"})

    page = http.get(url).json()
    assert [m["body"] for m in page["messages"]] == ["It moves so fast!", "10.4 arcsec per year"]
    assert page["retention_hours"] == 24 and page["max_length"] == chat.MAX_LENGTH
    newer = http.get(url, params={"after": sent["id"]}).json()["messages"]
    assert [m["body"] for m in newer] == ["10.4 arcsec per year"]
    # Rooms are separate.
    assert http.get("/api/v1/chat/general/messages").json()["messages"] == []


def test_refused_messages_say_why_and_are_not_stored(client):
    http, store = client
    url = "/api/v1/chat/general/messages"
    rude = http.post(url, json={"nickname": NICK, "body": "eres un p3nd3jo"})
    assert rude.status_code == 422 and rude.json()["code"] == "blocked_words"
    link = http.post(url, json={"nickname": NICK, "body": "visit spam.com"})
    assert link.status_code == 422 and link.json()["code"] == "personal_data"
    fake = http.post(url, json={"nickname": "Admin", "body": "hello"})
    assert fake.status_code == 422 and fake.json()["code"] == "nickname"
    assert store.chat_messages == []


def test_flooding_is_slowed_down(client):
    http, _ = client
    main._chat_flood = chat.FloodGuard(interval_s=60)
    url = "/api/v1/chat/general/messages"
    assert http.post(url, json={"nickname": NICK, "body": "one"}).status_code == 201
    second = http.post(url, json={"nickname": NICK, "body": "two"})
    assert second.status_code == 429 and int(second.headers["Retry-After"]) > 0


def test_messages_older_than_a_day_disappear(client):
    http, store = client
    url = "/api/v1/chat/general/messages"
    http.post(url, json={"nickname": NICK, "body": "yesterday"})
    store.chat_messages[0]["created_at"] = datetime.now(timezone.utc) - timedelta(hours=25)
    assert http.get(url).json()["messages"] == []
    # The next post deletes the old row for good.
    http.post(url, json={"nickname": NICK, "body": "today"})
    assert [m["body"] for m in store.chat_messages] == ["today"]
