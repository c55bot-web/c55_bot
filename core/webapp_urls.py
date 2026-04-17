"""URL для C55 Mini App (актуальна збірка та legacy v0.45 на GitHub Pages)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.config import C55_WEBAPP_API_URL, C55_WEBAPP_URL, C55_WEBAPP_URL_V045

# Версія кешу WebView; змінюй при оновленні статики на gh-pages
C55_WEBAPP_CACHE_BUST = "20260417u"


def _path_with_v045(path: str) -> str:
    """Вставляє сегмент /v0.45/ перед /webapp/ або /docs/ (типова схема gh-pages)."""
    if not path or "/v0.45/" in path:
        return path
    for marker in ("/webapp/", "/docs/"):
        idx = path.find(marker)
        if idx >= 0:
            prefix = path[:idx].rstrip("/")
            rest = path[idx:]
            return f"{prefix}/v0.45{rest}" if prefix else f"/v0.45{rest}"
    return path


def build_c55_webapp_url(*, is_admin: bool, legacy_v045: bool = False) -> str:
    """
    Повертає URL WebApp з query: v, is_admin, api (якщо задано).

    legacy_v045: повний URL з C55_WEBAPP_URL_V045 або шлях з /v0.45/ відносно C55_WEBAPP_URL.
    """
    if not C55_WEBAPP_URL:
        return ""

    if legacy_v045 and C55_WEBAPP_URL_V045:
        base = C55_WEBAPP_URL_V045
    else:
        base = C55_WEBAPP_URL

    parts = urlsplit(base)
    path = parts.path
    if legacy_v045 and not C55_WEBAPP_URL_V045:
        path = _path_with_v045(path)

    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    qs["v"] = C55_WEBAPP_CACHE_BUST
    qs["is_admin"] = "1" if is_admin else "0"
    if C55_WEBAPP_API_URL:
        qs["api"] = C55_WEBAPP_API_URL

    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(qs), parts.fragment))


def reply_kb_webapp_urls(*, is_admin: bool) -> tuple[str, str]:
    """
    (поточний WebApp URL, URL адмін-панелі v0.45 або "").
    Другий рядок кнопки показуємо лише якщо URL відрізняється від першого.
    """
    primary = build_c55_webapp_url(is_admin=is_admin, legacy_v045=False)
    if not primary or not is_admin:
        return primary, ""

    legacy = build_c55_webapp_url(is_admin=True, legacy_v045=True)
    if not legacy or legacy == primary:
        return primary, ""

    return primary, legacy
