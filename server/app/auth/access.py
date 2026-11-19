"""Who sees and who changes a flow or a recording (task 10.2; docs/design.md 8).

- A flow is private to its owner by default. Only the owner shares it (with the unit or with everyone), after a preview.
- The admin sees and changes every flow, but does not share one for its owner.
- A recording is read only by whoever made it (and the admin). A flow or a recording from before Gate 10 has no owner: only the admin.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import User

NO_OWNER = "Chưa rõ chủ"


def can_see(user: User, meta: dict[str, Any]) -> bool:
    if user.has("admin") or (meta.get("owner") and meta["owner"] == user.name):
        return True
    visibility = meta.get("visibility") or "private"
    return visibility == "all" or (visibility == "unit" and bool(meta.get("unit")) and meta["unit"] == user.unit)


def can_change(user: User, meta: dict[str, Any]) -> bool:
    return user.has("admin") or (bool(meta.get("owner")) and meta["owner"] == user.name)


def can_share(user: User, meta: dict[str, Any]) -> bool:
    return bool(meta.get("owner")) and meta["owner"] == user.name


def sees_session(user: User, session: dict[str, Any]) -> bool:
    return user.has("admin") or (bool(session.get("owner")) and session["owner"] == user.name)
