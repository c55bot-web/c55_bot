"""Допомога для запитів «на звільнення» (Зв): JSON, формат звіту, коротке ім'я."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from database.models import User


def zv_payload(
    date_from: str,
    time_from: str,
    date_to: str,
    time_to: str,
    reason: str,
    address: str = "",
) -> str:
    return json.dumps(
        {
            "date_from": date_from,
            "time_from": time_from,
            "date_to": date_to,
            "time_to": time_to,
            "reason": reason,
            "address": (address or "").strip(),
        },
        ensure_ascii=False,
    )


def parse_zv_payload(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def format_name_short(full_name: str) -> str:
    """Приклад: «Оврашко Михайло Сергійович» → «Оврашко М.С.»"""
    parts = full_name.strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0]
    initials = []
    for p in parts[1:]:
        if p:
            initials.append(p[0] + ".")
    return f"{parts[0]} {''.join(initials)}"


def zv_request_button_label(full_name: str) -> str:
    return f"{format_name_short(full_name)} На зв"


def format_zv_admin_report(user: User, data: dict[str, Any]) -> str:
    """Текст звіту для адміна згідно з ТЗ."""
    na = getattr(user, "na_count", 0) or 0
    viol = getattr(user, "violations_count", 0) or 0
    zv_addr = (data.get("address") or "").strip()
    profile_addr = (user.address or "").strip()
    addr_line = zv_addr if zv_addr else (profile_addr or "—")
    reason = (data.get("reason") or "—").strip()
    df, tf = data.get("date_from"), data.get("time_from")
    dt, tt = data.get("date_to"), data.get("time_to")
    try:
        d1 = datetime.fromisoformat(df).strftime("%d.%m.%Y") if df else "?"
    except Exception:
        d1 = str(df)
    try:
        d2 = datetime.fromisoformat(dt).strftime("%d.%m.%Y") if dt else "?"
    except Exception:
        d2 = str(dt)
    lines = [
        user.full_name,
        f"НА: {na}",
        f"Порушень: {viol}",
        f"З {d1} ({tf}) - по {d2} ({tt})",
        f"Адреса Зв: {addr_line}",
        f"Причина: {reason}",
    ]
    return "\n".join(lines)


def zv_end_datetime(data: dict[str, Any]) -> datetime | None:
    """Кінець періоду Зв для перевірки прострочення."""
    try:
        dt = data.get("date_to")
        tm = data.get("time_to") or "23:59"
        if not dt:
            return None
        if "T" in str(dt):
            return datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
        return datetime.strptime(f"{dt} {tm}", "%Y-%m-%d %H:%M")
    except Exception:
        return None
