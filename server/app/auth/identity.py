"""Who a person is and what they may do in Rookie Agent (task 10.1). A password is checked and dropped: never kept, never logged."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

ROLES = ("maker", "checker", "admin")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")   # an AD account name; nothing that could change an LDAP search
WRONG = "Sai tên đăng nhập hoặc mật khẩu."


class LoginError(Exception):
    """The message is safe to show: it never says which of the name or the password was wrong."""


@dataclass(frozen=True)
class User:
    name: str
    display: str
    unit: str
    roles: tuple[str, ...]

    def has(self, role: str) -> bool:
        return role in self.roles or "admin" in self.roles

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "display": self.display, "unit": self.unit, "roles": list(self.roles)}


# With login off (one PC, the bundled server): every caller is this PC, as before Gate 10.
LOCAL = User("may-nay", "Máy này (chưa bật đăng nhập)", "", ROLES)


class DevIdentity:
    """Fixed people from config/roles.json (`dev_users`): for tests and demos only (ROOKIE_AUTH=dev), never on a real PC."""

    def __init__(self, users: list[dict[str, Any]]) -> None:
        self._users = {str(u["name"]): u for u in users}

    def check(self, name: str, password: str) -> User:
        person = self._users.get(name)
        if person is None or not password or str(person.get("password")) != password:
            raise LoginError(WRONG)
        roles = tuple(r for r in ROLES if r in person.get("roles", []))
        if not roles:
            raise LoginError("Tài khoản chưa được cấp quyền dùng Rookie Agent. Nhờ quản trị thêm vào nhóm.")
        return User(name, str(person.get("display") or name), str(person.get("unit") or ""), roles)


# A directory: bind as the person with their password, then read their display name, unit and groups (distinguished names).
# Returns None when the bind fails. Raises anything else when AD cannot be reached.
Directory = Callable[[str, str], "dict[str, Any] | None"]


class LdapIdentity:
    """The bank's AD. Roles come from the AD groups named in config/roles.json (`groups`); a person in none of them is refused."""

    def __init__(self, groups: dict[str, list[str]], directory: Directory | None = None) -> None:
        self._groups = {role: {g.lower() for g in groups.get(role, [])} for role in ROLES}
        self._directory = directory or ldap3_directory()

    def check(self, name: str, password: str) -> User:
        if not _NAME.match(name or "") or not password:   # an empty password would bind anonymously: never sent
            raise LoginError(WRONG)
        try:
            found = self._directory(name, password)
        except LoginError:
            raise
        except Exception as error:  # noqa: BLE001  any failure to reach AD
            raise LoginError(f"Không kết nối được AD để đăng nhập ({type(error).__name__}). Thử lại sau hoặc báo quản trị.") from None
        if found is None:
            raise LoginError(WRONG)
        names = {_first_cn(g) for g in found.get("groups") or []}
        roles = tuple(r for r in ROLES if self._groups[r] & names)
        if not roles:
            raise LoginError("Tài khoản chưa được cấp quyền dùng Rookie Agent. Nhờ quản trị thêm vào nhóm.")
        return User(name, str(found.get("display") or name), str(found.get("unit") or ""), roles)


def _first_cn(dn: str) -> str:
    head = str(dn).split(",", 1)[0].strip()
    return head.split("=", 1)[1].strip().lower() if head.lower().startswith("cn=") else head.lower()


def ldap3_directory() -> Directory:
    """AD through ldap3 (pure Python; its wheel goes into the internal network with the package). Settings from the environment:
    ROOKIE_LDAP_URL (ldap://dc.bank.local or ldaps://…), ROOKIE_LDAP_DOMAIN (the UPN suffix, bank.local), ROOKIE_LDAP_BASE_DN
    (DC=bank,DC=local), ROOKIE_LDAP_UNIT_ATTRIBUTE (default department)."""
    url = os.environ.get("ROOKIE_LDAP_URL", "").strip()
    domain = os.environ.get("ROOKIE_LDAP_DOMAIN", "").strip()
    base_dn = os.environ.get("ROOKIE_LDAP_BASE_DN", "").strip()
    unit_attribute = os.environ.get("ROOKIE_LDAP_UNIT_ATTRIBUTE", "department").strip() or "department"
    if not (url and domain and base_dn):
        raise RuntimeError("ROOKIE_AUTH=ldap cần đặt ROOKIE_LDAP_URL, ROOKIE_LDAP_DOMAIN và ROOKIE_LDAP_BASE_DN.")

    def directory(name: str, password: str) -> dict[str, Any] | None:
        import ldap3
        from ldap3.core.exceptions import LDAPBindError
        from ldap3.utils.conv import escape_filter_chars

        server = ldap3.Server(url, get_info=ldap3.NONE, connect_timeout=5)
        try:
            connection = ldap3.Connection(server, user=f"{name}@{domain}", password=password, auto_bind=True, receive_timeout=10,
                                          read_only=True)
        except LDAPBindError:
            return None
        try:
            connection.search(base_dn, f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(name)}))",
                              attributes=["displayName", "memberOf", unit_attribute], size_limit=1)
            if not connection.entries:
                return None
            entry = connection.entries[0].entry_attributes_as_dict
            first = lambda key: (entry.get(key) or [""])[0]   # noqa: E731
            return {"display": first("displayName"), "unit": first(unit_attribute), "groups": list(entry.get("memberOf") or [])}
        finally:
            connection.unbind()

    return directory
