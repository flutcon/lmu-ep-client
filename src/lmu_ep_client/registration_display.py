from __future__ import annotations

from typing import Any


def private_registration_marker(reg: dict[str, Any]) -> str:
    if not reg.get("isPrivate"):
        return ""
    owner = str(reg.get("ownerLmuDriverName") or "").strip()
    if owner:
        return f" [private: {owner}]"
    return " [private]"


def private_registration_column(reg: dict[str, Any]) -> str:
    if not reg.get("isPrivate"):
        return "no"
    owner = str(reg.get("ownerLmuDriverName") or "").strip()
    return owner or "yes"
