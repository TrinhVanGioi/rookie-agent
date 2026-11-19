"""Task 10.1: who is calling. Off (one PC, as before), dev (fixed users, for tests and demos) or ldap (the bank's AD)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.identity import DevIdentity, LdapIdentity, LoginError
from app.main import create_app

DEV_USERS = [
    {"name": "gdv1", "password": "pw-gdv1", "display": "GDV Một", "unit": "CN-HN", "roles": ["maker"]},
    {"name": "ksv1", "password": "pw-ksv1", "display": "KSV Một", "unit": "CN-HN", "roles": ["checker"]},
    {"name": "quantri", "password": "pw-qt", "display": "Quản trị", "unit": "HO", "roles": ["admin"]},
]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def dev(tmp_path, clock):
    app = create_app(tmp_path / "auth.db", auth_mode="dev", identity=DevIdentity(DEV_USERS), clock=clock)
    with TestClient(app) as client:
        yield client


def login(client, name, password, kind="agent"):
    return client.post("/auth/login", json={"username": name, "password": password, "client": kind})


def test_with_login_off_every_caller_is_this_pc_as_before(client):
    assert client.get("/workflows").status_code == 200
    me = client.get("/auth/me").json()
    assert me["mode"] == "off" and "admin" in me["user"]["roles"]


def test_with_login_on_a_caller_without_a_login_is_refused_in_vietnamese(dev):
    for path in ("/workflows", "/sessions", "/twin/processes"):
        reply = dev.get(path)
        assert reply.status_code == 401 and "đăng nhập" in reply.json()["detail"]
    assert dev.get("/health").status_code == 200


def test_a_wrong_password_is_refused_and_says_nothing_about_which_part_was_wrong(dev):
    for name, password in (("gdv1", "sai"), ("khong-co", "pw-gdv1")):
        reply = login(dev, name, password)
        assert reply.status_code == 401 and reply.json()["detail"] == "Sai tên đăng nhập hoặc mật khẩu."


def test_the_agent_gets_a_token_and_the_admin_page_a_cookie_only_the_page_script_cannot_read(dev):
    reply = login(dev, "gdv1", "pw-gdv1")
    assert reply.status_code == 200
    body = reply.json()
    assert body["user"] == {"name": "gdv1", "display": "GDV Một", "unit": "CN-HN", "roles": ["maker"]}
    assert "password" not in str(body) and "pw-gdv1" not in str(body)
    assert dev.get("/workflows", headers={"Authorization": "Bearer " + body["token"]}).status_code == 200

    page = login(dev, "quantri", "pw-qt", kind="admin")
    cookie = page.headers["set-cookie"]
    assert "rk_session=" in cookie and "httponly" in cookie.lower() and "samesite=strict" in cookie.lower()
    assert "token" not in page.json()
    assert dev.get("/auth/me").json()["user"]["name"] == "quantri"


def test_a_token_ends_at_logout_and_when_it_is_too_old(dev, clock):
    token = login(dev, "gdv1", "pw-gdv1").json()["token"]
    auth = {"Authorization": "Bearer " + token}
    clock.now += 9 * 3600
    assert dev.get("/workflows", headers=auth).status_code == 200
    clock.now += 2 * 3600
    assert dev.get("/workflows", headers=auth).status_code == 401

    token = login(dev, "gdv1", "pw-gdv1").json()["token"]
    auth = {"Authorization": "Bearer " + token}
    assert dev.post("/auth/logout", headers=auth).status_code == 200
    assert dev.get("/workflows", headers=auth).status_code == 401


def test_five_wrong_passwords_lock_the_name_for_ten_minutes(dev, clock):
    for _ in range(5):
        assert login(dev, "gdv1", "sai").status_code == 401
    locked = login(dev, "gdv1", "pw-gdv1")
    assert locked.status_code == 429 and "10 phút" in locked.json()["detail"]
    clock.now += 601
    assert login(dev, "gdv1", "pw-gdv1").status_code == 200


def test_the_server_keeps_only_a_hash_of_a_token_and_never_the_password(dev, tmp_path):
    token = login(dev, "gdv1", "pw-gdv1").json()["token"]
    raw = (tmp_path / "auth.db").read_bytes()
    assert token.encode() not in raw and b"pw-gdv1" not in raw


# ---- the bank's AD (a stand-in directory: the real one is only inside the bank's network) ----------------------------------------


class Directory:
    """What LdapIdentity asks of AD: bind as the person, then read their name, unit and groups."""

    def __init__(self, people, up=True):
        self.people, self.up, self.binds = people, up, []

    def __call__(self, name, password):
        self.binds.append(name)
        if not self.up:
            raise ConnectionError("no route")
        person = self.people.get(name)
        if person is None or person["password"] != password:
            return None
        return {"display": person["display"], "unit": person["unit"], "groups": person["groups"]}


GROUPS = {"maker": ["RK-GDV"], "checker": ["RK-KSV"], "admin": ["RK-QUANTRI"]}
PEOPLE = {
    "an.nv": {"password": "x1", "display": "Nguyễn Văn An", "unit": "CN Hà Nội",
              "groups": ["CN=RK-GDV,OU=Groups,DC=bank,DC=local", "CN=Staff,OU=Groups,DC=bank,DC=local"]},
    "binh.tt": {"password": "x2", "display": "Trần Thị Bình", "unit": "CN Hà Nội", "groups": ["CN=Staff,OU=Groups,DC=bank,DC=local"]},
    "chi.lt": {"password": "x3", "display": "Lê Thị Chi", "unit": "Hội sở", "groups": ["cn=rk-ksv,ou=g,dc=bank", "CN=RK-QUANTRI,OU=g,DC=bank"]},
}


def test_ad_roles_come_from_the_groups_named_in_the_config():
    ad = LdapIdentity(GROUPS, directory=Directory(PEOPLE))
    an = ad.check("an.nv", "x1")
    assert (an.name, an.display, an.unit, an.roles) == ("an.nv", "Nguyễn Văn An", "CN Hà Nội", ("maker",))
    assert ad.check("chi.lt", "x3").roles == ("checker", "admin")


def test_ad_refuses_a_person_in_no_rookie_group_a_wrong_password_and_an_empty_one():
    directory = Directory(PEOPLE)
    ad = LdapIdentity(GROUPS, directory=directory)
    with pytest.raises(LoginError, match="chưa được cấp quyền"):
        ad.check("binh.tt", "x2")
    with pytest.raises(LoginError, match="Sai tên đăng nhập"):
        ad.check("an.nv", "sai")
    directory.binds.clear()
    with pytest.raises(LoginError, match="Sai tên đăng nhập"):
        ad.check("an.nv", "")            # an empty password binds anonymously in AD: never sent
    assert directory.binds == []


def test_ad_refuses_a_name_that_could_change_the_search():
    directory = Directory(PEOPLE)
    ad = LdapIdentity(GROUPS, directory=directory)
    for name in ("an.nv)(cn=*", "*", "a\\b", "x" * 65, ""):
        with pytest.raises(LoginError):
            ad.check(name, "x1")
    assert directory.binds == []


def test_ad_out_of_reach_is_said_plainly():
    ad = LdapIdentity(GROUPS, directory=Directory(PEOPLE, up=False))
    with pytest.raises(LoginError, match="Không kết nối được AD"):
        ad.check("an.nv", "x1")
