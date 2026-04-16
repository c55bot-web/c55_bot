import asyncio
import html
import json
import os
import logging
import tempfile
from sqlalchemy import select, func, delete, update, text, event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from datetime import date, datetime, timedelta
from core.config import ADMIN_IDS

from .models import Base, User, UserDiscipline, Poll, Vote, Setting, Approval, Schedule, ZvApprovedReport

# Фіксуємо абсолютний шлях до БД, щоб бот завжди працював з одним файлом.
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "c55_data.db"))
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, connection_record):
    # Без цього SQLite ігнорує ON DELETE CASCADE — лишаються «сиротські» votes зі старим poll_id,
    # новий poll може отримати той самий id → один новий голос дає «повний» лічильник і миттєве закриття.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

def get_db_path() -> str:
    return DB_PATH


async def ensure_user_discipline(session, user: User) -> UserDiscipline:
    """Рядок user_discipline за tg_id; створює, якщо ще немає."""
    if user.discipline is None:
        d = UserDiscipline(tg_id=user.tg_id)
        session.add(d)
        await session.flush()
    return user.discipline


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Прибрати голоси без запису опитування (накопичились до увімкнення foreign_keys)
        await conn.execute(text(
            "DELETE FROM votes WHERE poll_id NOT IN (SELECT id FROM polls)"
        ))
        # АВТО-РЕМОНТ БАЗИ ДАНИХ
        try: await conn.execute(text("ALTER TABLE schedule ADD COLUMN is_next_week BOOLEAN DEFAULT 0"))
        except Exception: pass
        try: await conn.execute(text("ALTER TABLE schedule ADD COLUMN date_str VARCHAR"))
        except Exception: pass
        try: await conn.execute(text("ALTER TABLE schedule ADD COLUMN location_text VARCHAR"))
        except Exception: pass
        try: await conn.execute(text("ALTER TABLE approvals ADD COLUMN correspondence VARCHAR"))
        except Exception: pass
        for col_sql in (
            "ALTER TABLE users ADD COLUMN na_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN violations_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_zv_reason VARCHAR",
        ):
            try:
                await conn.execute(text(col_sql))
            except Exception:
                pass
        # Міграція: дані НА/порушень/Зв з колонок users у таблицю user_discipline (якщо ще є старі колонки)
        try:
            await conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO user_discipline (tg_id, na_count, violations_count, last_zv_reason)
                    SELECT tg_id, COALESCE(na_count, 0), COALESCE(violations_count, 0), last_zv_reason FROM users
                    """
                )
            )
        except Exception:
            pass
        # Рядок user_discipline для кожного користувача, у кого ще немає (нова БД без колонок у users)
        try:
            await conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO user_discipline (tg_id, na_count, violations_count, last_zv_reason)
                    SELECT u.tg_id, 0, 0, NULL FROM users u
                    WHERE NOT EXISTS (SELECT 1 FROM user_discipline d WHERE d.tg_id = u.tg_id)
                    """
                )
            )
        except Exception:
            pass

    async with async_session() as session:
        # Додано 'auto_morning_schedule'
        defaults = {
            'auto_rozvid_1': 'True', 
            'auto_rozvid_2': 'True', 
            'auto_dorm_rent': 'True', 
            'auto_dorm_fund': 'True', 
            'auto_data_change': 'True',
            'auto_morning_schedule': 'True',
            'auto_zv_reminders': 'True',
        }
        for k, v in defaults.items():
            if not await session.scalar(select(Setting).where(Setting.key == k)):
                session.add(Setting(key=k, value=v))
        await session.commit()

# --- РОБОТА З КОРИСТУВАЧАМИ ---
async def add_or_update_user(tg_id: int, full_name: str, username: str | None, update_existing: bool = True):
    """Додає нового користувача або оновлює існуючого. update_existing=False — лише додає, не перезаписує."""
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            new_user = User(tg_id=tg_id, full_name=full_name, username=username)
            session.add(new_user)
            session.add(UserDiscipline(tg_id=tg_id))
            await session.commit()
            await backup_user_to_json(new_user)
        elif update_existing:
            user.full_name = full_name
            user.username = username
            await session.commit()
            await backup_user_to_json(user)

async def is_user_registered(tg_id: int) -> bool:
    async with async_session() as session:
        return (await session.get(User, tg_id)) is not None


async def check_is_admin(tg_id: int) -> bool:
    if tg_id in ADMIN_IDS: return True
    async with async_session() as session:
        user = await session.get(User, tg_id)
        return user.is_admin if user else False

async def get_all_usernames() -> list[str]:
    async with async_session() as session:
        result = await session.execute(select(User.username).where(User.username.isnot(None)))
        return result.scalars().all()

async def get_users_count() -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count(User.tg_id)))

async def get_admins() -> list[int]:
    async with async_session() as session:
        result = await session.execute(select(User.tg_id).where(User.is_admin == True))
        admins = result.scalars().all()
        return list(set(ADMIN_IDS + list(admins)))

async def delete_user_from_db(tg_id: int):
    async with async_session() as session:
        user = await session.get(User, tg_id)
        if user:
            await session.delete(user)
            await session.commit()
            
    file_path = 'users_backup.json'
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
            if str(tg_id) in data:
                del data[str(tg_id)]
                with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
        except: pass

# --- НАЛАШТУВАННЯ ТА ЗАПИТИ ---
async def get_setting(key: str) -> bool:
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        return setting.value == 'True' if setting else False

async def get_setting_value(key: str) -> str | None:
    """Повертає рядкове значення налаштування."""
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        return setting.value if setting else None

async def set_setting_value(key: str, value: str):
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        if setting:
            setting.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()

async def toggle_setting(key: str) -> bool:
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        if setting:
            new_val = not (setting.value == 'True')
            setting.value = str(new_val)
            await session.commit()
            return new_val
        return False

async def get_all_settings() -> dict:
    async with async_session() as session:
        settings = (await session.execute(select(Setting))).scalars().all()
        return {s.key: (s.value == 'True') for s in settings}

async def get_pending_approvals_count() -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count(Approval.id)))

async def add_approval_request(user_id: int, req_type: str, field: str = None, old_val: str = None, new_val: str = None):
    async with async_session() as session:
        app = Approval(user_id=user_id, type=req_type, field=field or "", old_value=str(old_val) if old_val is not None else "", new_value=str(new_val) if new_val is not None else "")
        session.add(app)
        await session.commit()

async def get_users_with_requests():
    """Повертає список (User, кількість запитів) для курсантів, що мають запити."""
    async with async_session() as session:
        subq = select(Approval.user_id).distinct()
        rows = await session.execute(subq)
        user_ids = [r for r in rows.scalars().all()]
        result = []
        for uid in user_ids:
            user = await session.get(User, uid)
            if user:
                count = await session.scalar(select(func.count(Approval.id)).where(Approval.user_id == uid))
                result.append((user, count))
        result.sort(key=lambda x: (x[0].list_number or 999, x[0].full_name))
        return result


async def get_users_with_requests_by_types(req_types: list[str]):
    """Повертає список (User, count) для курсантів, що мають запити певних типів."""
    if not req_types:
        return []
    async with async_session() as session:
        stmt = (
            select(Approval.user_id, func.count(Approval.id))
            .where(Approval.type.in_(req_types))
            .group_by(Approval.user_id)
        )
        rows = (await session.execute(stmt)).all()
        result = []
        for uid, count in rows:
            user = await session.get(User, uid)
            if user:
                result.append((user, int(count or 0)))
        result.sort(key=lambda x: (x[0].list_number or 999, x[0].full_name))
        return result

async def get_requests_by_user(user_id: int):
    async with async_session() as session:
        stmt = select(Approval).where(Approval.user_id == user_id).order_by(Approval.created_at.asc())
        return (await session.execute(stmt)).scalars().all()


async def get_requests_by_user_and_types(user_id: int, req_types: list[str]):
    if not req_types:
        return []
    async with async_session() as session:
        stmt = (
            select(Approval)
            .where(Approval.user_id == user_id, Approval.type.in_(req_types))
            .order_by(Approval.created_at.asc())
        )
        return (await session.execute(stmt)).scalars().all()

async def get_approval_by_id(app_id: int):
    async with async_session() as session:
        return await session.get(Approval, app_id)


async def get_approvals_by_type(req_type: str):
    async with async_session() as session:
        stmt = select(Approval).where(Approval.type == req_type).order_by(Approval.created_at.asc())
        return (await session.execute(stmt)).scalars().all()

async def delete_approval(app_id: int):
    async with async_session() as session:
        app = await session.get(Approval, app_id)
        if app:
            uid = app.user_id
            await session.delete(app)
            await session.commit()
            return uid
    return None

async def add_approval_correspondence(app_id: int, role: str, text: str):
    """Додає запис до переписки по запиту. role: 'admin_question' | 'student_answer'"""
    async with async_session() as session:
        app = await session.get(Approval, app_id)
        if app:
            items = []
            if app.correspondence:
                try:
                    items = json.loads(app.correspondence)
                except Exception:
                    pass
            items.append({"role": role, "text": text, "at": datetime.now().isoformat()})
            app.correspondence = json.dumps(items)
            await session.commit()

async def get_approval_correspondence(app_id: int) -> list:
    async with async_session() as session:
        app = await session.get(Approval, app_id)
        if app and app.correspondence:
            try:
                return json.loads(app.correspondence)
            except Exception:
                pass
    return []

async def get_stale_approvals(hours: int = 6) -> list:
    """Повертає запити, що вісять більше N годин."""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(hours=hours)
    async with async_session() as session:
        stmt = select(Approval).where(Approval.created_at < cutoff).order_by(Approval.created_at.asc())
        return (await session.execute(stmt)).scalars().all()

async def notify_admins_about_request(bot, user_name: str):
    """Сповіщає всіх адмінів про новий запит. Якщо <3 год з попереднього — редагує повідомлення, інакше — нове."""
    admins = await get_admins()
    if not admins:
        return
    count = await get_pending_approvals_count()
    text = f"🔔 <b>Новий запит</b> від {user_name}\n\n📋 Всього запитів: {count}"
    now = datetime.now()
    three_hours = timedelta(hours=3)
    for admin_id in admins:
        try:
            key = f"req_notif_{admin_id}"
            stored = await get_setting_value(key)
            if stored:
                parts = stored.split("|")
                if len(parts) >= 2:
                    last_msg_id, last_time_str = int(parts[0]), parts[1]
                    last_dt = datetime.fromisoformat(last_time_str)
                    if now - last_dt < three_hours:
                        await bot.edit_message_text(text=text, chat_id=admin_id, message_id=last_msg_id, parse_mode="HTML")
                        await set_setting_value(key, f"{last_msg_id}|{now.isoformat()}")
                        continue
            msg = await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
            await set_setting_value(key, f"{msg.message_id}|{now.isoformat()}")
        except Exception as e:
            logging.error(f"Notify admin {admin_id} error: {e}")

async def process_approval(app_id: int, approved: bool) -> int:
    user_id = None
    async with async_session() as session:
        app = await session.get(Approval, app_id)
        if app:
            user_id = app.user_id
            if approved:
                user = await session.get(User, app.user_id)
                if user:
                    if app.type == 'admin_request': user.is_admin = True
                    elif app.type in ('zv_release', 'zv_dorm'):
                        try:
                            payload = json.loads(app.new_value or "{}")
                            r = (payload.get("reason") or "").strip()
                            if r:
                                disc = await ensure_user_discipline(session, user)
                                disc.last_zv_reason = r[:500]
                        except Exception:
                            pass
                    elif app.field == 'fullname': user.full_name = app.new_value
                    elif app.field == 'phone': user.phone_number = app.new_value
                    elif app.field == 'address': user.address = app.new_value
                    elif app.field == 'listnum': user.list_number = int(app.new_value)
                    elif app.field == 'gender': user.is_female = (app.new_value == 'True')
                    elif app.field == 'dorm': user.in_dorm = (app.new_value == 'True')
                    await backup_user_to_json(user)
                if app.type in ('zv_release', 'zv_dorm', 'zv_city'):
                    session.add(
                        ZvApprovedReport(
                            user_id=app.user_id,
                            payload_json=app.new_value or "{}",
                        )
                    )
            await session.delete(app)
            await session.commit()
    return user_id

# --- ОПИТУВАННЯ ---
async def save_new_poll(tg_poll_id: str, message_id: int, chat_id: int, poll_type: str):
    async with async_session() as session:
        new_poll = Poll(
            tg_poll_id=str(tg_poll_id),
            message_id=message_id,
            chat_id=chat_id,
            type=poll_type,
        )
        session.add(new_poll)
        await session.commit()

async def get_active_polls():
    async with async_session() as session:
        return (await session.execute(select(Poll).where(Poll.is_active == True))).scalars().all()

async def get_poll_by_tg_id(tg_poll_id: str):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        return await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))

async def save_vote_and_get_count(tg_poll_id: str, tg_user_id: int, option_selected: str):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        poll = await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
        if not poll: return 0, None

        # Рахуємо тільки голоси курсантів із БД (і тільки гуртожиток для dorm-полів).
        user = await session.get(User, tg_user_id)
        is_eligible_user = bool(user)
        if poll.type in ['dorm_rent', 'dorm_fund']:
            is_eligible_user = bool(user and user.in_dorm)

        if is_eligible_user:
            vote = await session.scalar(select(Vote).where(Vote.poll_id == poll.id, Vote.user_id == tg_user_id))
            if not vote:
                session.add(Vote(poll_id=poll.id, user_id=tg_user_id, option_selected=option_selected))
            else:
                vote.option_selected = option_selected
            await session.commit()

        # Унікальні голосуючі (захист від дублікатів рядків і від некоректних даних)
        count_stmt = (
            select(func.count(func.distinct(Vote.user_id)))
            .join(User, Vote.user_id == User.tg_id)
            .where(Vote.poll_id == poll.id)
        )
        if poll.type in ['dorm_rent', 'dorm_fund']:
            count_stmt = count_stmt.where(User.in_dorm == True)
        count = await session.scalar(count_stmt)
        return count, poll

async def close_poll_in_db(tg_poll_id: str):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        poll = await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
        if poll:
            poll.is_active = False
            await session.commit()

async def save_poll_report_text(tg_poll_id: str, report_text: str):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        poll = await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
        if poll:
            poll.report_text = report_text
            await session.commit()

async def get_poll_report_data(tg_poll_id: str):
    tg_poll_id = str(tg_poll_id)
    async with async_session() as session:
        poll = await session.scalar(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
        if not poll: return None, [], []
        votes_stmt = select(Vote.option_selected, User.full_name, User.list_number, User.username).join(User, Vote.user_id == User.tg_id).where(Vote.poll_id == poll.id)
        votes_data = (await session.execute(votes_stmt)).all()
        subq = select(Vote.user_id).where(Vote.poll_id == poll.id)
        silent_stmt = select(User.full_name, User.list_number, User.username).where(~User.tg_id.in_(subq))
        if poll.type in ['dorm_rent', 'dorm_fund']: 
            silent_stmt = silent_stmt.where(User.in_dorm == True)
        silent_data = (await session.execute(silent_stmt)).all()
        return poll, votes_data, silent_data

async def get_closed_polls_history(limit_days: int = 7):
    async with async_session() as session:
        cutoff = datetime.now() - timedelta(days=limit_days)
        stmt = select(Poll).where(Poll.is_active == False, Poll.created_at >= cutoff).order_by(Poll.created_at.desc())
        return (await session.execute(stmt)).scalars().all()

async def cleanup_old_polls():
    async with async_session() as session:
        three_days_ago = datetime.now() - timedelta(days=3)
        await session.execute(delete(Poll).where(Poll.created_at < three_days_ago))
        await session.commit()


async def cleanup_expired_zv_approvals() -> int:
    """Видаляє запити Зв, у яких кінець періоду вже минув."""
    from core.zv_helpers import parse_zv_payload, zv_end_datetime

    removed = 0
    async with async_session() as session:
        stmt = select(Approval).where(Approval.type.in_(("zv_release", "zv_dorm")))
        apps = (await session.execute(stmt)).scalars().all()
        now = datetime.now()
        for app in apps:
            data = parse_zv_payload(app.new_value)
            if not data:
                continue
            end = zv_end_datetime(data)
            if end and end < now:
                await session.delete(app)
                removed += 1
        if removed:
            await session.commit()
    return removed


async def cleanup_daily_zv_city_submissions() -> int:
    """Щоденне очищення подань «Зв у місто» (pending у approvals)."""
    async with async_session() as session:
        stmt = select(Approval).where(Approval.type == "zv_city")
        apps = (await session.execute(stmt)).scalars().all()
        n = 0
        for app in apps:
            await session.delete(app)
            n += 1
        if n:
            await session.commit()
        return n


async def get_users_for_zv_city_reminder() -> list[User]:
    """Курсанти з гуртожитку (не адміни), які ще не подали Зв у місто."""
    async with async_session() as session:
        pending_city_subq = select(Approval.user_id).where(Approval.type == "zv_city")
        stmt = (
            select(User)
            .where(
                User.in_dorm == True,
                User.is_admin == False,
                ~User.tg_id.in_(pending_city_subq),
            )
            .order_by(User.list_number.asc().nulls_last(), User.full_name.asc())
        )
        return (await session.execute(stmt)).scalars().all()


async def get_users_for_zv_general_deadline_reminder() -> list[User]:
    """Курсанти з гуртожитку (не адміни), які ще не подали жоден тип Зв."""
    async with async_session() as session:
        pending_zv_subq = select(Approval.user_id).where(Approval.type.in_(("zv_city", "zv_dorm", "zv_release")))
        stmt = (
            select(User)
            .where(
                User.in_dorm == True,
                User.is_admin == False,
                ~User.tg_id.in_(pending_zv_subq),
            )
            .order_by(User.list_number.asc().nulls_last(), User.full_name.asc())
        )
        return (await session.execute(stmt)).scalars().all()


async def delete_all_zv_approved_reports() -> int:
    """Видаляє всі збережені в БД погоджені подання Зв (архів для звіту «на тиждень»)."""
    async with async_session() as session:
        n = await session.scalar(select(func.count()).select_from(ZvApprovedReport))
        await session.execute(delete(ZvApprovedReport))
        await session.commit()
        return int(n or 0)


async def update_user_last_zv_reason(user_id: int, reason: str) -> None:
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            disc = await ensure_user_discipline(session, user)
            disc.last_zv_reason = reason[:500]
            await session.commit()
            await backup_user_to_json(user)


async def set_user_na_violations(tg_id: int, na: int | None, violations: int | None) -> bool:
    async with async_session() as session:
        user = await session.get(User, tg_id)
        if not user:
            return False
        disc = await ensure_user_discipline(session, user)
        if na is not None:
            disc.na_count = na
        if violations is not None:
            disc.violations_count = violations
        await session.commit()
        await backup_user_to_json(user)
        return True


async def apply_discipline_by_list_number(list_number: int, violations_delta: int | None) -> tuple[bool, str]:
    """
    НА з Google Таблиці (стовпці E і F) для **усіх** курсантів з номером у списку.
    Порушення: відносна зміна лише для вказаного номера (наприклад -1 зняти одне).
    """
    from core.sne_na import sync_na_all_from_sheet_for_users

    async with async_session() as session:
        stmt = select(User).where(User.list_number == list_number).limit(1)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if not user:
            return False, f"Курсанта з номером у списку {list_number} не знайдено в базі."

        stmt_all = select(User).where(User.list_number.isnot(None)).order_by(User.list_number.asc())
        all_users = (await session.execute(stmt_all)).scalars().all()
        pairs = [(u.tg_id, u.list_number) for u in all_users if u.list_number is not None]

        na_map = await asyncio.to_thread(sync_na_all_from_sheet_for_users, pairs)

        updated_na = 0
        for u in all_users:
            if u.list_number is None:
                continue
            pack = na_map.get(u.tg_id)
            if not pack:
                continue
            na, err = pack
            if err or na is None:
                continue
            disc = await ensure_user_discipline(session, u)
            disc.na_count = na
            updated_na += 1

        t_pack = na_map.get(user.tg_id)
        if not t_pack:
            return False, "Не вдалося отримати НА з таблиці для цього курсанта."
        tna, terr = t_pack
        if terr:
            return False, terr
        if tna is None:
            return False, "Не вдалося порахувати НА з таблиці."

        disc = await ensure_user_discipline(session, user)
        if violations_delta is not None:
            cur = disc.violations_count or 0
            disc.violations_count = max(0, cur + violations_delta)

        await session.commit()

        for u in all_users:
            if u.list_number is None:
                continue
            p = na_map.get(u.tg_id)
            if p is not None and p[1] is None:
                await backup_user_to_json(u)

        name = html.escape(user.full_name or "?")
        msg = (
            f"✅ №{list_number} — {name}\n"
            f"НА={tna} (таблиця SNE: E і F; 1,5 б. негативу = 1 НА)\n"
            f"Порушень: {disc.violations_count}"
        )
        if violations_delta is not None:
            msg += f" (зміна {violations_delta:+d})"
        msg += f"\n\n📊 НА з таблиці оновлено в базі: <b>{updated_na}</b> з <b>{len(pairs)}</b> курсантів."
        return True, msg


async def get_zv_week_report_html() -> str:
    """Форматований HTML для «Зв на цей тиждень» — усі погоджені звіти, період яких перетинає поточний тиждень."""
    import html
    from datetime import date, timedelta
    from core.zv_helpers import parse_zv_payload, format_zv_admin_report
    from core.sne_na import read_ef_and_compute_na

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    blocks = []
    async with async_session() as session:
        stmt = select(ZvApprovedReport).order_by(ZvApprovedReport.approved_at.asc())
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            data = parse_zv_payload(row.payload_json)
            if not data:
                continue
            try:
                df = date.fromisoformat(data["date_from"][:10])
                dt = date.fromisoformat(data["date_to"][:10])
            except Exception:
                continue
            if dt < week_start or df > week_end:
                continue
            user = await session.get(User, row.user_id)
            if not user:
                continue
            if user.list_number is not None:
                na, err = await asyncio.to_thread(read_ef_and_compute_na, user.list_number)
                if not err and na is not None:
                    disc = await ensure_user_discipline(session, user)
                    disc.na_count = na
            raw = format_zv_admin_report(user, data)
            # У Telegram HTML дозволені лише обмежені теги; <br> не підтримується — переноси через \n
            blocks.append(html.escape(raw))
        await session.commit()
    if not blocks:
        return "Немає погоджених запитів Зв на цей календарний тиждень (за датами періоду у звіті)."
    header = (
        f"<b>Зв на тиждень {week_start.strftime('%d.%m')} — {week_end.strftime('%d.%m.%Y')}</b>\n\n"
    )
    return header + "\n\n".join(blocks)

async def clear_all_polls_from_db() -> int:
    """Видаляє всі записи з таблиці polls; голоси (votes) зникають через ON DELETE CASCADE."""
    async with async_session() as session:
        n = await session.scalar(select(func.count(Poll.id)))
        await session.execute(delete(Poll))
        await session.commit()
        return int(n or 0)

async def backup_user_to_json(user: User):
    file_path = 'users_backup.json'
    data = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        except: pass
    data[str(user.tg_id)] = {
        "full_name": user.full_name, "username": user.username, "phone": user.phone_number,
        "address": user.address, "in_dorm": user.in_dorm, "list_number": user.list_number, "is_female": user.is_female,
        "na_count": getattr(user, "na_count", 0), "violations_count": getattr(user, "violations_count", 0),
    }
    with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)

async def get_expected_voters_count(poll_type: str) -> int:
    async with async_session() as session:
        stmt = select(func.count()).select_from(User)
        if poll_type in ['dorm_rent', 'dorm_fund']:
            stmt = stmt.where(User.in_dorm == True)
        n = await session.scalar(stmt)
        return int(n or 0)

# --- РОБОТА З РОЗКЛАДОМ ---
async def update_schedule_in_db(lessons_data: list, is_next_week: bool = False):
    async with async_session() as session:
        await session.execute(delete(Schedule).where(Schedule.is_next_week == is_next_week))
        for item in lessons_data:
            session.add(Schedule(
                day=item['day'], 
                pair_num=item['pair'], 
                lesson_text=item['text'], 
                is_next_week=is_next_week,
                date_str=item.get('date_str'),
                location_text=item.get('loc_text')
            ))
        await session.commit()

async def get_schedule_by_day(day_name: str, is_next_week: bool = False):
    async with async_session() as session:
        stmt = select(Schedule).where(Schedule.day == day_name, Schedule.is_next_week == is_next_week).order_by(Schedule.pair_num)
        result = await session.execute(stmt)
        return result.scalars().all()

async def clear_schedule_db(is_next_week: bool = False):
    async with async_session() as session:
        await session.execute(delete(Schedule).where(Schedule.is_next_week == is_next_week))
        await session.commit()

async def promote_next_week_schedule():
    async with async_session() as session:
        await session.execute(delete(Schedule).where(Schedule.is_next_week == False))
        await session.execute(update(Schedule).where(Schedule.is_next_week == True).values(is_next_week=False))
        await session.commit()

# --- ДИСТАНЦІЙНЕ НАВЧАННЯ ТА ТЕКСТИ ПРЕДМЕТІВ ---
# Резервні ключі для міграції старих налаштувань (АП2->5АП2, ТЙ->3ТЙ, ФВ2->ФВ1, КСАК->5КСАК)
_SUBJECT_CODE_FALLBACK = {"5АП2": "АП2", "3ТЙ": "ТЙ", "ФВ1": "ФВ2", "5КСАК": "КСАК"}

async def get_subject_text(subject_code: str) -> str:
    """Повертає налаштований текст/посилання для предмету (при дистанційному)."""
    async with async_session() as session:
        key = f"subject_{subject_code}"
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        if setting and setting.value:
            return setting.value
        old_code = _SUBJECT_CODE_FALLBACK.get(subject_code)
        if old_code:
            old_setting = await session.scalar(select(Setting).where(Setting.key == f"subject_{old_code}"))
            if old_setting and old_setting.value:
                return old_setting.value
        return ""

async def set_subject_text(subject_code: str, text: str):
    async with async_session() as session:
        key = f"subject_{subject_code}"
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        if setting:
            setting.value = text
        else:
            session.add(Setting(key=key, value=text))
        await session.commit()

async def get_distance_learning(is_next_week: bool) -> bool:
    """Чи розклад на дистанційне (вручну або авто-визначено)."""
    key = f"distance_{'next' if is_next_week else 'current'}"
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        return setting and setting.value == "True"

async def set_distance_learning(is_next_week: bool, value: bool):
    key = f"distance_{'next' if is_next_week else 'current'}"
    async with async_session() as session:
        setting = await session.scalar(select(Setting).where(Setting.key == key))
        if setting:
            setting.value = str(value)
        else:
            session.add(Setting(key=key, value=str(value)))
        await session.commit()

async def check_schedule_has_classrooms(is_next_week: bool) -> bool:
    """Перевіряє чи є в розкладі кабінети (без СР та ФВ). Якщо ні — дистанційне."""
    import re
    async with async_session() as session:
        stmt = select(Schedule).where(Schedule.is_next_week == is_next_week)
        result = await session.execute(stmt)
        lessons = result.scalars().all()
    
    classroom_pattern = re.compile(r'\d+\s*НК.*ауд', re.IGNORECASE)
    # Не рахуємо СР та ФВ1 (фізкультура)
    exclude_patterns = ("СР", "С/Р", "ФВ1", "Фіз. виховання", "фіз. виховання")
    
    for l in lessons:
        lt = (l.lesson_text or "").upper()
        loc = (l.location_text or "") + " " + lt
        if any(ex in lt or ex.upper() in loc for ex in exclude_patterns):
            continue  # Пропускаємо СР та ФВ
        if classroom_pattern.search(loc):
            return True
    return False

async def format_schedule_distance(lessons: list, day_name: str, date_str: str = "") -> str:
    """Формує розклад у форматі для дистанційного (з текстом під кожною парою)."""
    from schedule_system.formatter import extract_subject_code
    lines = [f"<b>{day_name}</b> ({date_str})" if date_str else f"<b>{day_name}</b>"]
    for l in lessons:
        lines.append(f"{l.pair_num} пара: {l.lesson_text}")
        code = extract_subject_code(l.lesson_text)
        if code:
            subj_text = await get_subject_text(code)
            if subj_text:
                lines.append(subj_text)
    return "\n".join(lines)


def _xlsx_sheet_title(table_name: str, used: set[str]) -> str:
    """Ім’я аркуша Excel: max 31 символ, без \\ / : * ? [ ]."""
    bad = r"\/:*?[]"
    s = "".join((c if c not in bad else "_") for c in table_name)[:31] or "Sheet"
    if s.lower() == "history":
        s = "hist"
    i = 0
    base = s
    while s in used:
        i += 1
        suf = f"_{i}"
        s = (base[: 31 - len(suf)] + suf) if len(base) + len(suf) > 31 else base + suf
    used.add(s)
    return s


def _xlsx_cell_value(v) -> object:
    if v is None:
        return ""
    if isinstance(v, date):  # datetime є підкласом date
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


# --- ЕКСПОРТ БАЗИ ДАНИХ В XLSX (Google Таблиці / Excel) ---
async def export_db_to_xlsx() -> str:
    """
    Експортує всю базу даних у .xlsx: по одному аркушу на кожну таблицю SQLite
    (усі колонки та рядки згідно зі схемою БД).
    """
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    used_titles: set[str] = set()

    async with async_session() as session:
        for tbl in Base.metadata.sorted_tables:
            title = _xlsx_sheet_title(tbl.name, used_titles)
            ws = wb.create_sheet(title)
            ident = tbl.name.replace('"', '""')
            result = await session.execute(text(f'SELECT * FROM "{ident}"'))
            cols = list(result.keys())
            ws.append(cols)
            for row in result:
                ws.append([_xlsx_cell_value(x) for x in row])

    fd, path = tempfile.mkstemp(suffix=".xlsx")
    try:
        os.close(fd)
        wb.save(path)
        return path
    except Exception:
        if os.path.exists(path):
            os.unlink(path)
        raise