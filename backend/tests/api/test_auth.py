"""Accounts: sign-up/sign-in/sign-out, per-user isolation of documents and
conversations, admin-only settings, quotas, rate limits, CSRF and account deletion."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from querydoc.evaluation.synthetic import make_synthetic_pdf
from tests.api.conftest import build_client, upload

API = "/api/v1"
PW = "correct horse battery"


@pytest.fixture()
def auth_client(tmp_path, embedder) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    yield from build_client(tmp_path, embedder, app_overrides={
        "auth_enabled": True, "admin_emails": ["admin@example.com"], "max_documents_per_user": 3,
        "logins_per_minute_per_ip": 50, "signups_per_hour_per_ip": 50,
    })


def signup(c: TestClient, email: str, password: str = PW) -> dict:
    r = c.post(f"{API}/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def login(c: TestClient, email: str, password: str = PW) -> None:
    r = c.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


def logout(c: TestClient) -> None:
    assert c.post(f"{API}/auth/logout").status_code == 204


def test_local_mode_has_no_accounts(client):
    assert client.get(f"{API}/auth/config").json() == {"auth_enabled": False, "signup_enabled": True}
    me = client.get(f"{API}/auth/me").json()
    assert me["id"] == "local" and me["is_admin"] and me["auth_enabled"] is False
    assert client.post(f"{API}/auth/signup", json={"email": "a@b.co", "password": PW}).status_code == 404


def test_signup_login_logout(auth_client):
    c = auth_client
    assert c.get(f"{API}/health").status_code == 200  # public
    assert c.get(f"{API}/auth/config").json()["auth_enabled"] is True
    assert c.get(f"{API}/documents").status_code == 401
    assert c.get(f"{API}/auth/me").json()["error"]["code"] == "not_authenticated"

    bad = c.post(f"{API}/auth/signup", json={"email": "not-an-email", "password": PW})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_email"
    weak = c.post(f"{API}/auth/signup", json={"email": "a@example.com", "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"

    me = signup(c, "Alice@Example.com")
    assert me["email"] == "alice@example.com" and me["is_admin"] is False
    cookie = c.cookies.get("querydoc_session")
    assert cookie and len(cookie) > 30
    assert c.get(f"{API}/documents").status_code == 200
    assert c.post(f"{API}/auth/signup", json={"email": "alice@example.com", "password": PW}).status_code == 409

    logout(c)
    assert c.get(f"{API}/documents").status_code == 401
    wrong = c.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": "wrong password"})
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_credentials"
    unknown = c.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert unknown.status_code == 401 and unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    login(c, "ALICE@example.com")
    assert c.get(f"{API}/auth/me").json()["email"] == "alice@example.com"

    # A stolen-but-logged-out token no longer works.
    logout(c)
    c.cookies.set("querydoc_session", cookie)
    assert c.get(f"{API}/auth/me").status_code == 401


def test_users_cannot_see_each_others_data(auth_client):
    c = auth_client
    pdf, facts = make_synthetic_pdf(12, seed=31)
    signup(c, "alice@example.com")
    a_doc = upload(c, "alice.pdf", pdf)
    assert a_doc["status"] == "ready"
    r = c.post(f"{API}/chat", json={"message": facts[0].question})
    assert r.status_code == 200
    a_conv = r.json()["conversation_id"]
    logout(c)

    signup(c, "bob@example.com")
    assert c.get(f"{API}/documents").json()["total"] == 0
    assert c.get(f"{API}/conversations").json() == []
    for path in [f"/documents/{a_doc['id']}", f"/documents/{a_doc['id']}/file", f"/documents/{a_doc['id']}/status",
                 f"/conversations/{a_conv}"]:
        assert c.get(API + path).status_code == 404, path
    assert c.delete(f"{API}/documents/{a_doc['id']}").status_code == 404
    assert c.delete(f"{API}/conversations/{a_conv}").status_code == 404
    # Bob has no documents, and cannot reach Alice's by id or by continuing her conversation.
    assert c.post(f"{API}/chat", json={"message": "anything?"}).json()["error"]["code"] == "no_documents"
    b_doc = upload(c, "same-file.pdf", pdf)  # identical bytes: Bob gets his own copy
    assert b_doc["status"] == "ready" and b_doc["id"] != a_doc["id"]
    scoped = c.post(f"{API}/chat", json={"message": "x?", "document_ids": [a_doc["id"]]})
    assert scoped.status_code == 404
    assert c.post(f"{API}/chat", json={"message": "x?", "conversation_id": a_conv}).status_code == 404
    answer = c.post(f"{API}/chat", json={"message": facts[0].question}).json()["message"]
    assert answer["sources"] and {s["doc_id"] for s in answer["sources"]} == {b_doc["id"]}
    overview = c.get(f"{API}/analytics/overview").json()
    assert overview["documents"]["total"] == 1 and overview["conversations"] == 1
    logout(c)

    login(c, "alice@example.com")
    assert [d["id"] for d in c.get(f"{API}/documents").json()["items"]] == [a_doc["id"]]
    assert len(c.get(f"{API}/conversations").json()) == 1


def test_only_admins_change_server_settings(auth_client):
    c = auth_client
    signup(c, "user@example.com")
    s = c.get(f"{API}/settings").json()
    assert s["options"]["can_edit"] is False
    denied = c.put(f"{API}/settings", json={"top_k": 3})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
    logout(c)
    me = signup(c, "admin@example.com")
    assert me["is_admin"] is True
    assert c.get(f"{API}/settings").json()["options"]["can_edit"] is True
    assert c.put(f"{API}/settings", json={"top_k": 3}).json()["settings"]["top_k"] == 3


def test_document_quota(auth_client):
    c = auth_client
    signup(c, "quota@example.com")
    for seed in (41, 42, 43):
        upload(c, f"{seed}.pdf", make_synthetic_pdf(2, seed=seed)[0])
    r = c.post(f"{API}/documents/upload", files=[("files", ("4.pdf", make_synthetic_pdf(2, seed=44)[0], "application/pdf"))])
    assert r.status_code == 403 and r.json()["error"]["code"] == "quota_exceeded"


def test_login_rate_limit_and_cross_site_writes(tmp_path, embedder):
    gen = build_client(tmp_path, embedder, app_overrides={"auth_enabled": True, "logins_per_minute_per_ip": 3})
    c = next(gen)
    try:
        signup(c, "rl@example.com")
        logout(c)
        codes = [c.post(f"{API}/auth/login", json={"email": "rl@example.com", "password": "nope nope"}).status_code
                 for _ in range(4)]
        assert codes == [401, 401, 401, 429]
        evil = c.post(f"{API}/auth/logout", headers={"Origin": "https://evil.example"})
        assert evil.status_code == 403 and evil.json()["error"]["code"] == "forbidden_origin"
        assert c.post(f"{API}/auth/logout", headers={"Origin": "http://testserver"}).status_code == 204
    finally:
        gen.close()


def test_delete_account_removes_everything(auth_client):
    c = auth_client
    signup(c, "leaver@example.com")
    doc = upload(c, "mine.pdf", make_synthetic_pdf(3, seed=51)[0])
    vectors = c.get(f"{API}/health").json()["index_vectors"]
    assert vectors > 0
    assert c.request("DELETE", f"{API}/auth/me", json={"password": "wrong password"}).status_code == 401
    assert c.request("DELETE", f"{API}/auth/me", json={"password": PW}).status_code == 204
    assert c.get(f"{API}/health").json()["index_vectors"] == vectors - doc["chunk_count"]
    assert c.get(f"{API}/auth/me").status_code == 401
    assert c.post(f"{API}/auth/login", json={"email": "leaver@example.com", "password": PW}).status_code == 401
