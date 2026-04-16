"""Розрахунок НА з Google Таблиці SNE: колонки E і F (негативні бали → 1 НА за кожні 1,5 б.)."""
from __future__ import annotations

import logging
import re
import time

from core.config import SNE_SPREADSHEET_ID, SNE_CREDENTIALS_PATH


# E — I атестація (−1,5 б.), F — II атестація (−1,5 б.) у конфігу SNE; НА = сума по обох колонках
NA_POINTS_PER_ONE = 1.5

_cached_client = None
_cached_worksheet = None


def _get_sheet_client():
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(SNE_CREDENTIALS_PATH, scopes=scopes)
        _cached_client = gspread.authorize(creds)
        return _cached_client
    except Exception as e:
        logging.error("SNE NA: не вдалося підключитися до Google Sheets: %s", e)
        return None


def _get_worksheet():
    """Один раз відкриває таблицю (без повторних spreadsheets.get на кожен /discipline)."""
    global _cached_worksheet
    if _cached_worksheet is not None:
        return _cached_worksheet
    client = _get_sheet_client()
    if not client:
        return None
    try:
        _cached_worksheet = client.open_by_key(SNE_SPREADSHEET_ID).sheet1
        return _cached_worksheet
    except Exception as e:
        logging.error("SNE NA: open_by_key: %s", e)
        return None


def _gspread_call_with_retry(fn, *args, **kwargs):
    """Google Sheets дає 429 при перевищенні read quota — коротка пауза і повтор."""
    last = None
    for attempt in range(4):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            err = str(e)
            if "429" in err or "Quota" in err or "RESOURCE_EXHAUSTED" in err:
                delay = min(12.0, 1.5 * (2**attempt))
                logging.warning("SNE NA: API rate limit, пауза %.1f с (спроба %s)", delay, attempt + 1)
                time.sleep(delay)
                continue
            raise
    raise last


def parse_cell_float(raw) -> float:
    """Парсить число з клітинки; Google/Excel часто дають «−1,5» (Unicode −), float() з таким рядком падає."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip()
    # Нерозривні пробіли тощо
    for sp in ("\u00a0", "\u202f", "\u2009"):
        s = s.replace(sp, "")
    # Unicode-мінус і довге тире → ASCII '-'
    for ch in ("\u2212", "\u2013", "\u2014", "\uFE63", "\uFF0D"):
        s = s.replace(ch, "-")
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        pass
    # Остання спроба: витягнути число з рядка (текст, зайві символи)
    m = re.search(r"-?\s*\d+(?:[.,]\d+)?", s.replace(" ", ""))
    if not m:
        return 0.0
    frag = m.group(0).replace(",", ".").replace(" ", "")
    frag = frag.replace("\u2212", "-").replace("−", "-")
    try:
        return float(frag)
    except ValueError:
        return 0.0


def compute_na_count(e_val: float, f_val: float) -> int:
    """Скільки НА: сума по негативних значеннях у E і F, кожні 1,5 б. = 1 НА."""
    total = 0.0
    for v in (e_val, f_val):
        if v < 0:
            total += abs(v) / NA_POINTS_PER_ONE
    return int(round(total))


def _col_cell(row_vals: list) -> object | None:
    if not row_vals:
        return None
    return row_vals[0] if len(row_vals) > 0 else None


def _normalize_column(col: list, expected_len: int) -> list:
    """Google обрізає кінцеві порожні рядки — доповнюємо до висоти діапазону."""
    out = list(col)
    while len(out) < expected_len:
        out.append([])
    return out[:expected_len]


def read_ef_and_compute_na(list_number: int) -> tuple[int | None, str | None]:
    """
    Читає E{row}, F{row} для рядка курсанта (row = 3 + list_number, як у /sne).
    Повертає (na_count, error_message).
    """
    from gspread.utils import ValueRenderOption

    ws = _get_worksheet()
    if not ws:
        return None, "Google Sheets не налаштовано (credentials / SNE)."
    try:
        row = 3 + list_number
        vr_list = _gspread_call_with_retry(
            ws.batch_get,
            [f"E{row}", f"F{row}"],
            value_render_option=ValueRenderOption.unformatted,
        )
        e_raw = vr_list[0].first() if vr_list else None
        f_raw = vr_list[1].first() if len(vr_list) > 1 else None
        e_v = parse_cell_float(e_raw)
        f_v = parse_cell_float(f_raw)
        na = compute_na_count(e_v, f_v)
        logging.debug(
            "SNE NA list=%s row=%s E=%r F=%r -> e=%s f=%s na=%s",
            list_number,
            row,
            e_raw,
            f_raw,
            e_v,
            f_v,
            na,
        )
        return na, None
    except Exception as e:
        logging.exception("SNE NA read error list_number=%s: %s", list_number, e)
        return None, f"Помилка читання таблиці: {e!s}"


def sync_na_all_from_sheet_for_users(pairs: list[tuple[int, int]]) -> dict[int, tuple[int | None, str | None]]:
    """
    Один batchGet на дві колонки E і F (мін–макс рядок). Рядки не зміщуються, на відміну від
    прямокутника E:F у одному діапазоні, де Google пропускає порожні рядки.

    Паралельно кешуємо worksheet — без десятків викликів spreadsheets.get.

    pairs: (tg_id, list_number). Повертає: tg_id -> (na_count, error_or_None).
    """
    from gspread.utils import ValueRenderOption

    out: dict[int, tuple[int | None, str | None]] = {}
    if not pairs:
        return out

    ws = _get_worksheet()
    if not ws:
        for tg_id, _ in pairs:
            out[tg_id] = (None, "Google Sheets не налаштовано (credentials / SNE).")
        return out

    try:
        rows = [3 + ln for _, ln in pairs]
        min_r, max_r = min(rows), max(rows)
        expected_h = max_r - min_r + 1

        vr_list = _gspread_call_with_retry(
            ws.batch_get,
            [f"E{min_r}:E{max_r}", f"F{min_r}:F{max_r}"],
            value_render_option=ValueRenderOption.unformatted,
        )

        col_e = list(vr_list[0]) if vr_list and len(vr_list) > 0 else []
        col_f = list(vr_list[1]) if len(vr_list) > 1 else []
        col_e = _normalize_column(col_e, expected_h)
        col_f = _normalize_column(col_f, expected_h)

        for tg_id, list_num in pairs:
            row = 3 + list_num
            i = row - min_r
            if i < 0 or i >= expected_h:
                na, err = read_ef_and_compute_na(list_num)
                out[tg_id] = (na, err)
                continue
            e_raw = _col_cell(col_e[i])
            f_raw = _col_cell(col_f[i])
            e_v = parse_cell_float(e_raw)
            f_v = parse_cell_float(f_raw)
            na = compute_na_count(e_v, f_v)
            out[tg_id] = (na, None)

        return out
    except Exception as e:
        logging.exception("SNE NA batch sync: %s", e)
        msg = f"Помилка читання таблиці: {e!s}"
        for tg_id, _ in pairs:
            out[tg_id] = (None, msg)
        return out
