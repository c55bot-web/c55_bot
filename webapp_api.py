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
from aiogram import Bot
from aiogram.utils.web_app import safe_parse_webapp_init_data

from core.config import BOT_TOKEN
from handlers.webapp_payload import execute_c55_webapp_payload

log = logging.getLogger(__name__)

_ALLOWED_ORIGIN_PREFIXES = (
    "https://c55bot-web.github.io",
    "https://web.telegram.org",
    "https://telegram.org",
)


def _cors_headers(origin: str | None) -> dict[str, str]:
    allow_origin = "*"
    if origin:
        if origin.startswith(_ALLOWED_ORIGIN_PREFIXES) or origin.endswith(".trycloudflare.com"):
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


def _json_headers(origin: str | None) -> dict[str, str]:
    h = _cors_headers(origin)
    h["Content-Type"] = "application/json; charset=utf-8"
    return h


async def handle_options(request: web.Request) -> web.Response:
    origin = request.headers.get("Origin")
    return web.Response(status=204, headers=_cors_headers(origin))


async def handle_c55_action(request: web.Request) -> web.Response:
    origin = request.headers.get("Origin")
    headers = _json_headers(origin)

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

    bot: Bot | None = request.app.get("bot")
    if bot is None:
        return web.json_response({"ok": False, "error": "server_misconfigured"}, status=500, headers=headers)

    kind = str(payload.get("kind", "c55_student_webapp")).strip()
    action = str(payload.get("action", "")).strip()
    if kind not in {"c55_student_webapp", "c55_admin_webapp"}:
        return web.json_response({"ok": False, "error": "bad_kind"}, status=400, headers=headers)
    if not action:
        return web.json_response({"ok": False, "error": "missing_action"}, status=400, headers=headers)

    res = await execute_c55_webapp_payload(bot, user.id, kind, action, payload)
    out: dict[str, Any] = {"ok": bool(res.get("ok", True))}
    if "text" in res:
        out["text"] = res["text"]
    if "parse_mode" in res:
        out["parse_mode"] = res["parse_mode"]
    if "data" in res:
        out["data"] = res["data"]
    return web.json_response(out, status=200, headers=headers)


async def handle_admin_history(request: web.Request) -> web.Response:
    """Зворотна сумісність: той самий результат, що й action admin_history_recent."""
    origin = request.headers.get("Origin")
    headers = _json_headers(origin)

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

    bot: Bot | None = request.app.get("bot")
    if bot is None:
        return web.json_response({"ok": False, "error": "server_misconfigured"}, status=500, headers=headers)

    merged = {**payload, "kind": "c55_admin_webapp", "action": "admin_history_recent"}
    res = await execute_c55_webapp_payload(bot, user.id, "c55_admin_webapp", "admin_history_recent", merged)
    out: dict[str, Any] = {"ok": True, "text": res.get("text", ""), "parse_mode": res.get("parse_mode", "HTML")}
    return web.json_response(out, status=200, headers=headers)


def build_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    for path in ("/api/c55/action", "/api/c55/admin/history"):
        app.router.add_route("OPTIONS", path, handle_options)
    app.router.add_route("POST", "/api/c55/action", handle_c55_action)
    app.router.add_route("POST", "/api/c55/admin/history", handle_admin_history)
    return app


async def start_site(bot: Bot, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("C55 WebApp API listening on http://%s:%s", host, port)
    return runner
