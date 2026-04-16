"""Запит «на звільнення»: Mini App для гуртожитку + legacy fallback."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.states import ZvRelease
from core.config import MENU_OWNERS, ZV_DORM_WEBAPP_URL
from core.zv_helpers import zv_payload, parse_zv_payload
from database.models import User
from database.requests import (
    async_session,
    add_approval_request,
    notify_admins_about_request,
    update_user_last_zv_reason,
)

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

TIME_SLOTS = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]


def _is_owner(callback: CallbackQuery) -> bool:
    owner_id = MENU_OWNERS.get(callback.message.message_id)
    return not owner_id or owner_id == callback.from_user.id


def _time_to_cb(t: str) -> str:
    return t.replace(":", "")


def _cb_to_time(s: str) -> str:
    if len(s) == 4 and s.isdigit():
        return f"{s[:2]}:{s[2:]}"
    return "08:00"


async def _is_dorm_user(user_id: int) -> bool:
    async with async_session() as session:
        user = await session.get(User, user_id)
        return bool(user and user.in_dorm)


def _is_valid_date(raw: str) -> bool:
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_valid_time(raw: str) -> bool:
    try:
        datetime.strptime(raw, "%H:%M")
        return True
    except Exception:
        return False


def _dates_kb(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    today = date.today()
    for i in range(14):
        d = today + timedelta(days=i)
        b.button(text=d.strftime("%d.%m"), callback_data=f"{prefix}{d.isoformat()}")
    b.adjust(4)
    return b.as_markup()


def _times_kb(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in TIME_SLOTS:
        b.button(text=t, callback_data=f"{prefix}{_time_to_cb(t)}")
    b.button(text="✏️ Інший час", callback_data=f"{prefix}other")
    b.adjust(4)
    return b.as_markup()


def _address_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📍 Взяти з профілю (БД)", callback_data="zv_addr_db")
    b.button(text="✏️ Ввести свою адресу", callback_data="zv_addr_manual")
    b.button(text="🔙 Скасувати", callback_data="student_panel_main")
    b.adjust(1)
    return b.as_markup()


def _reason_kb(last_reason: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✍️ Ввести причину текстом", callback_data="zv_reason_type_new")
    if last_reason:
        short = (last_reason[:40] + "…") if len(last_reason) > 40 else last_reason
        b.button(text=f"♻️ Остання: {short}", callback_data="zv_reason_type_last")
    b.button(text="🔙 Скасувати", callback_data="student_panel_main")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "req_zv_city_start")
async def zv_city_start(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not _is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await _is_dorm_user(callback.from_user.id):
        return await callback.answer("Подання Зв доступне лише курсантам із гуртожитку.", show_alert=True)
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            return await callback.answer("Вас немає в базі.", show_alert=True)
    await add_approval_request(callback.from_user.id, "zv_city", new_val="{}")
    await notify_admins_about_request(bot, user.full_name)
    await callback.message.edit_text(
        "✅ Подання у <b>Зв у місто</b> надіслано адміністраторам.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 До панелі курсанта", callback_data="student_panel_main")]]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


async def _start_zv_dorm_legacy_flow(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    notice_html: str | None = None,
):
    if not _is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await _is_dorm_user(callback.from_user.id):
        return await callback.answer("Подання Зв доступне лише курсантам із гуртожитку.", show_alert=True)
    await state.clear()
    await state.set_state(None)
    await state.update_data(zv_step="df", zv_kind="zv_dorm")
    body = "📋 <b>Звільнення</b>\n\nОберіть <b>дату початку</b>:"
    text = f"{notice_html}\n\n{body}" if notice_html else body
    await callback.message.edit_text(
        text,
        reply_markup=_dates_kb("zvdf_"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "req_zv_dorm_start")
async def zv_dorm_start(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await _is_dorm_user(callback.from_user.id):
        return await callback.answer("Подання Зв доступне лише курсантам із гуртожитку.", show_alert=True)
    url = (ZV_DORM_WEBAPP_URL or "").strip()
    # Telegram приймає web_app лише з https://; http або відсутній URL — сценарій у боті
    if not url:
        return await _start_zv_dorm_legacy_flow(
            callback,
            state,
            notice_html="⚠️ <b>ZV_DORM_WEBAPP_URL</b> не задано — подання через кроки нижче.",
        )
    if not url.lower().startswith("https://"):
        return await _start_zv_dorm_legacy_flow(
            callback,
            state,
            notice_html=(
                "🔒 У Telegram кнопка Mini App працює лише з <b>HTTPS</b> (не з http://). "
                "Подайте Зв через кроки нижче або вкажіть у .env HTTPS-адресу (тунель / домен з TLS)."
            ),
        )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗓 Відкрити календар Зв", web_app=WebAppInfo(url=url))],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="req_zv_menu")],
        ]
    )
    await callback.message.edit_text(
        "🏠 <b>Зв з гуртожитку</b>\n\nВідкрийте Mini App та оберіть дату/час початку і завершення.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.web_app_data)
async def zv_dorm_webapp_submit(message: Message, state: FSMContext, bot: Bot):
    if not await _is_dorm_user(message.from_user.id):
        return await message.answer("Подання Зв доступне лише курсантам із гуртожитку.")
    try:
        payload = json.loads(message.web_app_data.data or "{}")
    except Exception:
        return await message.answer("❌ Не вдалося прочитати дані з Mini App.")
    if payload.get("kind") != "zv_dorm_webapp":
        return

    date_from = str(payload.get("date_from", "")).strip()
    date_to = str(payload.get("date_to", "")).strip()
    time_from = str(payload.get("time_from", "")).strip()
    time_to = str(payload.get("time_to", "")).strip()

    if not (_is_valid_date(date_from) and _is_valid_date(date_to) and _is_valid_time(time_from) and _is_valid_time(time_to)):
        return await message.answer("❌ Некоректна дата або час. Спробуйте ще раз у Mini App.")

    payload_json = zv_payload(date_from, time_from, date_to, time_to, reason="MiniApp", address="")
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            return await message.answer("Вас немає в базі. Напишіть /start.")

    await add_approval_request(message.from_user.id, "zv_dorm", new_val=payload_json)
    await notify_admins_about_request(bot, user.full_name)
    await state.clear()
    await message.answer("✅ Запит на Зв з гуртожитку надіслано адміністраторам.")


@router.callback_query(F.data == "req_zv_start")
async def zv_start(callback: CallbackQuery, state: FSMContext):
    await _start_zv_dorm_legacy_flow(callback, state)


@router.callback_query(F.data.startswith("zvdf_"))
async def zv_pick_date_from(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    raw = callback.data.replace("zvdf_", "")
    await state.update_data(date_from=raw, zv_step="tf")
    await callback.message.edit_text(
        "🕐 Оберіть <b>час початку</b>:",
        reply_markup=_times_kb("zvtf_"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("zvtf_"))
async def zv_pick_time_from(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    suf = callback.data.replace("zvtf_", "")
    if suf == "other":
        await state.set_state(ZvRelease.waiting_custom_time_from)
        await callback.message.edit_text(
            "Введіть час початку у форматі <b>ГГ:ХХ</b> (наприклад 16:30):",
            parse_mode="HTML",
        )
        await callback.answer()
        return
    tf = _cb_to_time(suf)
    await state.update_data(time_from=tf, zv_step="dt")
    await callback.message.edit_text(
        "📅 Оберіть <b>дату закінчення</b>:",
        reply_markup=_dates_kb("zvdt_"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ZvRelease.waiting_custom_time_from, F.text)
async def zv_custom_time_from(message: Message, state: FSMContext):
    t = message.text.strip().replace(" ", "")
    if len(t) not in (4, 5) or ":" not in t:
        return await message.answer("Формат: ГГ:ХХ (наприклад 16:30)")
    parts = t.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return await message.answer("Формат: ГГ:ХХ")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return await message.answer("Некоректний час")
    tf = f"{h:02d}:{m:02d}"
    await state.update_data(time_from=tf, zv_step="dt")
    await state.set_state(None)
    await message.answer(
        "📅 Оберіть <b>дату закінчення</b>:",
        reply_markup=_dates_kb("zvdt_"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("zvdt_"))
async def zv_pick_date_to(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    raw = callback.data.replace("zvdt_", "")
    await state.update_data(date_to=raw, zv_step="tt")
    await callback.message.edit_text(
        "🕐 Оберіть <b>час закінчення</b>:",
        reply_markup=_times_kb("zvtt_"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("zvtt_"))
async def zv_pick_time_to(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    suf = callback.data.replace("zvtt_", "")
    if suf == "other":
        await state.set_state(ZvRelease.waiting_custom_time_to)
        await callback.message.edit_text(
            "Введіть час закінчення у форматі <b>ГГ:ХХ</b>:",
            parse_mode="HTML",
        )
        await callback.answer()
        return
    tt = _cb_to_time(suf)
    await state.update_data(time_to=tt)
    await _zv_show_address_step(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.message(ZvRelease.waiting_custom_time_to, F.text)
async def zv_custom_time_to(message: Message, state: FSMContext):
    t = message.text.strip().replace(" ", "")
    if len(t) < 4 or ":" not in t:
        return await message.answer("Формат: ГГ:ХХ")
    parts = t.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return await message.answer("Формат: ГГ:ХХ")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return await message.answer("Некоректний час")
    tt = f"{h:02d}:{m:02d}"
    await state.update_data(time_to=tt)
    await state.set_state(None)
    await _zv_show_address_step_msg(message, state, message.from_user.id)


async def _zv_show_address_step(message: Message, state: FSMContext, user_id: int):
    await message.edit_text(
        "📍 <b>Адреса звільнення</b>\n\nОберіть джерело адреси:",
        reply_markup=_address_kb(),
        parse_mode="HTML",
    )


async def _zv_show_address_step_msg(message: Message, state: FSMContext, user_id: int):
    await message.answer(
        "📍 <b>Адреса звільнення</b>\n\nОберіть джерело адреси:",
        reply_markup=_address_kb(),
        parse_mode="HTML",
    )


async def _zv_show_reason_step_msg(message: Message, state: FSMContext, user_id: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        last = (user.last_zv_reason or "").strip() if user else ""
    data = await state.get_data()
    await message.answer(
        "📝 <b>Причина звільнення</b>",
        reply_markup=_reason_kb(last or None),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "zv_addr_db")
async def zv_addr_from_db(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        addr = (user.address or "").strip() if user else ""
    if not addr:
        return await callback.answer(
            "Немає адреси в профілі. Додайте її в профілі або оберіть «Ввести свою адресу».",
            show_alert=True,
        )
    await state.update_data(zv_address=addr)
    await _zv_show_reason_step(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "zv_addr_manual")
async def zv_addr_manual_start(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    await state.set_state(ZvRelease.waiting_address_text)
    await callback.message.edit_text(
        "Введіть адресу звільнення одним повідомленням:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="student_panel_main")]]
        ),
    )
    await callback.answer()


@router.message(ZvRelease.waiting_address_text, F.text)
async def zv_address_text_done(message: Message, state: FSMContext):
    addr = message.text.strip()
    if not addr:
        return await message.answer("Введіть адресу.")
    await state.update_data(zv_address=addr)
    await state.set_state(None)
    await _zv_show_reason_step_msg(message, state, message.from_user.id)


async def _zv_show_reason_step(message: Message, state: FSMContext, user_id: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        last = (user.last_zv_reason or "").strip() if user else ""
    await message.edit_text(
        "📝 <b>Причина звільнення</b>",
        reply_markup=_reason_kb(last or None),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "zv_reason_type_new")
async def zv_reason_new(callback: CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        return await callback.answer()
    await state.set_state(ZvRelease.waiting_reason_text)
    await callback.message.edit_text(
        "Опишіть причину одним повідомленням:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="student_panel_main")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "zv_reason_type_last")
async def zv_reason_last(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not _is_owner(callback):
        return await callback.answer()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            return await callback.answer("Немає в базі", show_alert=True)
        reason = (user.last_zv_reason or "").strip()
        if not reason:
            return await callback.answer("Немає збереженої причини", show_alert=True)
    await _zv_submit(callback.from_user.id, state, bot, reason)
    await callback.message.edit_text("✅ Запит на звільнення надіслано адміністраторам.")
    await state.clear()
    await callback.answer()


@router.message(ZvRelease.waiting_reason_text, F.text)
async def zv_reason_text_done(message: Message, state: FSMContext, bot: Bot):
    reason = message.text.strip()
    if not reason:
        return await message.answer("Введіть текст причини.")
    await _zv_submit(message.from_user.id, state, bot, reason)
    await state.clear()
    await message.answer("✅ Запит на звільнення надіслано адміністраторам.")


async def _zv_submit(user_id: int, state: FSMContext, bot: Bot, reason: str):
    data = await state.get_data()
    df = data.get("date_from")
    tf = data.get("time_from")
    dt = data.get("date_to")
    tt = data.get("time_to")
    req_type = data.get("zv_kind") or "zv_dorm"
    if not all([df, tf, dt, tt]):
        logging.error("ZV submit: incomplete state %s", data)
        return
    addr = (data.get("zv_address") or "").strip()
    payload = zv_payload(df, tf, dt, tt, reason, address=addr)
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return
        name = user.full_name
    await add_approval_request(user_id, req_type, new_val=payload)
    await update_user_last_zv_reason(user_id, reason)
    await notify_admins_about_request(bot, name)
