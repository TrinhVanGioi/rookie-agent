"""Login for the server (task 10.1; docs/design.md 13).

ROOKIE_AUTH chooses how:
- `off` (default): one PC with the bundled server; every caller is this PC, as before Gate 10.
- `dev`: the fixed people of config/roles.json `dev_users`, for tests and demos.
- `ldap`: the bank's AD; roles from the AD groups named in config/roles.json `groups`.

The admin page gets a cookie the page script cannot read; the Windows agent gets a token it sends as `Authorization: Bearer`.
The server keeps only the SHA-256 of a token. Passwords are checked and dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.identity import LOCAL, DevIdentity, LdapIdentity, LoginError, User

ROLES_PATH = Path(__file__).resolve().parents[3] / "config" / "roles.json"
COOKIE = "rk_session"
PROTECTED = ("/sessions", "/workflows", "/twin", "/assistant", "/runs", "/admin/api")
NEED_LOGIN = "Chưa đăng nhập hoặc phiên đăng nhập đã hết hạn. Đăng nhập lại."
MAX_FAILURES, LOCK_SECONDS = 5, 600


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=256)
    client: Literal["agent", "admin"] = "agent"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_roles(path: Path = ROLES_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Auth:
    def __init__(self, storage: Any, mode: str | None = None, identity: Any = None, clock: Callable[[], float] = time.time) -> None:
        self.mode = (mode or os.environ.get("ROOKIE_AUTH") or "off").strip().lower()
        if self.mode not in ("off", "dev", "ldap"):
            raise RuntimeError("ROOKIE_AUTH chỉ nhận off, dev hoặc ldap.")
        self.storage, self.clock = storage, clock
        self.hours = float(os.environ.get("ROOKIE_TOKEN_HOURS") or 10)
        if identity is None and self.mode != "off":
            roles = load_roles()
            identity = DevIdentity(roles.get("dev_users", [])) if self.mode == "dev" else LdapIdentity(roles.get("groups", {}))
        self.identity = identity
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def login(self, name: str, password: str, kind: str) -> tuple[User, str, float]:
        if self.mode == "off":
            raise HTTPException(409, "Máy chủ này chưa bật đăng nhập (ROOKIE_AUTH=off).")
        now, key = self.clock(), name.strip().lower()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < LOCK_SECONDS]
            self._failures[key] = recent
            if len(recent) >= MAX_FAILURES:
                raise HTTPException(429, f"Sai mật khẩu {MAX_FAILURES} lần. Tài khoản tạm khoá, thử lại sau 10 phút.")
        try:
            user = self.identity.check(name.strip(), password)
        except LoginError as error:
            with self._lock:
                self._failures.setdefault(key, []).append(now)
            raise HTTPException(401, str(error)) from None
        with self._lock:
            self._failures.pop(key, None)
        token, expires = secrets.token_urlsafe(32), now + self.hours * 3600
        self.storage.purge_tokens(now)
        self.storage.add_token(_hash(token), user.as_dict(), kind, expires)
        return user, token, expires

    def user_of(self, token: str | None) -> User | None:
        if self.mode == "off":
            return LOCAL
        if not token:
            return None
        found = self.storage.get_token(_hash(token))
        if found is None or found[2] <= self.clock():
            return None
        data = found[0]
        return User(data["name"], data["display"], data["unit"], tuple(data["roles"]))

    def logout(self, token: str | None) -> None:
        if token:
            self.storage.delete_token(_hash(token))


def token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE) or None


def user(request: Request) -> User:
    """The caller of a protected route (set by the middleware)."""
    return getattr(request.state, "user", None) or LOCAL


def require(request: Request, role: str) -> User:
    who = user(request)
    if not who.has(role):
        raise HTTPException(403, "Tài khoản này không có quyền làm việc này.")
    return who


def install(app: FastAPI, auth: Auth) -> None:
    app.state.auth = auth

    @app.middleware("http")
    async def who_is_calling(request: Request, call_next):
        if request.url.path.startswith(PROTECTED):
            found = auth.user_of(token_of(request))
            if found is None:
                return JSONResponse({"detail": NEED_LOGIN}, status_code=401)
            request.state.user = found
        return await call_next(request)

    @app.post("/auth/login")
    def login(body: LoginIn) -> JSONResponse:
        who, token, expires = auth.login(body.username, body.password, body.client)
        reply: dict[str, Any] = {"user": who.as_dict(), "expires_at": expires}
        if body.client == "agent":
            response = JSONResponse({**reply, "token": token})
        else:
            response = JSONResponse(reply)
            response.set_cookie(COOKIE, token, max_age=int(auth.hours * 3600), httponly=True, samesite="strict", path="/")
        return response

    @app.post("/auth/logout")
    def logout(request: Request) -> JSONResponse:
        auth.logout(token_of(request))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/auth/me")
    def me(request: Request) -> dict[str, Any]:
        found = auth.user_of(token_of(request))
        if found is None:
            raise HTTPException(401, NEED_LOGIN)
        return {"mode": auth.mode, "user": found.as_dict()}
