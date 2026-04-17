import logging
import os
import re
import pdfplumber
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from aiogram.exceptions import TelegramBadRequest

from core.states import AdminPanel, CustomPoll, CustomRequestResponse
from core.keyboards import (
    get_main_menu_kb, 
    get_poll_types_keyboard, 
    get_active_polls_keyboard,
    get_users_list_kb, 
    get_history_days_kb, 
    get_history_polls_kb, 
    get_history_report_kb,
    get_auto_polls_kb, 
    get_back_btn,
    get_approvals_users_kb,
    get_approvals_categories_kb,
    get_approvals_users_kb_filtered,
    get_user_requests_kb,
    get_approval_action_kb,
    get_schedule_kb
)
from core.config import GROUP_CHAT_ID, MESSAGE_THREAD_ID, SCHEDULE_THREAD_ID, POLLS_CONFIG, POLL_DISPLAY_NAMES, MENU_OWNERS, C55_WEBAPP_URL, C55_WEBAPP_API_URL
from database.requests import (
    get_setting, toggle_setting, check_is_admin, save_new_poll, 
    get_active_polls, async_session,
    get_closed_polls_history, get_poll_by_tg_id, save_poll_report_text, get_all_settings,
    update_schedule_in_db, clear_schedule_db, get_schedule_by_day,
    get_users_with_requests, get_users_with_requests_by_types, get_requests_by_user, get_requests_by_user_and_types,
    get_approval_by_id, delete_approval, process_approval, get_approvals_by_type,
    set_distance_learning, get_approval_correspondence, export_db_to_xlsx, clear_all_polls_from_db,
    get_zv_week_report_html, apply_discipline_by_list_number,
)
from database.models import Poll, User
from handlers.polls import generate_report
from schedule_system.extractor import get_raw_schedule
from schedule_system.formatter import parse_lesson

router = Router()


def _c55_webapp_url(is_admin: bool = False) -> str:
    if not C55_WEBAPP_URL:
        return ""
    parts = urlsplit(C55_WEBAPP_URL)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    qs["v"] = "20260417t"
    qs["is_admin"] = "1" if is_admin else "0"
    if C55_WEBAPP_API_URL:
        qs["api"] = C55_WEBAPP_API_URL
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(qs), parts.fragment))


@router.message(Command("discipline"))
async def cmd_discipline(message: Message):
    """НА з таблиці SNE (E, F); порушення — зміна від поточного значення."""
    if not await check_is_admin(message.from_user.id):
        await message.answer("❌ Команда лише для адміністраторів.")
        return
    parts = (message.text or "").split()
    if len(parts) not in (2, 3):
        await message.answer(
            "Формат: <code>/discipline номер_у_списку [зміна_порушень]</code>\n\n"
            "<b>НА</b> береться з Google Таблиці (стовпці <b>E</b> і <b>F</b>): "
            "сума негативних балів, кожні <b>1,5 б.</b> = <b>1 НА</b>.\n\n"
            "<b>Порушення</b> — відносна зміна: <code>+2</code> додати два, <code>-1</code> зняти одне.\n\n"
            "Приклади:\n"
            "<code>/discipline 15</code> — лише оновити НА з таблиці\n"
            "<code>/discipline 15 2</code> — +2 порушення та оновити НА\n"
            "<code>/discipline 15 -1</code> — зняти 1 порушення та оновити НА\n\n"
            "<i>При кожному виклику НА з таблиці оновлюється для всіх курсантів у базі (хто має номер у списку).</i>",
            parse_mode="HTML",
        )
        return
    try:
        list_num = int(parts[1])
    except ValueError:
        await message.answer("Номер у списку має бути цілим числом.")
        return
    viol_delta = None
    if len(parts) == 3:
        try:
            viol_delta = int(parts[2])
        except ValueError:
            await message.answer(
                "Зміна порушень має бути цілим числом (наприклад <code>-2</code>).",
                parse_mode="HTML",
            )
            return
    ok, text = await apply_discipline_by_list_number(list_num, viol_delta)
    await message.answer(text, parse_mode="HTML" if ok else None)


@router.message(Command("clear_polls"))
async def cmd_clear_polls(message: Message):
    """Повне очищення таблиці опитувань у БД (лише адміни)."""
    if not await check_is_admin(message.from_user.id):
        await message.answer("❌ Команда доступна лише адміністраторам.")
        return
    n = await clear_all_polls_from_db()
    await message.answer(
        f"✅ Очищено БД: видалено <b>{n}</b> запис(ів) опитувань. "
        f"Пов’язані голоси (votes) видалено автоматично.\n\n"
        f"<i>У Telegram повідомлення-опитування лишаються; бот більше не прив’язаний до них.</i>",
        parse_mode="HTML",
    )


@router.message(Command("db_export"))
async def cmd_db_export(message: Message, bot: Bot):
    """Експорт бази даних в Google Таблиці (.xlsx). Тільки для адмінів."""
    if not await check_is_admin(message.from_user.id):
        await message.answer("❌ Ця команда доступна лише адміністраторам.")
        return
    path = None
    try:
        await message.answer("⏳ Формування експорту...")
        path = await export_db_to_xlsx()
        from datetime import datetime
        filename = f"c55_db_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        doc = FSInputFile(path, filename=filename)
        await message.answer_document(doc, caption="📦 Експорт бази даних (Google Таблиці / Excel)")
    except Exception as e:
        logging.error(f"db_export error: {e}")
        await message.answer(f"❌ Помилка експорту: {e}")
    finally:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass


def is_owner(callback: CallbackQuery) -> bool:
    owner_id = MENU_OWNERS.get(callback.message.message_id)
    return not owner_id or owner_id == callback.from_user.id

@router.message(F.text == "⚙️ Панель адміністратора")
async def admin_panel_cmd(message: Message, state: FSMContext):
    if not await check_is_admin(message.from_user.id): return
    await state.clear()
    if C55_WEBAPP_URL:
        await message.answer(
            "🌐 <b>C55 Web App</b>\nНатисніть кнопку <b>під полем вводу</b>, щоб відкрити єдину панель.",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🌐 Відкрити C55 Web App", web_app=WebAppInfo(url=_c55_webapp_url(is_admin=True)))],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        return
    try:
        await message.delete()
    except Exception:
        pass
    from database.requests import get_pending_approvals_count
    apps_count = await get_pending_approvals_count()
    msg = await message.answer(
        "⚙️ <b>Панель управління</b>\nОберіть дію:", 
        reply_markup=get_main_menu_kb(True, apps_count), parse_mode="HTML"
    )
    MENU_OWNERS[msg.message_id] = message.from_user.id

@router.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    from database.requests import get_pending_approvals_count
    apps_count = await get_pending_approvals_count()
    await callback.message.edit_text(
        "⚙️ <b>Панель управління</b>\nОберіть дію:",
        reply_markup=get_main_menu_kb(True, apps_count), parse_mode="HTML"
    )

@router.callback_query(F.data == "menu_start_poll")
async def process_menu_start_poll(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await callback.message.edit_text("Оберіть тип опитування (Шаблони):", reply_markup=get_poll_types_keyboard())

@router.callback_query(F.data.startswith("start_poll_"))
async def create_poll(callback: CallbackQuery, bot: Bot):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    poll_type = callback.data.replace("start_poll_", "")
    config = POLLS_CONFIG.get(poll_type)
    if not config: return
    
    now = datetime.now()
    effective_dt = now + timedelta(days=1) if poll_type == "rozvid_1" else now
    date_str = effective_dt.strftime("%d.%m.%Y")
    question = config["question"].format(date=date_str, month=effective_dt.strftime("%B"))
    
    try:
        poll_msg = await bot.send_poll(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=MESSAGE_THREAD_ID,
            question=question,
            options=config["options"],
            is_anonymous=False,
            allows_multiple_answers=False
        )

        await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, poll_type)
        poll_name = POLL_DISPLAY_NAMES.get(poll_type, poll_type)
        await callback.message.edit_text(f"✅ Опитування «{poll_name}» успішно створено!", reply_markup=get_back_btn("menu_main"))
    except TelegramBadRequest as e:
        await callback.answer(f"❌ Помилка: бота немає в групі або немає прав.", show_alert=True)
        logging.error(e)

@router.callback_query(F.data == "menu_close_polls")
async def process_menu_close_polls(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    polls = await get_active_polls()
    if not polls:
        return await callback.message.edit_text("✅ Немає активних опитувань для закриття.", reply_markup=get_back_btn("menu_main"))
    await callback.message.edit_text("Оберіть опитування для примусового закриття:", reply_markup=get_active_polls_keyboard(polls))

@router.callback_query(F.data.startswith("close_poll_"))
async def close_specific_poll(callback: CallbackQuery, bot: Bot):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    tg_poll_id = callback.data.replace("close_poll_", "")
    await force_close_poll(tg_poll_id, bot, callback.message)
    await process_menu_close_polls(callback)

@router.callback_query(F.data == "menu_users")
async def process_menu_users(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    async with async_session() as session:
        users = (await session.execute(select(User).order_by(User.list_number.asc().nulls_last(), User.full_name))).scalars().all()
    await callback.message.edit_text("👥 <b>Список курсантів:</b>", reply_markup=get_users_list_kb(users), parse_mode="HTML")

@router.callback_query(F.data == "menu_history")
async def process_menu_history(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    polls = await get_closed_polls_history()
    if not polls: return await callback.message.edit_text("Історія порожня (зберігається 7 днів).", reply_markup=get_back_btn("menu_main"))
    
    dates = []
    for p in polls:
        d_str = p.created_at.strftime('%d.%m.%Y')
        if d_str not in dates: dates.append(d_str)
        
    await callback.message.edit_text("📅 Оберіть дату:", reply_markup=get_history_days_kb(dates))

@router.callback_query(F.data.startswith("hist_day_"))
async def process_hist_day(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    date_str = callback.data.replace("hist_day_", "")
    target_date = datetime.strptime(date_str, "%d.%m.%Y").date()
    polls = await get_closed_polls_history()
    day_polls = [p for p in polls if p.created_at.date() == target_date]
    await callback.message.edit_text(f"Опитування за {date_str}:", reply_markup=get_history_polls_kb(day_polls, date_str))

@router.callback_query(F.data.startswith("hist_poll_"))
async def process_hist_poll(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    tg_poll_id = callback.data.replace("hist_poll_", "")
    poll = await get_poll_by_tg_id(tg_poll_id)
    if poll and poll.report_text:
        date_str = poll.created_at.strftime('%d.%m.%Y')
        await callback.message.edit_text(f"📄 <b>Звіт:</b>\n\n{poll.report_text}", reply_markup=get_history_report_kb(date_str), parse_mode="HTML")
    else:
        await callback.answer("Звіт не знайдено", show_alert=True)

@router.callback_query(F.data == "menu_auto_polls")
async def process_menu_auto_polls(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    settings = await get_all_settings()
    await callback.message.edit_text("⚙️ <b>Налаштування авто-опитувань:</b>", reply_markup=get_auto_polls_kb(settings), parse_mode="HTML")

@router.callback_query(F.data.startswith("toggle_auto_"))
async def process_toggle_auto(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    key = callback.data.replace("toggle_", "")
    await toggle_setting(key)
    await process_menu_auto_polls(callback)

async def force_close_poll(tg_poll_id: str, bot: Bot, message_obj: Message):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        poll = await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
        if not poll or not poll.is_active: return
        try:
            stopped_poll = await bot.stop_poll(chat_id=poll.chat_id, message_id=poll.message_id)
            poll.is_active = False 
            await session.commit()
            report_text, silent_text = await generate_report(stopped_poll, tg_poll_id)
            await save_poll_report_text(tg_poll_id, report_text + "\n\n" + silent_text)
            await bot.send_message(chat_id=poll.chat_id, message_thread_id=MESSAGE_THREAD_ID, text=f"🛑 <b>ПРИМУСОВЕ ЗАКРИТТЯ</b>\n\n{report_text}", parse_mode="HTML")
            await bot.send_message(chat_id=poll.chat_id, message_thread_id=MESSAGE_THREAD_ID, text=silent_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Force close error: {e}")

@router.callback_query(F.data == "menu_approvals")
async def process_menu_approvals(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ви викликали меню!", show_alert=True)
    await state.clear()
    dorm_users = await get_users_with_requests_by_types(["zv_dorm", "zv_release"])
    city_users = await get_users_with_requests_by_types(["zv_city"])
    other_users = await get_users_with_requests_by_types(["admin_request", "custom_request", "profile_update"])
    counts = {
        "zv_dorm": sum(c for _, c in dorm_users),
        "zv_city": sum(c for _, c in city_users),
        "other": sum(c for _, c in other_users),
    }
    await callback.message.edit_text(
        "🔔 <b>Запити</b>\n\nОберіть категорію:",
        reply_markup=get_approvals_categories_kb(counts),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_approvals_zv_dorm")
async def process_menu_approvals_zv_dorm(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ви викликали меню!", show_alert=True)
    users_with_counts = await get_users_with_requests_by_types(["zv_dorm", "zv_release"])
    await callback.message.edit_text(
        "🏠 <b>Запити: Зв від гурту</b>",
        reply_markup=get_approvals_users_kb_filtered(users_with_counts, "zv_dorm"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_approvals_zv_city")
async def process_menu_approvals_zv_city(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ви викликали меню!", show_alert=True)
    users_with_counts = await get_users_with_requests_by_types(["zv_city"])
    await callback.message.edit_text(
        "🏙 <b>Запити: Зв у місто</b>",
        reply_markup=get_approvals_users_kb_filtered(users_with_counts, "zv_city", show_city_report=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_approvals_other")
async def process_menu_approvals_other(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ви викликали меню!", show_alert=True)
    users_with_counts = await get_users_with_requests_by_types(["admin_request", "custom_request", "profile_update"])
    await callback.message.edit_text(
        "📝 <b>Запити: Інше</b>",
        reply_markup=get_approvals_users_kb_filtered(users_with_counts, "other"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "approvals_back_zv_dorm")
async def approvals_back_zv_dorm(callback: CallbackQuery):
    await process_menu_approvals_zv_dorm(callback)


@router.callback_query(F.data == "approvals_back_zv_city")
async def approvals_back_zv_city(callback: CallbackQuery):
    await process_menu_approvals_zv_city(callback)


@router.callback_query(F.data == "approvals_back_other")
async def approvals_back_other(callback: CallbackQuery):
    await process_menu_approvals_other(callback)


@router.callback_query(F.data.regexp(r"^approvals_user_(zv_dorm|zv_city|other)_\d+$"))
async def process_approvals_user(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ви викликали меню!", show_alert=True)
    payload = callback.data.replace("approvals_user_", "")
    category, user_id_str = payload.rsplit("_", 1)
    user_id = int(user_id_str)
    if category == "zv_dorm":
        apps = await get_requests_by_user_and_types(user_id, ["zv_dorm", "zv_release"])
    elif category == "zv_city":
        apps = await get_requests_by_user_and_types(user_id, ["zv_city"])
    else:
        apps = await get_requests_by_user_and_types(user_id, ["admin_request", "custom_request", "profile_update"])
    if not apps:
        await callback.answer("Запити вже оброблені", show_alert=True)
        if category == "zv_dorm":
            await process_menu_approvals_zv_dorm(callback)
        elif category == "zv_city":
            await process_menu_approvals_zv_city(callback)
        else:
            await process_menu_approvals_other(callback)
        return
    async with async_session() as session:
        user = await session.get(User, user_id)
        name = user.full_name if user else "?"
    await callback.message.edit_text(
        f"📋 <b>Запити від {name}:</b>",
        reply_markup=get_user_requests_kb(apps, user_id, name, category=category),
        parse_mode="HTML",
    )

@router.callback_query(F.data.startswith("view_app_"))
async def process_view_app(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    app_id = int(callback.data.replace("view_app_", ""))
    app = await get_approval_by_id(app_id)
    if not app:
        return await callback.answer("Запит не знайдено", show_alert=True)
    async with async_session() as session:
        user = await session.get(User, app.user_id)
        user_name = user.full_name if user else "?"
    text = f"📝 <b>Запит від {user_name}:</b>\n\n"
    if app.type == 'admin_request':
        text += "🚀 Бажає отримати права АДМІНІСТРАТОРА"
        kb = get_approval_action_kb(app_id, is_custom=False, back_to_user_id=app.user_id)
    elif app.type in ('zv_release', 'zv_dorm'):
        from core.zv_helpers import parse_zv_payload, format_zv_admin_report
        import html as html_lib
        data = parse_zv_payload(app.new_value)
        if data and user:
            body = format_zv_admin_report(user, data)
            text += "<pre>" + html_lib.escape(body) + "</pre>"
        else:
            text += "(не вдалося прочитати дані Зв)"
        kb = get_approval_action_kb(app_id, is_custom=True, back_to_user_id=app.user_id)
    elif app.type == 'zv_city':
        list_num = user.list_number if user and user.list_number is not None else "?"
        text += f"🏙 Запит на <b>Зв у місто</b>\n№ за списком: <b>{list_num}</b>"
        kb = get_approval_action_kb(app_id, is_custom=True, back_to_user_id=app.user_id)
    elif app.type == 'custom_request':
        text += app.new_value or "(порожній запит)"
        kb = get_approval_action_kb(app_id, is_custom=True, back_to_user_id=app.user_id)
    else:
        fields_map = {'fullname': 'ПІБ', 'phone': 'Телефон', 'address': 'Адреса', 'listnum': 'Номер за списком', 'gender': 'Стать', 'dorm': 'Гуртожиток'}
        text += f"Зміна поля: <b>{fields_map.get(app.field, app.field)}</b>\n"
        text += f"Старе значення: {app.old_value or '—'}\n"
        text += f"Нове значення: <b>{app.new_value or '—'}</b>"
        kb = get_approval_action_kb(app_id, is_custom=False, back_to_user_id=app.user_id, use_full_buttons=True)
    corr = await get_approval_correspondence(app_id)
    if corr:
        text += "\n\n<b>📬 Переписка:</b>\n"
        for item in corr:
            role_label = "Адмін" if item.get("role") == "admin_question" else "Курсант"
            text += f"<i>{role_label}:</i> {item.get('text', '')}\n"
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "approvals_city_report")
async def approvals_city_report(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    apps = await get_approvals_by_type("zv_city")
    if not apps:
        return await callback.answer("Немає подань у Зв у місто.", show_alert=True)
    async with async_session() as session:
        first_dep: list[str] = []
        second_dep: list[str] = []
        for app in apps:
            u = await session.get(User, app.user_id)
            if not u:
                continue
            num = u.list_number if u.list_number is not None else 999
            label = f"{u.list_number if u.list_number is not None else '?'} — {u.full_name}"
            if num <= 14:
                first_dep.append(label)
            else:
                second_dep.append(label)
    first_dep.sort()
    second_dep.sort()
    text = (
        "у Звільнення у місто йдуть і так:\n"
        "1 відділення\n"
        + ("\n".join(first_dep) if first_dep else "—")
        + "\n\n2 відділення\n"
        + ("\n".join(second_dep) if second_dep else "—")
    )
    await callback.message.answer(text)
    await callback.answer("Звіт надіслано")


@router.callback_query(F.data == "approvals_confirm_all_zv_city")
async def approvals_confirm_all_zv_city(callback: CallbackQuery, bot: Bot):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    apps = await get_approvals_by_type("zv_city")
    done = 0
    for app in apps:
        user_id = await process_approval(app.id, True)
        if user_id:
            done += 1
            try:
                await bot.send_message(user_id, "✅ Запит на звільнення погоджено!")
            except Exception:
                pass
    await callback.answer(f"Підтверджено: {done}", show_alert=True)
    await process_menu_approvals_zv_city(callback)


@router.callback_query(F.data == "approvals_confirm_all_zv_dorm")
async def approvals_confirm_all_zv_dorm(callback: CallbackQuery, bot: Bot):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    apps = await get_approvals_by_type("zv_dorm")
    legacy = await get_approvals_by_type("zv_release")
    done = 0
    for app in apps + legacy:
        user_id = await process_approval(app.id, True)
        if user_id:
            done += 1
            try:
                await bot.send_message(user_id, "✅ Запит на звільнення погоджено!")
            except Exception:
                pass
    await callback.answer(f"Підтверджено: {done}", show_alert=True)
    await process_menu_approvals_zv_dorm(callback)

@router.callback_query(F.data.regexp(r"^app_(yes|no)_\d+$"))
async def process_app_decision(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return await callback.answer("❌ Немає прав!", show_alert=True)
    parts = callback.data.split("_")
    approved = (parts[1] == "yes")
    app_id = int(parts[2])
    user_id = await process_approval(app_id, approved)
    if user_id:
        msg = "✅ Ваш запит на зміну даних підтверджено!" if approved else "❌ Ваш запит на зміну даних відхилено адміністратором."
        try: await bot.send_message(user_id, msg)
        except: pass
    await callback.answer("Готово!")
    await process_menu_approvals(callback)

@router.callback_query(F.data.startswith("app_custom_yes_"))
async def app_custom_yes(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_custom_yes_", ""))
    app = await get_approval_by_id(app_id)
    if not app:
        await callback.answer("Запит не знайдено", show_alert=True)
        return
    if app.type in ('zv_release', 'zv_dorm', 'zv_city'):
        user_id = await process_approval(app_id, True)
        msg = "✅ Запит на звільнення погоджено!"
    else:
        user_id = await delete_approval(app_id)
        msg = "✅ Ваш запит погоджено!"
    if user_id:
        try:
            await bot.send_message(user_id, msg)
        except Exception:
            pass
    await callback.answer("Готово!")
    await process_menu_approvals(callback, state)

@router.callback_query(F.data.startswith("app_custom_no_"))
async def app_custom_no(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_custom_no_", ""))
    app = await get_approval_by_id(app_id)
    if not app:
        await callback.answer("Запит не знайдено", show_alert=True)
        return
    if app.type in ('zv_release', 'zv_dorm', 'zv_city'):
        user_id = await process_approval(app_id, False)
        msg = "❌ Запит на звільнення відхилено."
    else:
        user_id = await delete_approval(app_id)
        msg = "❌ Ваш запит відхилено."
    if user_id:
        try:
            await bot.send_message(user_id, msg)
        except Exception:
            pass
    await callback.answer("Готово!")
    await process_menu_approvals(callback, state)


@router.callback_query(F.data == "export_zv_week")
async def export_zv_week(callback: CallbackQuery):
    if not is_owner(callback):
        return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    text = await get_zv_week_report_html()
    if len(text) <= 4000:
        await callback.message.answer(text, parse_mode="HTML")
    else:
        for i in range(0, len(text), 3800):
            await callback.message.answer(text[i : i + 3800], parse_mode="HTML")
    await callback.answer("Надіслано")

def _get_back_to_approvals_btn(app: object) -> object:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="menu_approvals")]])

@router.callback_query(F.data.startswith("app_custom_manual_"))
async def app_custom_manual(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_custom_manual_", ""))
    await state.update_data(custom_req_app_id=app_id, custom_req_action="manual", custom_req_is_profile=False)
    await state.set_state(CustomRequestResponse.waiting_for_manual_text)
    await callback.message.edit_text("✍️ Напишіть відповідь курсанту:", reply_markup=get_back_btn("menu_approvals"))

@router.callback_query(F.data.startswith("app_profile_manual_"))
async def app_profile_manual(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_profile_manual_", ""))
    await state.update_data(custom_req_app_id=app_id, custom_req_action="manual", custom_req_is_profile=True)
    await state.set_state(CustomRequestResponse.waiting_for_manual_text)
    app = await get_approval_by_id(app_id)
    back_btn = _get_back_to_approvals_btn(app) if app else get_back_btn("menu_approvals")
    await callback.message.edit_text("✍️ Напишіть відповідь курсанту:", reply_markup=back_btn)

@router.callback_query(F.data.startswith("app_custom_question_"))
async def app_custom_question(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_custom_question_", ""))
    await state.update_data(custom_req_app_id=app_id, custom_req_action="question", custom_req_is_profile=False)
    await state.set_state(CustomRequestResponse.waiting_for_question_text)
    await callback.message.edit_text("❓ Напишіть запитання для курсанта:", reply_markup=get_back_btn("menu_approvals"))

@router.callback_query(F.data.startswith("app_profile_question_"))
async def app_profile_question(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    app_id = int(callback.data.replace("app_profile_question_", ""))
    await state.update_data(custom_req_app_id=app_id, custom_req_action="question", custom_req_is_profile=True)
    await state.set_state(CustomRequestResponse.waiting_for_question_text)
    app = await get_approval_by_id(app_id)
    back_btn = _get_back_to_approvals_btn(app) if app else get_back_btn("menu_approvals")
    await callback.message.edit_text("❓ Напишіть запитання для курсанта:", reply_markup=back_btn)

@router.message(CustomRequestResponse.waiting_for_manual_text, F.text)
@router.message(CustomRequestResponse.waiting_for_question_text, F.text)
async def process_custom_req_response(message: Message, state: FSMContext, bot: Bot):
    if not await check_is_admin(message.from_user.id): return
    data = await state.get_data()
    app_id = data.get("custom_req_app_id")
    action = data.get("custom_req_action")
    is_profile = data.get("custom_req_is_profile", False)
    if not app_id:
        await state.clear()
        return
    app = await get_approval_by_id(app_id)
    if not app:
        await message.answer("Запит не знайдено.")
        await state.clear()
        return
    text = message.text.strip()
    user_id = app.user_id
    back_btn = _get_back_to_approvals_btn(app)
    if action == "manual":
        prefix = "📩 Відповідь адміна: "
        try:
            await bot.send_message(user_id, prefix + text)
        except Exception as e:
            await message.answer(f"Не вдалося надіслати: {e}")
        await delete_approval(app_id)
        await state.clear()
        await message.answer("✅ Відправлено курсанту!", reply_markup=back_btn)
    else:
        from database.requests import add_approval_correspondence
        await add_approval_correspondence(app_id, "admin_question", text)
        prefix = "❓ Запитання від адміна: "
        from core.keyboards import get_reply_to_request_kb
        try:
            await bot.send_message(user_id, prefix + text, reply_markup=get_reply_to_request_kb(app_id))
        except Exception as e:
            await message.answer(f"Не вдалося надіслати: {e}")
        await state.clear()
        await message.answer("✅ Запитання надіслано! Запит залишається відкритим.", reply_markup=back_btn)

@router.callback_query(F.data == "admin_sch_current")
async def admin_sch_curr(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    await callback.message.edit_text(
        "📅 <b>Керування розкладом (Поточний)</b>\nВиберіть дію:",
        reply_markup=get_schedule_kb(mode="admin", is_next_week=False),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_sch_next")
async def admin_sch_next(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    await callback.message.edit_text(
        "📅 <b>Керування розкладом (Наступний)</b>\nВиберіть дію:",
        reply_markup=get_schedule_kb(mode="admin", is_next_week=True),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("sch_upd_"))
async def sch_update_pdf(callback: CallbackQuery):
    parts = callback.data.split("_")
    is_next = "next" in callback.data
    is_online = "online" in callback.data
    if is_online:
        cmd = "/upd_sch_online_next" if is_next else "/upd_sch_online"
    else:
        cmd = "/upd_sch_next" if is_next else "/upd_sch"
    hint = "онлайн (дистанційно)" if is_online else "очно"
    await callback.message.edit_text(
        f"📥 Надішліть PDF розкладу <b>{hint}</b> в цей чат з підписом:\n<code>{cmd}</code>",
        reply_markup=get_back_btn("admin_sch_next" if is_next else "admin_sch_current"),
        parse_mode="HTML"
    )

# =========================================================================
# ВЕРСІЯ №2: ТІЛЬКИ ДЛЯ КОМАНДИРА (ГЕНЕРУЄТЬСЯ ЛИШЕ ПО КНОПЦІ)
# =========================================================================
@router.callback_query(F.data.startswith("sch_rep_"))
async def generate_schedule_report_btn(callback: CallbackQuery):
    is_next = "next" in callback.data
    days_order = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
    
    all_lessons = []
    for day in days_order:
        lessons = await get_schedule_by_day(day, is_next_week=is_next)
        all_lessons.extend([(day, l) for l in lessons])
        
    if not all_lessons:
        return await callback.answer("Розклад порожній!", show_alert=True)
        
    dates = {}
    for day, l in all_lessons:
        if l.date_str: dates[day] = l.date_str
        
    date_start = dates.get("Пн", "??")
    date_end = dates.get("Сб", dates.get("Пт", "??"))
    
    # ФОРМУЄМО ТВОЮ ІДЕАЛЬНУ ВЕРСІЮ
    commander_report = f"Навчальний тиждень ({date_start} - {date_end})\n\n"
    for day in days_order:
        day_lessons = [l for d, l in all_lessons if d == day]
        if day_lessons:
            commander_report += f"{day}\nС-55, розхід на пари {dates.get(day, '')}\n"
            for l in day_lessons:
                loc = l.location_text if l.location_text else l.lesson_text
                commander_report += f"{l.pair_num} пара: {loc} (28 о/с)\n"
            commander_report += "\n"
            
    await callback.message.answer(f"📄 <b>Звіт для командира:</b>\n\n<pre>{commander_report.strip()}</pre>", parse_mode="HTML")
    await callback.answer("Звіт згенеровано!", show_alert=False)

# =========================================================================
# ВЕРСІЯ №1: ДЛЯ СТУДЕНТІВ (ВІДПРАВЛЯЄТЬСЯ У ТРЕД ПІСЛЯ ЗАВАНТАЖЕННЯ)
# =========================================================================
SCHEDULE_CAPTIONS = ["/upd_sch", "/upd_sch_next", "/upd_sch_online", "/upd_sch_online_next"]

@router.message(F.document, F.caption.in_(SCHEDULE_CAPTIONS))
async def handle_schedule_pdf(message: Message, bot: Bot):
    if not await check_is_admin(message.from_user.id): return
    cap = (message.caption or "").strip()
    is_next = "next" in cap
    is_online = "online" in cap
    
    os.makedirs("schedule_system/data", exist_ok=True)
    file_path = "schedule_system/data/current_schedule.pdf"
    
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, file_path)
    
    file_name = message.document.file_name
    # ISZZI_30_ (підкреслення) або ISZZI_30.pdf (крапка)
    match = re.search(r'ISZZI_(\d+)_', file_name) or re.search(r'ISZZI_(\d+)\.', file_name)
    week_num = match.group(1) if match else "?"

    dates = {}
    try:
        with pdfplumber.open(file_path) as pdf:
            text = pdf.pages[0].extract_text()
            matches = re.findall(r"(Понеділок|Вівторок|Середа|Четвер|П'ятниця|Субота)\s+(\d{2}\.\d{2})", text)
            day_map = {"Понеділок": "Пн", "Вівторок": "Вт", "Середа": "Ср", "Четвер": "Чт", "П'ятниця": "Пт", "Субота": "Сб"}
            for day_full, date_short in matches:
                dates[day_map[day_full]] = date_short
    except:
        pass

    try:
        from schedule_system import config as sch_cfg
        sch_cfg.PDF_FILENAME = "current_schedule.pdf"
        
        raw_data = get_raw_schedule() 
        formatted = []
        for item in raw_data:
            parsed = parse_lesson(item['raw_text'])
            d_str = dates.get(item['day'])
            if parsed: 
                formatted.append({
                    'day': item['day'], 
                    'pair': item['pair'], 
                    'text': parsed['full'], 
                    'loc_text': parsed['loc'], 
                    'date_str': d_str
                })
        
        await update_schedule_in_db(formatted, is_next_week=is_next)
        await set_distance_learning(is_next, is_online)
        
        date_start = dates.get("Пн", "??")
        date_end = dates.get("Пт", "??")
        days_order = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
        
        # СТУДЕНТСЬКИЙ ЗВІТ ДЛЯ ГРУПИ (при онлайн — з текстами з /options)
        student_report = f"📅 <b>Розклад на {week_num}-ий навчальний тиждень ({date_start} - {date_end})</b>"
        if is_online:
            student_report += " — дистанційно"
        student_report += "\n\n"
        
        if is_online:
            from schedule_system.formatter import extract_subject_code
            from database.requests import get_subject_text
            for day in days_order:
                day_lessons = [l for l in formatted if l['day'] == day]
                if day_lessons:
                    student_report += f"<b>{day} ({dates.get(day, '')})</b>\n"
                    for l in day_lessons:
                        student_report += f"<b>{l['pair']} пара:</b> {l['text']}\n"
                        code = extract_subject_code(l['text'])
                        if code:
                            subj_text = await get_subject_text(code)
                            if subj_text:
                                student_report += subj_text + "\n"
                    student_report += "\n"
        else:
            for day in days_order:
                day_lessons = [l for l in formatted if l['day'] == day]
                if day_lessons:
                    student_report += f"<b>{day} ({dates.get(day, '')})</b>\n"
                    for l in day_lessons:
                        student_report += f"<b>{l['pair']} пара:</b> {l['text']}\n"
                    student_report += "\n"
        
        await message.answer("✅ <b>Розклад успішно завантажено та відправлено студентам у тред!</b>\n\n<i>Щоб сформувати звіт для командирів, натисніть кнопку «📄 Згенерувати звіт» у меню розкладу.</i>", parse_mode="HTML")
        
        # Відправляємо СТУДЕНТСЬКУ версію в групу
        target_thread = SCHEDULE_THREAD_ID if SCHEDULE_THREAD_ID else MESSAGE_THREAD_ID
        await bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=target_thread, text=student_report.strip())
        
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@router.callback_query(F.data.startswith("sch_clear_"))
async def sch_clear(callback: CallbackQuery):
    is_next = "next" in callback.data
    from database.requests import clear_schedule_db
    await clear_schedule_db(is_next)
    
    # Замість того, щоб перезавантажувати сторінку і ловити краш, просто виводимо сповіщення:
    await callback.answer("✅ Розклад успішно очищено!", show_alert=True)
    
    # Спробуємо оновити меню, але якщо текст не змінився - ігноруємо помилку
    try:
        if is_next:
            await admin_sch_next(callback)
        else:
            await admin_sch_curr(callback)
    except TelegramBadRequest:
        pass # Якщо повідомлення таке ж саме, бот просто проігнорує помилку і не зависне
    
@router.callback_query(F.data == "ping_all")
async def ping_all_users_handler(callback: CallbackQuery, bot: Bot):
    if not is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    from database.requests import async_session
    from database.models import User
    from sqlalchemy import select
    from core.config import GROUP_CHAT_ID, MESSAGE_THREAD_ID
    
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        
    # Бот збере ТІЛЬКИ теги, без жодних слів
    text = " ".join([f"@{u.username}" for u in users if u.username])

    if text:
        await bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=MESSAGE_THREAD_ID, text=text)
        await callback.answer("🔔 Усіх пропінговано!", show_alert=True)
    else:
        await callback.answer("⚠️ Немає курсантів з username у базі.", show_alert=True)

@router.callback_query(F.data == "close_all_polls")
async def close_all_polls_handler(callback: CallbackQuery, bot: Bot):
    from database.requests import get_active_polls, close_poll_in_db
    
    # Отримуємо всі активні опитування з бази
    active_polls = await get_active_polls()
    
    if not active_polls:
        return await callback.answer("🛑 Немає активних опитувань для закриття.", show_alert=True)
        
    closed_count = 0
    for p in active_polls:
        try:
            # Зупиняємо опитування в самому Telegram
            await bot.stop_poll(chat_id=p.chat_id, message_id=p.message_id)
            # Помічаємо його як закрите в базі даних
            await close_poll_in_db(p.tg_poll_id)
            closed_count += 1
        except Exception as e:
            # Якщо опитування вже було видалене вручну, просто пропускаємо
            print(f"Не вдалося закрити {p.tg_poll_id}: {e}")
            continue
            
    await callback.answer(f"✅ Успішно закрито {closed_count} опитувань!", show_alert=True)
    
    # Видаляємо повідомлення з кнопками, щоб оновити інтерфейс
    try:
        await callback.message.delete()
    except:
        pass