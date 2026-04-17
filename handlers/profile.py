from aiogram import Router, F, Bot
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import (
    Message,
    CallbackQuery,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from aiogram.filters import Command

from core.states import EditUser, CustomPoll, CustomRequest, CustomRequestReply
from core.keyboards import get_profile_kb, get_back_btn, get_schedule_kb, get_student_panel_kb
from core.config import MENU_OWNERS, GROUP_CHAT_ID, MESSAGE_THREAD_ID, C55_WEBAPP_URL
from database.requests import (
    async_session, check_is_admin, add_approval_request, backup_user_to_json, get_schedule_by_day, save_new_poll, get_setting,
    notify_admins_about_request, get_approval_by_id, add_approval_correspondence,
    get_distance_learning, get_subject_text, check_schedule_has_classrooms, update_user_last_zv_reason,
    get_pending_approvals_count, get_users_count, get_users_with_requests_by_types,
    get_approvals_by_type, process_approval, toggle_setting, get_all_settings
)
from database.models import User
from core.zv_helpers import zv_payload

router = Router()

router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

def is_owner(callback: CallbackQuery) -> bool:
    owner_id = MENU_OWNERS.get(callback.message.message_id)
    return not owner_id or owner_id == callback.from_user.id


def _c55_webapp_url() -> str:
    """Повертає URL WebApp з cache-busting версією."""
    if not C55_WEBAPP_URL:
        return ""
    parts = urlsplit(C55_WEBAPP_URL)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    # Примусове оновлення кешу Telegram WebView після редизайнів WebApp
    qs["v"] = "20260417d"
    new_query = urlencode(qs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

# Приклади для полів профілю (відображаються при зміні)
EDIT_PROMPTS = {
    "fullname": (
        "✍️ Введіть <b>ПІБ</b> повністю:\n\n"
        "<i>Приклад: Оврашко М.С.</i>"
    ),
    "phone": (
        "✍️ Введіть <b>номер телефону</b>:\n\n"
        "<i>Приклад: 066-100-71-65</i>"
    ),
    "address": (
        "✍️ Введіть <b>адресу</b>:\n\n"
        "<i>Приклад: м. Київ, вул. Хрещатик, 1, кв. 5</i>"
    ),
    "listnum": (
        "✍️ Введіть <b>номер за списком</b> (тільки цифра):\n\n"
        "<i>Приклад: 15</i>"
    ),
}

# --- ГОЛОВНА ПАНЕЛЬ КУРСАНТА ---
@router.message(F.text == "🎓 Панель курсанта")
async def student_panel_cmd(message: Message, state: FSMContext):
    await state.clear()
    if not C55_WEBAPP_URL:
        msg = await message.answer(
            "🎓 <b>Панель курсанта</b>\nОберіть потрібний розділ:",
            reply_markup=get_student_panel_kb(),
            parse_mode="HTML",
        )
        MENU_OWNERS[msg.message_id] = message.from_user.id
        return
    await message.answer(
        "🌐 <b>C55 Web App</b>\nНатисніть кнопку <b>під полем вводу</b>, щоб відкрити єдину панель (курсант/адмін).",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🌐 Відкрити C55 Web App", web_app=WebAppInfo(url=_c55_webapp_url()))],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )

@router.callback_query(F.data == "student_panel_main")
async def student_panel_inline(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await state.clear()
    if C55_WEBAPP_URL:
        await callback.message.edit_text(
            "🎓 <b>C55 Web App</b>\nНатисніть кнопку нижче поля вводу: <b>🌐 Відкрити C55 Web App</b>.",
            reply_markup=get_back_btn("close_panel"),
            parse_mode="HTML",
        )
        await callback.message.answer(
            "⬇️ Кнопка відкриття C55 Web App:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🌐 Відкрити C55 Web App", web_app=WebAppInfo(url=_c55_webapp_url()))],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        return
    await callback.message.edit_text(
        "🎓 <b>Панель курсанта</b>\nОберіть потрібний розділ:",
        reply_markup=get_student_panel_kb(), parse_mode="HTML"
    )

@router.message(F.web_app_data)
async def c55_student_webapp_submit(message: Message, bot: Bot):
    try:
        payload = json.loads(message.web_app_data.data or "{}")
    except Exception:
        return
    kind = str(payload.get("kind", "c55_student_webapp")).strip()
    if kind not in {"c55_student_webapp", "c55_admin_webapp"}:
        return

    action = str(payload.get("action", "")).strip()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            return await message.answer("❌ Вас немає в базі. Напишіть /start.")
        user_name = user.full_name

    if kind == "c55_admin_webapp":
        if not await check_is_admin(message.from_user.id):
            return await message.answer("❌ Адмін-панель доступна лише адміністраторам.")

        if action == "admin_stats":
            pending = await get_pending_approvals_count()
            users_total = await get_users_count()
            dorm_users = await get_users_with_requests_by_types(["zv_dorm", "zv_release"])
            city_users = await get_users_with_requests_by_types(["zv_city"])
            other_users = await get_users_with_requests_by_types(["admin_request", "custom_request", "profile_update"])
            dorm_count = sum(c for _, c in dorm_users)
            city_count = sum(c for _, c in city_users)
            other_count = sum(c for _, c in other_users)
            settings = await get_all_settings()
            text = (
                "⚙️ <b>Статистика адмін-панелі</b>\n\n"
                f"👥 Курсантів у БД: <b>{users_total}</b>\n"
                f"🔔 Запитів очікує: <b>{pending}</b>\n"
                f"🏠 З/В з гурту: <b>{dorm_count}</b>\n"
                f"🏙 З/В у місто: <b>{city_count}</b>\n"
                f"📝 Інші запити: <b>{other_count}</b>\n\n"
                f"🤖 Авто-З/В нагадування: <b>{'ON' if settings.get('auto_zv_reminders') else 'OFF'}</b>\n"
                f"📅 Авто-розклад 20:00: <b>{'ON' if settings.get('auto_morning_schedule') else 'OFF'}</b>"
            )
            return await message.answer(text, parse_mode="HTML")

        if action == "admin_confirm_all":
            category = str(payload.get("category", "")).strip()
            if category == "zv_city":
                apps = await get_approvals_by_type("zv_city")
            elif category == "zv_dorm":
                apps = await get_approvals_by_type("zv_dorm")
                apps += await get_approvals_by_type("zv_release")
            else:
                return await message.answer("❌ Невідома категорія для підтвердження.")

            done = 0
            for app in apps:
                uid = await process_approval(app.id, True)
                if uid:
                    done += 1
                    try:
                        await bot.send_message(uid, "✅ Ваш запит на З/В погоджено!")
                    except Exception:
                        pass
            return await message.answer(f"✅ Підтверджено запитів: <b>{done}</b>", parse_mode="HTML")

        if action == "admin_toggle_auto":
            key = str(payload.get("key", "")).strip()
            allowed = {
                "auto_rozvid_1",
                "auto_rozvid_2",
                "auto_dorm_rent",
                "auto_dorm_fund",
                "auto_morning_schedule",
                "auto_zv_reminders",
            }
            if key not in allowed:
                return await message.answer("❌ Некоректний ключ налаштування.")
            new_val = await toggle_setting(key)
            return await message.answer(f"⚙️ {key}: <b>{'ON' if new_val else 'OFF'}</b>", parse_mode="HTML")

        if action == "admin_ping_all":
            async with async_session() as session:
                users = (await session.execute(select(User))).scalars().all()
            text = " ".join([f"@{u.username}" for u in users if u.username])
            if not text:
                return await message.answer("⚠️ Немає курсантів з username у базі.")
            await bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=MESSAGE_THREAD_ID, text=text)
            return await message.answer("🔔 Усіх пропінговано в групі.")

        return await message.answer("ℹ️ Невідома дія адмін-панелі.")

    if action == "profile_snapshot":
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            if not user:
                return await message.answer("❌ Вас немає в базі.")
            text = await render_profile_text(user)
            return await message.answer(text, parse_mode="HTML")

    if action == "profile_update_request":
        field = str(payload.get("field", "")).strip()
        new_value = str(payload.get("value", "")).strip()
        allowed = {"fullname", "phone", "address", "listnum", "gender", "dorm"}
        if field not in allowed:
            return await message.answer("❌ Некоректне поле профілю.")
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            if not user:
                return await message.answer("❌ Вас немає в базі.")
            old_map = {
                "fullname": user.full_name or "",
                "phone": user.phone_number or "",
                "address": user.address or "",
                "listnum": str(user.list_number or ""),
                "gender": str(user.is_female),
                "dorm": str(user.in_dorm),
            }
            if field == "listnum":
                if not new_value.isdigit() or int(new_value) < 1:
                    return await message.answer("❌ Номер за списком має бути цілим числом.")
                new_value = str(int(new_value))
            elif field in {"gender", "dorm"}:
                if new_value not in {"True", "False"}:
                    return await message.answer("❌ Для цього поля потрібно True/False.")
            elif not new_value:
                return await message.answer("❌ Значення не може бути порожнім.")
        await add_approval_request(message.from_user.id, "profile_update", field, old_map[field], new_value)
        await notify_admins_about_request(bot, user_name)
        return await message.answer("✅ Запит на зміну профілю надіслано.")

    if action == "custom_request":
        text = str(payload.get("text", "")).strip()
        if not text:
            return await message.answer("❌ Введіть текст запиту.")
        await add_approval_request(message.from_user.id, "custom_request", new_val=text)
        await notify_admins_about_request(bot, user_name)
        return await message.answer("✅ Ваш запит надіслано адміністраторам.")

    if action == "zv_city_submit":
        await add_approval_request(message.from_user.id, "zv_city", new_val="{}")
        await notify_admins_about_request(bot, user_name)
        return await message.answer("✅ Подання у Зв у місто надіслано.")

    if action == "zv_dorm_submit":
        date_from = str(payload.get("date_from", "")).strip()
        date_to = str(payload.get("date_to", "")).strip()
        time_from = str(payload.get("time_from", "")).strip()
        time_to = str(payload.get("time_to", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        address_mode = str(payload.get("address_mode", "db")).strip().lower()
        address_manual = str(payload.get("address", "")).strip()
        if not all([date_from, date_to, time_from, time_to, reason]):
            return await message.answer("❌ Заповніть дату/час і причину.")
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            if not user:
                return await message.answer("❌ Вас немає в базі.")
            if address_mode == "db":
                address = (user.address or "").strip()
                if not address:
                    return await message.answer("❌ У профілі немає адреси. Оберіть ручний ввід.")
            elif address_mode == "manual":
                if not address_manual:
                    return await message.answer("❌ Введіть адресу вручну.")
                address = address_manual
            else:
                return await message.answer("❌ Некоректний режим адреси.")
        payload_json = zv_payload(date_from, time_from, date_to, time_to, reason=reason, address=address)
        await add_approval_request(message.from_user.id, "zv_dorm", new_val=payload_json)
        await update_user_last_zv_reason(message.from_user.id, reason)
        await notify_admins_about_request(bot, user_name)
        return await message.answer("✅ Запит на Зв з гуртожитку надіслано.")

    if action == "custom_poll_submit":
        question = str(payload.get("question", "")).strip()
        options = payload.get("options", [])
        if not isinstance(options, list):
            options = []
        options = [str(x).strip() for x in options if str(x).strip()]
        if not question or len(options) < 2 or len(options) > 10:
            return await message.answer("❌ Потрібне питання і 2-10 варіантів.")
        poll_msg = await bot.send_poll(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=MESSAGE_THREAD_ID,
            question=question,
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, "custom")
        return await message.answer("✅ Власне голосування створено в групі.")

    if action == "schedule_to_chat":
        day = str(payload.get("day", "Пн")).strip()
        week = str(payload.get("week", "current")).strip()
        is_next = (week == "next")
        lessons = await get_schedule_by_day(day, is_next_week=is_next)
        if not lessons:
            return await message.answer(f"ℹ️ На {day} пар немає.")
        is_distance = await get_distance_learning(is_next_week=is_next)
        if not is_distance:
            is_distance = not await check_schedule_has_classrooms(is_next_week=is_next)
        title = "Наступний" if is_next else "Поточний"
        text = f"📅 <b>Розклад на {day} ({title})</b>"
        if is_distance:
            text += " — дистанційно"
        text += "\n\n"
        from schedule_system.formatter import extract_subject_code
        for l in lessons:
            text += f"<b>{l.pair_num} пара:</b> {l.lesson_text}\n"
            if is_distance:
                code = extract_subject_code(l.lesson_text)
                if code:
                    subj_text = await get_subject_text(code)
                    if subj_text:
                        text += subj_text + "\n"
        return await message.answer(text, parse_mode="HTML")

    await message.answer("ℹ️ Дія Web App не розпізнана.")

@router.callback_query(F.data == "request_menu")
async def request_menu(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await state.clear()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📝 Свій запит (довільний текст)", callback_data="req_custom_text")
    b.button(text="📋 Подати себе у Зв", callback_data="req_zv_menu")
    b.button(text="🔙 Назад", callback_data="student_panel_main")
    b.adjust(1)
    await callback.message.edit_text(
        "📝 <b>Подати запит</b>\n\nОберіть тип:",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "req_zv_menu")
async def req_zv_menu(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await state.clear()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🏙 Звільнення в місто", callback_data="req_zv_city_start")
    b.button(text="🏠 Зв з гуртожитку", callback_data="req_zv_dorm_start")
    b.button(text="🔙 Назад", callback_data="request_menu")
    b.adjust(1)
    await callback.message.edit_text(
        "📋 <b>Подача у Зв</b>\n\nОберіть тип подачі:",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "req_custom_text")
async def req_custom_text(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await state.set_state(CustomRequest.waiting_for_request_text)
    await callback.message.edit_text(
        "✍️ <b>Ваш текстовий запит</b>\n\nНапишіть текст. Адміністратор розгляне його та відповість:",
        reply_markup=get_back_btn("request_menu"),
        parse_mode="HTML",
    )

@router.message(CustomRequest.waiting_for_request_text, F.text)
async def custom_request_submit(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    if not text:
        return await message.answer("⚠️ Введіть текст запиту.")
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await state.clear()
            return await message.answer("Вас немає в базі. Напишіть /start.")
        user_name = user.full_name
    await add_approval_request(message.from_user.id, 'custom_request', new_val=text)
    await notify_admins_about_request(bot, user_name)
    await state.clear()
    await message.answer("✅ Ваш запит надіслано! Очікуйте відповіді від адміністратора.", reply_markup=get_back_btn("student_panel_main"))

@router.callback_query(F.data.startswith("reply_to_request_"))
async def reply_to_request_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    app_id = int(callback.data.replace("reply_to_request_", ""))
    app = await get_approval_by_id(app_id)
    if not app or app.user_id != callback.from_user.id:
        return await callback.answer("Запит не знайдено.", show_alert=True)
    await state.update_data(reply_to_app_id=app_id)
    await state.set_state(CustomRequestReply.waiting_for_reply)
    await callback.message.edit_text("✍️ Напишіть вашу відповідь на запитання адміна:")
    await callback.answer()

@router.message(CustomRequestReply.waiting_for_reply, F.text)
async def reply_to_request_submit(message: Message, state: FSMContext):
    data = await state.get_data()
    app_id = data.get("reply_to_app_id")
    if not app_id:
        await state.clear()
        return
    app = await get_approval_by_id(app_id)
    if not app or app.user_id != message.from_user.id:
        await message.answer("Запит не знайдено.")
        await state.clear()
        return
    await add_approval_correspondence(app_id, "student_answer", message.text.strip())
    await state.clear()
    await message.answer("✅ Відповідь надіслано! Адміністратор її перегляне.")

@router.callback_query(F.data == "close_panel")
async def close_panel_handler(callback: CallbackQuery):
    if not is_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    await callback.answer("Панель закрито")
    try:
        await callback.message.delete()
    except Exception:
        pass

# --- ПРОФІЛЬ ---
async def render_profile_text(user: User) -> str:
    dorm_status = "🏠 В гуртожитку" if user.in_dorm else "🏙 Киянин"
    phone = user.phone_number or "Не вказано"
    addr = user.address or "Не вказано"
    list_num = user.list_number if user.list_number is not None else "Не вказано"
    gender_str = "Жіноча 👩" if user.is_female else "Чоловіча 👨"
    
    na = getattr(user, "na_count", 0) or 0
    viol = getattr(user, "violations_count", 0) or 0
    return (f"👤 <b>Профіль курсанта:</b>\n"
            f"<b>ПІБ:</b> {user.full_name}\n"
            f"<b>Стать:</b> {gender_str}\n"
            f"<b>№ за списком:</b> {list_num}\n"
            f"<b>Телефон:</b> {phone}\n"
            f"<b>Адреса:</b> {addr}\n"
            f"<b>НА (неатестацій):</b> {na}\n"
            f"<b>Порушень:</b> {viol}\n"
            f"<b>Статус:</b> {dorm_status}")

@router.callback_query(F.data == "my_profile_inline")
async def process_my_profile_inline(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            return await callback.answer("Вас немає в базі. Напишіть /start.", show_alert=True)
        text = await render_profile_text(user)
        await callback.message.edit_text(text, reply_markup=get_profile_kb(user.tg_id), parse_mode="HTML")

@router.callback_query(F.data.startswith("edit_"))
async def process_edit_profile(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    
    data = await state.get_data()
    target_id = data.get("target_user_id", callback.from_user.id)
    
    field = callback.data.replace("edit_", "")
    is_admin = await check_is_admin(callback.from_user.id)

    # dorm, gender — тогли (одразу змінює адмін; курсант — тільки через запит)
    if field in ['dorm', 'gender']:
        async with async_session() as session:
            user = await session.get(User, target_id)
            if not user: return
            
            if is_admin:
                if field == 'dorm': user.in_dorm = not user.in_dorm
                else: user.is_female = not user.is_female
                await session.commit()
                await backup_user_to_json(user)
                is_other = (target_id != callback.from_user.id)
                text = await render_profile_text(user)
                await callback.message.edit_text(text, reply_markup=get_profile_kb(target_id, is_admin_mode=is_other), parse_mode="HTML")
            else:
                old_val = str(user.in_dorm) if field == 'dorm' else str(user.is_female)
                new_val = str(not user.in_dorm) if field == 'dorm' else str(not user.is_female)
                await add_approval_request(user.tg_id, 'profile_update', field, old_val, new_val)
                await callback.answer("⏳ Запит відправлено! Зміна з’явиться після підтвердження вкладці «Запити».", show_alert=True)
        return

    # fullname, phone, address, listnum — текст (адмін змінює одразу, курсант — через запит)
    prompt = EDIT_PROMPTS.get(field, "✍️ Введіть нове значення:")
    await state.update_data(field=field)
    await state.set_state(EditUser.waiting_for_text)
    
    back_target = f"view_user_{target_id}" if target_id != callback.from_user.id else "my_profile_inline"
    await callback.message.edit_text(prompt, reply_markup=get_back_btn(back_target), parse_mode="HTML")

@router.message(EditUser.waiting_for_text)
async def process_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_user_id", message.from_user.id)
    field = data['field']
    
    val = message.text.strip()
    if field == 'listnum' and (not val.isdigit() or int(val) < 1):
        await message.answer("⚠️ Введіть коректний номер (наприклад: 15)")
        return

    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user: return

        is_admin = await check_is_admin(message.from_user.id)

        if is_admin:
            # Адмін змінює одразу в обхід запитів
            if field == 'fullname': user.full_name = val
            elif field == 'phone': user.phone_number = val
            elif field == 'address': user.address = val
            elif field == 'listnum': user.list_number = int(val)
            await session.commit()
            await backup_user_to_json(user)
            text = await render_profile_text(user)
            is_other = (target_id != message.from_user.id)
            await message.answer("✅ Дані оновлено!")
            await message.answer(text, reply_markup=get_profile_kb(target_id, is_admin_mode=is_other), parse_mode="HTML")
            await state.clear()
            # Зберігаємо target_user_id, щоб при наступній зміні (2-а, 3-я...) не переключалося на адміна
            if is_other:
                await state.update_data(target_user_id=target_id)
        else:
            # Курсант: створюємо запит, зміна — після підтвердження в «Запити»
            old_map = {'fullname': user.full_name, 'phone': user.phone_number or '', 'address': user.address or '', 'listnum': str(user.list_number or '')}
            new_val = str(int(val)) if field == 'listnum' else val
            await add_approval_request(user.tg_id, 'profile_update', field, old_map.get(field, ''), new_val)
            await message.answer("⏳ Запит надіслано! Зміна з’явиться після підтвердження адміном у вкладці «Запити».")
            await state.clear()

@router.callback_query(F.data.startswith("view_user_"))
async def process_view_user_admin(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.replace("view_user_", ""))
    
    # ОБОВ'ЯЗКОВО ЗБЕРІГАЄМО ID курсанта, щоб бот знав, кого ми редагуємо
    await state.update_data(target_user_id=target_id)
    
    from database.requests import async_session
    from database.models import User
    
    async with async_session() as session:
        user = await session.get(User, target_id)
        if user:
            # Тут має бути твоя функція генерації тексту профілю (наприклад, get_user_profile_text)
            text = await render_profile_text(user) 
            
            # ГОЛОВНЕ: is_admin_mode=True включає всі кнопки керування (ПІБ, телефон, видалення)
            from core.keyboards import get_profile_kb
            await callback.message.edit_text(
                text, 
                reply_markup=get_profile_kb(target_id, is_admin_mode=True), 
                parse_mode="HTML"
            )

@router.callback_query(F.data.startswith("delete_user_"))
async def process_delete_user(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return await callback.answer("❌ Немає прав!", show_alert=True)
    
    target_tg_id = int(callback.data.replace("delete_user_", ""))
    from database.requests import delete_user_from_db
    await delete_user_from_db(target_tg_id)
    await callback.message.edit_text("✅ Курсанта успішно видалено з бази даних.", reply_markup=get_back_btn("menu_main"))


# --- СТВОРЕННЯ ВЛАСНОГО ГОЛОСУВАННЯ (СТАРА СИСТЕМА) ---
@router.callback_query(F.data.startswith("custom_poll_start_"))
async def custom_poll_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    mode = callback.data.split("_")[3] # admin або student
    await state.update_data(mode=mode)
    
    kb = get_back_btn("menu_main" if mode == "admin" else "student_panel_main")
    
    text = (
        "✍️ <b>Створення власного голосування</b>\n\n"
        "Напишіть повідомлення у такому форматі (питання, а під ним варіанти через дефіс):\n\n"
        "<b>Тест</b>\n"
        "- Тест1\n"
        "- Тест2\n"
        "- Тест3\n\n"
        "<i>Мінімум 2 варіанти відповідей.</i>"
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(CustomPoll.waiting_for_poll_data)

@router.message(CustomPoll.waiting_for_poll_data)
async def process_custom_poll_data(message: Message, state: FSMContext, bot: Bot):
    lines = message.text.strip().split('\n')
    if len(lines) < 3:
        return await message.answer("⚠️ Неправильний формат!\nМає бути одне питання і мінімум 2 варіанти відповідей (кожен з дефісом).")
    
    question = lines[0].strip()
    options = []
    
    for line in lines[1:]:
        line = line.strip()
        if line.startswith('-'):
            options.append(line[1:].strip())
            
    if len(options) < 2 or len(options) > 10:
        return await message.answer("⚠️ Варіантів відповідей (з дефісом на початку) має бути від 2 до 10!\nСпробуйте ще раз:")
    
    data = await state.get_data()
    mode = data.get('mode', 'student')
    
    try:
        poll_msg = await bot.send_poll(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=MESSAGE_THREAD_ID,
            question=question,
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False
        )
        await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, "custom")
        
        kb = get_back_btn("menu_main" if mode == "admin" else "student_panel_main")
        await message.answer("✅ Ваше голосування успішно надіслано в групу!", reply_markup=kb)
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
    
    await state.clear()


# --- РОЗКЛАД (КУРСАНТИ) ---
@router.callback_query(F.data == "user_sch_current")
async def user_sch_curr(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    await callback.message.edit_text(
        "📅 <b>Розклад С-55 (Поточний)</b>\nОберіть день тижня:",
        reply_markup=get_schedule_kb(mode="student", is_next_week=False),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "user_sch_next")
async def user_sch_next(callback: CallbackQuery):
    if not is_owner(callback): return await callback.answer("❌ Не ваше меню!", show_alert=True)
    await callback.message.edit_text(
        "📅 <b>Розклад С-55 (Наступний)</b>\nОберіть день тижня:",
        reply_markup=get_schedule_kb(mode="student", is_next_week=True),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("sch_view_"))
async def sch_view_day(callback: CallbackQuery):
    if not is_owner(callback):
        return await callback.answer("❌ Не ваше меню!", show_alert=True)
    parts = callback.data.split("_")
    is_next = (parts[2] == "next")
    day = parts[3]
    mode = parts[4] if len(parts) > 4 else "student"
    
    lessons = await get_schedule_by_day(day, is_next_week=is_next)
    
    if not lessons:
        return await callback.answer(f"На {day} пар немає (СР)", show_alert=True)
    
    from database.requests import get_distance_learning, get_subject_text, check_schedule_has_classrooms
    from schedule_system.formatter import extract_subject_code
    
    # Явний прапорець з завантаження (онлайн) або fallback: розклад без аудиторій = дистанційно
    is_distance = await get_distance_learning(is_next_week=is_next)
    if not is_distance:
        has_classrooms = await check_schedule_has_classrooms(is_next_week=is_next)
        is_distance = not has_classrooms
    word = "Наступний" if is_next else "Поточний"
    text = f"📅 <b>Розклад на {day} ({word})</b>"
    if is_distance:
        text += " — дистанційно"
    text += "\n\n"
    for l in lessons:
        text += f"<b>{l.pair_num} пара:</b> {l.lesson_text}\n"
        if is_distance:
            code = extract_subject_code(l.lesson_text)
            if code:
                subj_text = await get_subject_text(code)
                if subj_text:
                    text += subj_text + "\n"
    
    back_btn = f"{'admin' if mode == 'admin' else 'user'}_sch_{'next' if is_next else 'current'}"
    await callback.message.edit_text(text, reply_markup=get_back_btn(back_btn), parse_mode="HTML")


@router.message(Command("get_admin"))
async def cmd_get_admin(message: Message):
    from database.requests import add_approval_request
    await add_approval_request(message.from_user.id, 'admin_request')
    await message.answer("⏳ Запит на отримання прав адміністратора надіслано командирам на розгляд.")