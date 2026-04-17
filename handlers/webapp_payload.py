"""Спільна логіка WebApp (sendData + HTTPS API) без дублювання."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from sqlalchemy import select

from core.config import GROUP_CHAT_ID, MESSAGE_THREAD_ID, POLLS_CONFIG, POLL_DISPLAY_NAMES
from core.zv_helpers import zv_payload
from database.models import User
from database.requests import (
    add_approval_request,
    async_session,
    check_is_admin,
    check_schedule_has_classrooms,
    cleanup_duplicate_approvals,
    clear_schedule_db,
    close_poll_in_db,
    get_active_polls,
    get_all_settings,
    get_approval_by_id,
    get_approvals_by_type,
    get_closed_polls_history,
    get_distance_learning,
    get_pending_approvals_count,
    get_requests_by_user_and_types,
    get_schedule_by_day,
    get_subject_text,
    get_users_count,
    get_users_with_requests,
    get_users_with_requests_by_types,
    notify_admins_about_request,
    process_approval,
    save_new_poll,
    set_setting_value,
    toggle_setting,
    update_user_last_zv_reason,
)

_AUTO_KEYS = (
    "auto_rozvid_1",
    "auto_rozvid_2",
    "auto_dorm_rent",
    "auto_dorm_fund",
    "auto_morning_schedule",
    "auto_zv_reminders",
)


def _ok(text: str, parse_mode: str = "HTML") -> dict[str, Any]:
    return {"ok": True, "text": text, "parse_mode": parse_mode}


def _data(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data}


async def execute_c55_webapp_payload(
    bot: Bot,
    telegram_user_id: int,
    kind: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with async_session() as session:
        db_user = await session.get(User, telegram_user_id)
        if not db_user:
            return _ok("❌ Вас немає в базі. Напишіть /start.")
        user_name = db_user.full_name

    if kind == "c55_admin_webapp":
        if not await check_is_admin(telegram_user_id):
            return _ok("❌ Адмін-панель доступна лише адміністраторам.")

        if action == "admin_stats":
            pending = await get_pending_approvals_count()
            users_total = await get_users_count()
            dorm_users = await get_users_with_requests_by_types(["zv_dorm", "zv_release"])
            city_users = await get_users_with_requests_by_types(["zv_city"])
            other_users = await get_users_with_requests_by_types(
                ["admin_request", "custom_request", "profile_update"]
            )
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
            return _ok(text)

        if action == "admin_confirm_all":
            category = str(payload.get("category", "")).strip()
            if category == "zv_city":
                apps = await get_approvals_by_type("zv_city")
            elif category == "zv_dorm":
                apps = await get_approvals_by_type("zv_dorm")
                apps += await get_approvals_by_type("zv_release")
            else:
                return _ok("❌ Невідома категорія для підтвердження.")

            done = 0
            for app in apps:
                uid = await process_approval(app.id, True)
                if uid:
                    done += 1
                    try:
                        await bot.send_message(uid, "✅ Ваш запит на З/В погоджено!")
                    except Exception:
                        pass
            return _ok(f"✅ Підтверджено запитів: <b>{done}</b>")

        if action == "admin_pending_list":
            category = str(payload.get("category", "")).strip()
            if category == "zv_city":
                types = ["zv_city"]
                title = "🏙 <b>Запити: З/В у місто</b>"
            elif category == "zv_dorm":
                types = ["zv_dorm", "zv_release"]
                title = "🏠 <b>Запити: З/В з гуртожитку</b>"
            elif category == "other":
                types = ["admin_request", "custom_request", "profile_update"]
                title = "📝 <b>Запити: інші</b>"
            else:
                return _ok("❌ Невідома категорія запитів.")

            rows = []
            for t in types:
                rows.extend(await get_approvals_by_type(t))
            if not rows:
                return _ok("✅ У цій категорії немає активних запитів.")
            rows.sort(key=lambda x: x.created_at or datetime.min)

            async with async_session() as session:
                lines = [title, ""]
                for app in rows[:40]:
                    u = await session.get(User, app.user_id)
                    name = u.full_name if u else f"ID {app.user_id}"
                    created = app.created_at.strftime("%d.%m %H:%M") if app.created_at else "?"
                    lines.append(f"• <code>{app.id}</code> | {app.type} | {name} | {created}")
                if len(rows) > 40:
                    lines.append(f"\n… ще {len(rows) - 40} запит(ів)")
            return _ok("\n".join(lines))

        if action == "admin_approval_apply":
            approval_id_raw = payload.get("approval_id")
            decision = str(payload.get("decision", "approve")).strip().lower()
            try:
                approval_id = int(approval_id_raw)
            except Exception:
                return _ok("❌ Некоректний ID запиту.")
            app = await get_approval_by_id(approval_id)
            if not app:
                return _ok("❌ Запит із таким ID не знайдено.")
            approve = decision == "approve"
            uid = await process_approval(approval_id, approve)
            if uid and approve:
                try:
                    await bot.send_message(uid, "✅ Ваш запит погоджено.")
                except Exception:
                    pass
            elif uid and not approve:
                try:
                    await bot.send_message(uid, "❌ Ваш запит відхилено.")
                except Exception:
                    pass
            return _ok(
                f"{'✅' if approve else '🛑'} Оброблено запит <code>{approval_id}</code>: "
                f"<b>{'погоджено' if approve else 'відхилено'}</b>."
            )

        if action == "admin_toggle_auto":
            key = str(payload.get("key", "")).strip()
            if key not in set(_AUTO_KEYS):
                return _ok("❌ Некоректний ключ налаштування.")
            new_val = await toggle_setting(key)
            return _ok(f"⚙️ {key}: <b>{'ON' if new_val else 'OFF'}</b>")

        if action == "admin_set_auto":
            key = str(payload.get("key", "")).strip()
            if key not in set(_AUTO_KEYS):
                return _ok("❌ Некоректний ключ налаштування.")
            on_raw = payload.get("on")
            if isinstance(on_raw, str):
                on = on_raw.lower() in ("true", "1", "yes", "on")
            elif isinstance(on_raw, bool):
                on = on_raw
            else:
                return _ok("❌ Некоректне значення on.")
            await set_setting_value(key, "True" if on else "False")
            return _ok(f"⚙️ {key}: <b>{'ON' if on else 'OFF'}</b>")

        if action == "admin_auto_snapshot":
            settings = await get_all_settings()
            snap = {k: bool(settings.get(k)) for k in _AUTO_KEYS}
            return _data({"settings": snap})

        if action == "admin_auto_status":
            settings = await get_all_settings()
            labels = {
                "auto_rozvid_1": "Розвід 1 відділення",
                "auto_rozvid_2": "Розвід 2 відділення",
                "auto_dorm_rent": "Оренда (гуртожиток)",
                "auto_dorm_fund": "Фонд гуртожитку",
                "auto_morning_schedule": "Розклад 20:00",
                "auto_zv_reminders": "Нагадування З/В",
            }
            lines = ["🤖 <b>Стан авто-опитувань</b>", ""]
            for key in _AUTO_KEYS:
                lines.append(f"• {labels[key]}: <b>{'ON' if settings.get(key) else 'OFF'}</b>")
            return _ok("\n".join(lines))

        if action == "admin_ping_all":
            async with async_session() as session:
                users = (await session.execute(select(User))).scalars().all()
            text = " ".join([f"@{u.username}" for u in users if u.username])
            if not text:
                return _ok("⚠️ Немає курсантів з username у базі.")
            await bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=MESSAGE_THREAD_ID, text=text)
            return _ok("🔔 Усіх пропінговано в групі.")

        if action == "admin_city_report":
            await cleanup_duplicate_approvals("zv_city")
            apps = await get_approvals_by_type("zv_city")
            if not apps:
                return _ok("ℹ️ Немає активних подань у З/В у місто.")
            async with async_session() as session:
                first_dep: list[tuple[int, str]] = []
                second_dep: list[tuple[int, str]] = []
                for app in apps:
                    u = await session.get(User, app.user_id)
                    if not u:
                        continue
                    num = u.list_number if u.list_number is not None else 999
                    label = f"- {u.full_name}"
                    if num <= 14:
                        first_dep.append((num, label))
                    else:
                        second_dep.append((num, label))
            first_dep.sort(key=lambda x: (x[0], x[1]))
            second_dep.sort(key=lambda x: (x[0], x[1]))
            text = (
                "🏙 <b>Звіт по поданнях у З/В у місто</b>\n\n"
                "<b>1 відділення</b>\n"
                + ("\n".join([x[1] for x in first_dep]) if first_dep else "—")
                + "\n\n<b>2 відділення</b>\n"
                + ("\n".join([x[1] for x in second_dep]) if second_dep else "—")
                + f"\n\nРазом: <b>{len(first_dep) + len(second_dep)}</b>"
            )
            return _ok(text)

        if action == "admin_requests_overview":
            users = await get_users_with_requests()
            if not users:
                return _ok("✅ Немає курсантів з активними запитами.")
            lines = ["📋 <b>Курсанти з активними запитами</b>", ""]
            for name, cnt in users[:40]:
                lines.append(f"• {name}: <b>{cnt}</b>")
            if len(users) > 40:
                lines.append(f"\n… і ще {len(users) - 40} курсант(ів)")
            return _ok("\n".join(lines))

        if action == "admin_polls_list":
            polls = await get_active_polls()
            if not polls:
                return _ok("ℹ️ Активних опитувань немає.")
            lines = ["🗳 <b>Активні опитування</b>", ""]
            for p in polls[:25]:
                created = p.created_at.strftime("%d.%m %H:%M") if p.created_at else "?"
                lines.append(f"• {p.type} | id: <code>{p.tg_poll_id}</code> | {created}")
            if len(polls) > 25:
                lines.append(f"\n… і ще {len(polls) - 25}")
            return _ok("\n".join(lines))

        if action == "admin_close_all_polls":
            polls = await get_active_polls()
            if not polls:
                return _ok("ℹ️ Активних опитувань немає.")
            closed = 0
            for p in polls:
                try:
                    await bot.stop_poll(chat_id=p.chat_id, message_id=p.message_id)
                except Exception:
                    pass
                await close_poll_in_db(p.tg_poll_id)
                closed += 1
            return _ok(f"🛑 Закрито опитувань: <b>{closed}</b>")

        if action == "admin_users_overview":
            async with async_session() as session:
                users = (await session.execute(select(User))).scalars().all()
            total = len(users)
            dorm = sum(1 for u in users if u.in_dorm)
            admins = sum(1 for u in users if u.is_admin)
            lines = [
                "👥 <b>Курсанти / користувачі</b>",
                "",
                f"Всього у БД: <b>{total}</b>",
                f"З гуртожитку: <b>{dorm}</b>",
                f"Адмінів: <b>{admins}</b>",
            ]
            return _ok("\n".join(lines))

        if action == "admin_users_list":
            async with async_session() as session:
                users = (
                    await session.execute(select(User).order_by(User.list_number.asc().nulls_last(), User.full_name))
                ).scalars().all()
            if not users:
                return _ok("ℹ️ У базі немає користувачів.")
            lines = ["👥 <b>Список курсантів</b>", ""]
            for u in users[:80]:
                n = u.list_number if u.list_number is not None else "—"
                uname = f" @{u.username}" if u.username else ""
                lines.append(f"• {n}. {u.full_name}{uname}")
            if len(users) > 80:
                lines.append(f"\n… ще {len(users) - 80} користувач(ів)")
            return _ok("\n".join(lines))

        if action == "admin_history_recent":
            try:
                limit_days = int(payload.get("limit_days", 7) or 7)
            except Exception:
                limit_days = 7
            polls = await get_closed_polls_history(limit_days=limit_days)
            if not polls:
                return _ok("ℹ️ Історія порожня (за 7 днів).")
            lines = [f"📊 <b>Історія закритих опитувань (останні {limit_days} дн.)</b>", ""]
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
                lines.append(f"… ще {len(polls) - shown} звіт(ів) за {limit_days} дн.")
            return _ok("\n".join(lines))

        if action == "admin_create_poll":
            poll_type = str(payload.get("poll_type", "")).strip()
            cfg = POLLS_CONFIG.get(poll_type)
            if not cfg:
                return _ok("❌ Невідомий тип опитування.")
            now = datetime.now()
            effective = now + timedelta(days=1) if poll_type == "rozvid_1" else now
            q = cfg["question"].format(date=effective.strftime("%d.%m.%Y"), month=effective.strftime("%B"))
            poll_msg = await bot.send_poll(
                chat_id=GROUP_CHAT_ID,
                message_thread_id=MESSAGE_THREAD_ID,
                question=q,
                options=cfg["options"],
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, poll_type)
            display = POLL_DISPLAY_NAMES.get(poll_type, poll_type)
            return _ok(f"✅ Створено опитування: <b>{display}</b>")

        if action == "admin_custom_poll_create":
            question = str(payload.get("question", "")).strip()
            options = payload.get("options", [])
            if not isinstance(options, list):
                options = []
            options = [str(x).strip() for x in options if str(x).strip()]
            if not question or len(options) < 2 or len(options) > 10:
                return _ok("❌ Потрібне питання і 2-10 варіантів.")
            poll_msg = await bot.send_poll(
                chat_id=GROUP_CHAT_ID,
                message_thread_id=MESSAGE_THREAD_ID,
                question=question,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, "custom")
            return _ok("✅ Власне голосування створено в групі.")

        if action == "admin_schedule_report":
            week = str(payload.get("week", "current")).strip()
            is_next = week == "next"
            days_order = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
            all_lessons = []
            for day in days_order:
                lessons = await get_schedule_by_day(day, is_next_week=is_next)
                all_lessons.extend([(day, l) for l in lessons])
            if not all_lessons:
                return _ok("ℹ️ Розклад порожній для вибраного тижня.")

            dates: dict[str, str] = {}
            for day, l in all_lessons:
                if l.date_str:
                    dates[day] = l.date_str
            date_start = dates.get("Пн", "??")
            date_end = dates.get("Сб", dates.get("Пт", "??"))

            lines = [
                f"📄 <b>Звіт для командира ({'наступний' if is_next else 'поточний'} тиждень)</b>",
                "",
                f"Навчальний тиждень ({date_start} - {date_end})",
                "",
            ]
            for day in days_order:
                day_lessons = [l for d, l in all_lessons if d == day]
                if not day_lessons:
                    continue
                lines.append(f"<b>{day}</b>")
                lines.append(f"С-55, розхід на пари {dates.get(day, '')}")
                for l in day_lessons:
                    loc = l.location_text if l.location_text else l.lesson_text
                    lines.append(f"{l.pair_num} пара: {loc} (28 о/с)")
                lines.append("")
            return _ok("\n".join(lines))

        if action == "admin_schedule_clear":
            week = str(payload.get("week", "current")).strip()
            is_next = week == "next"
            await clear_schedule_db(is_next)
            return _ok(f"✅ Розклад ({'наступний' if is_next else 'поточний'} тиждень) очищено.")

        return _ok("ℹ️ Невідома дія адмін-панелі.")

    if action == "profile_snapshot":
        from handlers.profile import render_profile_text

        async with async_session() as session:
            user = await session.get(User, telegram_user_id)
            if not user:
                return _ok("❌ Вас немає в базі.")
            text = await render_profile_text(user)
            return _ok(text)

    if action == "profile_update_request":
        field = str(payload.get("field", "")).strip()
        new_value = str(payload.get("value", "")).strip()
        allowed = {"fullname", "phone", "address", "listnum", "gender", "dorm"}
        if field not in allowed:
            return _ok("❌ Некоректне поле профілю.")
        async with async_session() as session:
            user = await session.get(User, telegram_user_id)
            if not user:
                return _ok("❌ Вас немає в базі.")
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
                    return _ok("❌ Номер за списком має бути цілим числом.")
                new_value = str(int(new_value))
            elif field in {"gender", "dorm"}:
                if new_value not in {"True", "False"}:
                    return _ok("❌ Для цього поля потрібно True/False.")
            elif not new_value:
                return _ok("❌ Значення не може бути порожнім.")
        await add_approval_request(telegram_user_id, "profile_update", field, old_map[field], new_value)
        await notify_admins_about_request(bot, user_name)
        return _ok("✅ Запит на зміну профілю надіслано.")

    if action == "custom_request":
        text = str(payload.get("text", "")).strip()
        if not text:
            return _ok("❌ Введіть текст запиту.")
        await add_approval_request(telegram_user_id, "custom_request", new_val=text)
        await notify_admins_about_request(bot, user_name)
        return _ok("✅ Ваш запит надіслано адміністраторам.")

    if action == "zv_city_submit":
        await cleanup_duplicate_approvals("zv_city")
        existing = await get_requests_by_user_and_types(telegram_user_id, ["zv_city"])
        if existing:
            return _ok("ℹ️ Ви вже подали себе у З/В у місто. Дублювати заявку не потрібно.")
        await add_approval_request(telegram_user_id, "zv_city", new_val="{}")
        await notify_admins_about_request(bot, user_name)
        return _ok("✅ Подання у Зв у місто надіслано.")

    if action == "zv_dorm_submit":
        date_from = str(payload.get("date_from", "")).strip()
        date_to = str(payload.get("date_to", "")).strip()
        time_from = str(payload.get("time_from", "")).strip()
        time_to = str(payload.get("time_to", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        address_mode = str(payload.get("address_mode", "db")).strip().lower()
        address_manual = str(payload.get("address", "")).strip()
        if not all([date_from, date_to, time_from, time_to, reason]):
            return _ok("❌ Заповніть дату/час і причину.")
        async with async_session() as session:
            user = await session.get(User, telegram_user_id)
            if not user:
                return _ok("❌ Вас немає в базі.")
            if address_mode == "db":
                address = (user.address or "").strip()
                if not address:
                    return _ok("❌ У профілі немає адреси. Оберіть ручний ввід.")
            elif address_mode == "manual":
                if not address_manual:
                    return _ok("❌ Введіть адресу вручну.")
                address = address_manual
            else:
                return _ok("❌ Некоректний режим адреси.")
        payload_json = zv_payload(date_from, time_from, date_to, time_to, reason=reason, address=address)
        await add_approval_request(telegram_user_id, "zv_dorm", new_val=payload_json)
        await update_user_last_zv_reason(telegram_user_id, reason)
        await notify_admins_about_request(bot, user_name)
        return _ok("✅ Запит на Зв з гуртожитку надіслано.")

    if action == "custom_poll_submit":
        question = str(payload.get("question", "")).strip()
        options = payload.get("options", [])
        if not isinstance(options, list):
            options = []
        options = [str(x).strip() for x in options if str(x).strip()]
        if not question or len(options) < 2 or len(options) > 10:
            return _ok("❌ Потрібне питання і 2-10 варіантів.")
        poll_msg = await bot.send_poll(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=MESSAGE_THREAD_ID,
            question=question,
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        await save_new_poll(poll_msg.poll.id, poll_msg.message_id, GROUP_CHAT_ID, "custom")
        return _ok("✅ Власне голосування створено в групі.")

    if action == "schedule_to_chat":
        from schedule_system.formatter import extract_subject_code

        day = str(payload.get("day", "Пн")).strip()
        week = str(payload.get("week", "current")).strip()
        is_next = week == "next"
        lessons = await get_schedule_by_day(day, is_next_week=is_next)
        if not lessons:
            return _ok(f"ℹ️ На {day} пар немає.")
        is_distance = await get_distance_learning(is_next_week=is_next)
        if not is_distance:
            is_distance = not await check_schedule_has_classrooms(is_next_week=is_next)
        title = "Наступний" if is_next else "Поточний"
        text = f"📅 <b>Розклад на {day} ({title})</b>"
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
        return _ok(text)

    return _ok("ℹ️ Дія Web App не розпізнана.")
