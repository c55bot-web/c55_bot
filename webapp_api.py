"""HTTPS-friendly Mini App API (no tg.sendData).

Telegram Mini Apps cannot reliably call the bot backend on github.io without a separate API origin.
This module exposes a small aiohttp JSON API, validates Telegram WebApp initData using aiogram helpers,
and reuses the same DB logic as the bot.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from aiogram.utils.web_app import safe_parse_webapp_init_data

from core.config import BOT_TOKEN, POLL_DISPLAY_NAMES
from database.requests import check_is_admin, get_closed_polls_history

log = logging.getLogger(__name__)

_ALLOWED_ORIGIN_SUFFIXES = (
    "https://c55bot-web.github.io",
    "https://web.telegram.org",
    "https://telegram.org",
)


def _cors_headers(origin: str | None) -> dict[str, str]:
    allow_origin = "*"
    if origin:
        if origin.startswith(_ALLOWED_ORIGIN_SUFFIXES):
            allow_origin = origin
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Web-App-Init-Data",
        "Access-Control-Max-Age": "86400",
    }


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        return await request.json(loads=json.loads)
    except Exception:
        return {}


def _extract_init_data(request: web.Request, payload: dict[str, Any]) -> str:
    hdr = request.headers.get("X-Telegram-Web-App-Init-Data", "").strip()
    if hdr:
        return hdr
    v = payload.get("init_data") or payload.get("initData")
    return str(v or "").strip()


async def handle_options(request: web.Request) -> web.Response:
    origin = request.headers.get("Origin")
    return web.Response(status=204, headers=_cors_headers(origin))


async def handle_admin_history(request: web.Request) -> web.Response:
    origin = request.headers.get("Origin")
    headers = _cors_headers(origin)
    headers["Content-Type"] = "application/json; charset=utf-8"

    if request.method != "POST":
        return web.json_response({"ok": False, "error": "method_not_allowed"}, status=405, headers=headers)

    payload = await _read_json(request)
    init_data = _extract_init_data(request, payload)
    if not init_data:
        return web.json_response({"ok": False, "error": "missing_init_data"}, status=401, headers=headers)

    try:
        parsed = safe_parse_webapp_init_data(BOT_TOKEN, init_data)
    except Exception:
        return web.json_response({"ok": False, "error": "bad_init_data"}, status=401, headers=headers)

    user = parsed.user
    if not user:
        return web.json_response({"ok": False, "error": "missing_user"}, status=401, headers=headers)

    if not await check_is_admin(user.id):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403, headers=headers)

    limit_days = int(payload.get("limit_days", 7) or 7)
    polls = await get_closed_polls_history(limit_days=limit_days)
    if not polls:
        return web.json_response({"ok": True, "text": "ℹ️ Історія порожня (за 7 днів)."}, status=200, headers=headers)

    lines = ["📊 <b>Історія закритих опитувань (останні 7 днів)</b>", ""]
    shown = 0
    for p in polls:
        if shown >= 6:
            break
        created = p.created_at.strftime("%d.%m %H:%M") if p.created_at else "?"
        name = POLL_DISPLAY_NAMES.get(p.type, p.type)
        lines.append(f"<b>{name}</b> ({p.type}) — {created}")
        if p.report_text:
            lines.append(p.report_text)
        else:
            lines.append("ℹ️ Детальний звіт для цього опитування не збережено.")
        lines.append("")
        shown += 1
    if len(polls) > shown:
        lines.append(f"… ще {len(polls) - shown} звіт(ів) за 7 днів.")

    text = "\n".join(lines)
    return web.json_response({"ok": True, "text": text, "parse_mode": "HTML"}, status=200, headers=headers)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_route("OPTIONS", "/api/c55/admin/history", handle_options)
    app.router.add_route("POST", "/api/c55/admin/history", handle_admin_history)
    return app


async def start_site(host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_app())
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("C55 WebApp API listening on http://%s:%s", host, port)
    return runner
