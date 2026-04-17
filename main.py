import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Імпорт налаштувань та клавіатур
from core.config import (
    BOT_TOKEN,
    GROUP_CHAT_ID,
    MESSAGE_THREAD_ID,
    SCHEDULE_THREAD_ID,
    POLLS_CONFIG,
    C55_WEBAPP_URL,
    C55_WEBAPP_API_URL,
    C55_WEBAPP_API_HOST,
    C55_WEBAPP_API_PORT,
)
from core.keyboards import get_reply_kb
from core.bot_commands import setup_bot_commands, build_help_text

# Імпорт логіки бази даних
from database.requests import (
    init_db, check_is_admin, add_or_update_user, is_user_registered,
    get_pending_approvals_count, get_setting, 
    save_new_poll, cleanup_old_polls, add_approval_request,
    get_schedule_by_day, promote_next_week_schedule,
    get_distance_learning, get_stale_approvals, get_admins,
    get_db_path, get_users_count, cleanup_expired_zv_approvals,
    delete_all_zv_approved_reports, get_users_for_zv_city_reminder,
    get_users_for_zv_general_deadline_reminder, cleanup_daily_zv_city_submissions,
)

from handlers.admin import router as admin_router
from handlers.polls import router as polls_router
from handlers.profile import router as profile_router
from handlers.zv_release import router as zv_release_router
from handlers.options import router as options_router
from handlers.sne import router as sne_router

logging.basicConfig(level=logging.INFO)

def _c55_webapp_url(is_admin: bool = False) -> str:
    if not C55_WEBAPP_URL:
        return ""
    parts = urlsplit(C55_WEBAPP_URL)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    qs["v"] = "20260417s"
    qs["is_admin"] = "1" if is_admin else "0"
    if C55_WEBAPP_API_URL:
        qs["api"] = C55_WEBAPP_API_URL
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(qs), parts.fragment))


def _schedule_zv_cleanup():
    import asyncio
    asyncio.get_event_loop().create_task(_zv_cleanup_async())


async def _zv_cleanup_async():
    n = await cleanup_expired_zv_approvals()
    if n:
        logging.info("Зв: видалено прострочених запитів: %s", n)


async def _zv_sunday_archive_cleanup():
    """Щонеділі 23:59 — очищення архіву погоджених подань Зв у БД."""
    n = await delete_all_zv_approved_reports()
    if n:
        logging.info("Зв: очищено архів погоджених подань у БД (%s записів)", n)


async def _zv_city_daily_cleanup():
    """Щоденне очищення подань «Зв у місто» наприкінці дня."""
    n = await cleanup_daily_zv_city_submissions()
    if n:
        logging.info("Зв у місто: щоденно очищено подань (%s записів)", n)


async def auto_poll_job(bot: Bot, poll_type: str):
    setting_key = f"auto_{poll_type}"
    is_enabled = await get_setting(setting_key)
    if is_enabled != True: return 

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
    except Exception as e:
        logging.error(f"Auto-poll error: {e}")

# =========================================================================
# РОЗКЛАД НА ЗАВТРА (ВЕЧІРНЯ РОЗСИЛКА)
# =========================================================================
async def daily_sch_broadcast(bot: Bot):
    # ПЕРЕВІРКА: чи увімкнене відправлення розкладу
    is_enabled = await get_setting("auto_morning_schedule")
    if is_enabled != True:
        return

    days = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"}
    tomorrow = datetime.now() + timedelta(days=1)
    day_name = days.get(tomorrow.weekday())
    if not day_name:
        return

    lessons = await get_schedule_by_day(day_name, is_next_week=False)
    if not lessons:
        return

    date_str = tomorrow.strftime("%d.%m.%Y")
    is_distance = await get_distance_learning(is_next_week=False)
    if not is_distance:
        from database.requests import check_schedule_has_classrooms
        is_distance = not await check_schedule_has_classrooms(is_next_week=False)
    
    if is_distance:
        from schedule_system.formatter import extract_subject_code
        from database.requests import get_subject_text
        text = f"📅 <b>Розклад на завтра ({day_name}, {date_str})</b> — дистанційно\n\n"
        for l in lessons:
            text += f"<b>{l.pair_num} пара:</b> {l.lesson_text}\n"
            code = extract_subject_code(l.lesson_text)
            if code:
                subj_text = await get_subject_text(code)
                if subj_text:
                    text += subj_text + "\n"
    else:
        text = f"📅 <b>Розклад на завтра ({day_name}, {date_str})</b>\n\n"
        for l in lessons:
            text += f"<b>{l.pair_num} пара:</b> {l.lesson_text}\n"
    
    target_thread = SCHEDULE_THREAD_ID if SCHEDULE_THREAD_ID else MESSAGE_THREAD_ID
    await bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=target_thread, text=text.strip())

async def notify_stale_approvals(bot: Bot):
    """Нагадування адмінам про запити, що вісять 6+ годин."""
    from database.requests import get_setting_value, set_setting_value
    stale = await get_stale_approvals(6)
    if not stale:
        return
    last_key = "stale_approvals_last_notif"
    last_str = await get_setting_value(last_key)
    if last_str:
        try:
            last_dt = datetime.fromisoformat(last_str)
            if datetime.now() - last_dt < timedelta(hours=6):
                return
        except Exception:
            pass
    admins = await get_admins()
    if not admins:
        return
    count = len(stale)
    text = f"⏰ <b>Нагадування:</b> {count} запит(ів) очікує розгляду більше 6 годин.\n\nБудь ласка, перегляньте їх у розділі «🔔 Запити»."
    for admin_id in admins:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Stale notify to {admin_id}: {e}")
    await set_setting_value(last_key, datetime.now().isoformat())


async def _send_zv_city_reminder(bot: Bot, is_half_hour_warning: bool = False):
    # Лише по буднях: Пн(0) ... Пт(4)
    if datetime.now().weekday() > 4:
        return
    is_enabled = await get_setting("auto_zv_reminders")
    if is_enabled != True:
        return
    users = await get_users_for_zv_city_reminder()
    if not users:
        return
    if is_half_hour_warning:
        text = "⏰ До останнього подання у Зв у місто залишилось пів години."
    else:
        text = "🔔 Нагадування: не забудьте подати себе у Зв у місто."
    for u in users:
        try:
            await bot.send_message(u.tg_id, text)
        except Exception as e:
            logging.error(f"ZV city reminder to {u.tg_id} failed: {e}")


async def _send_zv_final_5m_reminder(bot: Bot):
    is_enabled = await get_setting("auto_zv_reminders")
    if is_enabled != True:
        return
    users = await get_users_for_zv_general_deadline_reminder()
    if not users:
        return
    text = (
        "⚠️ Памʼятка: до крайнього строку подання у Зв залишилось 5 хвилин.\n"
        "Якщо ви з гуртожитку — подайте заявку зараз."
    )
    for u in users:
        try:
            await bot.send_message(u.tg_id, text)
        except Exception as e:
            logging.error(f"ZV final reminder to {u.tg_id} failed: {e}")

async def main():
    await init_db()
    try:
        users_count = await get_users_count()
        logging.info(f"📦 DB file: {get_db_path()} | users: {users_count}")
    except Exception as e:
        logging.error(f"DB info log error: {e}")
    
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    webapp_api_runner = None
    if C55_WEBAPP_API_URL:
        try:
            from webapp_api import start_site

            webapp_api_runner = await start_site(C55_WEBAPP_API_HOST, C55_WEBAPP_API_PORT)
        except Exception as e:
            logging.error("Не вдалося запустити C55 WebApp API: %s", e)

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        user = message.from_user
        await add_or_update_user(user.id, user.full_name, user.username, update_existing=False)
        is_admin = await check_is_admin(user.id)
        await message.answer(
            f"Привіт, {user.full_name}! 👋\nТи успішно зареєстрований у базі.\n\nСкористайся кнопкою '🌐 Відкрити C55 Web App'.",
            reply_markup=get_reply_kb(is_admin, webapp_url=_c55_webapp_url(is_admin=is_admin))
        )

    @dp.message(Command("refresh"))
    async def cmd_refresh(message: Message):
        """Лише показує нижню клавіатуру; нічого не пише в БД."""
        user = message.from_user
        if not await is_user_registered(user.id):
            await message.answer(
                "Спочатку зареєструйся командою /start — без цього бот тебе не знає в базі.",
            )
            return
        is_admin = await check_is_admin(user.id)
        await message.answer(
            "✅ Кнопки оновлено.",
            reply_markup=get_reply_kb(is_admin, webapp_url=_c55_webapp_url(is_admin=is_admin)),
        )

    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        await add_approval_request(message.from_user.id, 'admin_request')
        await message.answer("⏳ Запит на отримання прав адміністратора надіслано на розгляд.")
        try: await message.delete()
        except: pass

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        is_admin = await check_is_admin(message.from_user.id)
        await message.answer(build_help_text(is_admin), parse_mode="HTML")

    dp.include_routers(admin_router, profile_router, zv_release_router, polls_router, options_router, sne_router)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    
    scheduler.add_job(auto_poll_job, 'cron', hour=7, minute=30, args=[bot, "rozvid_1"])
    scheduler.add_job(auto_poll_job, 'cron', hour=7, minute=30, args=[bot, "rozvid_2"])
    scheduler.add_job(auto_poll_job, 'cron', day=1, hour=10, minute=0, args=[bot, "dorm_rent"])
    scheduler.add_job(auto_poll_job, 'cron', day=1, hour=10, minute=5, args=[bot, "dorm_fund"])
    
    # Розклад на завтра о 20:00 (київський час)
    scheduler.add_job(daily_sch_broadcast, 'cron', hour=20, minute=0, args=[bot])
    
    # ПЕРЕНЕСЕННЯ РОЗКЛАДУ (Понеділок о 1:00 — "Наступний" стає "Поточним")
    scheduler.add_job(promote_next_week_schedule, 'cron', day_of_week='mon', hour=1, minute=0)

    scheduler.add_job(cleanup_old_polls, 'cron', hour=3, minute=0)

    # Прострочені запити на звільнення (кінець періоду минув)
    scheduler.add_job(_schedule_zv_cleanup, 'cron', hour='*/4', minute=17)

    # Архів погоджених подань Зв у БД — очищення щонеділі о 23:59
    scheduler.add_job(_zv_sunday_archive_cleanup, 'cron', day_of_week='sun', hour=23, minute=59)

    # Подання «Зв у місто» — очищення щодня наприкінці дня.
    scheduler.add_job(_zv_city_daily_cleanup, 'cron', hour=23, minute=59)

    # Нагадування адмінам про запити 6+ годин (кожні 6 годин)
    scheduler.add_job(notify_stale_approvals, 'cron', hour='0,6,12,18', minute=5, args=[bot])

    # Нагадування по Зв у місто (12:00 і 14:30), останнє — за пів години до дедлайну.
    scheduler.add_job(_send_zv_city_reminder, 'cron', hour=12, minute=0, args=[bot, False])
    scheduler.add_job(_send_zv_city_reminder, 'cron', hour=14, minute=30, args=[bot, True])

    # Пам'ятка за 5 хв до крайнього строку подання у Зв.
    scheduler.add_job(_send_zv_final_5m_reminder, 'cron', hour=14, minute=55, args=[bot])

    scheduler.start()
    logging.info("🚀 Бот запущений!")

    try:
        await setup_bot_commands(bot)
        logging.info("Команди бота зареєстровані (підказки при /)")
    except Exception as e:
        logging.error(f"Не вдалося зареєструвати команди в Telegram: {e}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        if webapp_api_runner is not None:
            try:
                await webapp_api_runner.cleanup()
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(main())
    