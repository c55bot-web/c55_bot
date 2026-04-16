import logging
import html
from aiogram import Router, Bot
from aiogram.types import PollAnswer
from core.config import MESSAGE_THREAD_ID
from sqlalchemy import select
from database.models import User
from database.requests import (
    save_vote_and_get_count, get_poll_report_data, close_poll_in_db, 
    get_admins, save_poll_report_text, get_expected_voters_count, async_session
)

router = Router()
HIDE_STUDENTS_TAG = "[NO_STUDENTS]"

def sort_by_list_number(user):
    return (user.list_number if user.list_number is not None else 999, user.full_name)

def option_hides_students(option_text: str) -> bool:
    return HIDE_STUDENTS_TAG in option_text.upper()

def option_display_text(option_text: str) -> str:
    return option_text.replace(HIDE_STUDENTS_TAG, "").strip()

@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer, bot: Bot):
    if not poll_answer.option_ids: return
    
    vote_count, poll_info = await save_vote_and_get_count(
        poll_answer.poll_id, poll_answer.user.id, str(poll_answer.option_ids[0])
    )
    
    if poll_info and poll_info.is_active:
        target_votes = await get_expected_voters_count(poll_info.type)
        # Якщо у БД 0 курсантів (або для гуртожитку — 0 мешканців), target_votes == 0 і умова
        # vote_count >= 0 виконується одразу — опитування закривається "само", хоча голосів немає.
        if target_votes <= 0:
            logging.warning(
                "Авто-закриття опитування пропущено: очікуваних голосів %s (тип %s). "
                "Перевірте користувачів у БД.",
                target_votes,
                poll_info.type,
            )
            return
        if vote_count >= target_votes:
            try:
                stopped_poll = await bot.stop_poll(chat_id=poll_info.chat_id, message_id=poll_info.message_id)
                await close_poll_in_db(poll_answer.poll_id)
                
                # ОТРИМУЄМО ДВА ПОВІДОМЛЕННЯ
                report_text, silent_text = await generate_report(stopped_poll, poll_answer.poll_id)
                
                # Зберігаємо в базу об'єднаний варіант для історії
                await save_poll_report_text(poll_answer.poll_id, report_text + "\n\n" + silent_text)
                
                # ВІДПРАВЛЯЄМО ДВА ПОВІДОМЛЕННЯ В ЧАТ
                await bot.send_message(chat_id=poll_info.chat_id, message_thread_id=MESSAGE_THREAD_ID, text=report_text, parse_mode="HTML")
                await bot.send_message(chat_id=poll_info.chat_id, message_thread_id=MESSAGE_THREAD_ID, text=silent_text, parse_mode="HTML")
                
                admins = await get_admins()
                for admin_id in admins:
                    if admin_id != poll_info.chat_id: 
                        try: 
                            await bot.send_message(admin_id, f"📥 <b>Копія звіту:</b>\n\n{report_text}", parse_mode="HTML")
                            await bot.send_message(admin_id, silent_text, parse_mode="HTML")
                        except Exception as e: logging.error(e)
            except Exception as e: logging.error(f"Помилка зупинки: {e}")

async def generate_report(stopped_poll, tg_poll_id):
    try:
        poll_info, votes_data, silent_data = await get_poll_report_data(tg_poll_id)
        
        async with async_session() as session:
            stmt = select(User)
            if poll_info and poll_info.type in ['dorm_rent', 'dorm_fund']:
                stmt = stmt.where(User.in_dorm == True)
            all_users = (await session.execute(stmt)).scalars().all()
            user_map = {u.full_name: u for u in all_users}
            
        total_users = len(all_users)
        total_females = len([u for u in all_users if getattr(u, 'is_female', False)])
        
        results = {opt.text: [] for opt in stopped_poll.options}
        voted_names = set()
        
        for opt_idx_str, full_name, list_number, username in votes_data:
            idx = int(opt_idx_str)
            if idx < len(stopped_poll.options):
                opt_text = stopped_poll.options[idx].text
                user_obj = user_map.get(full_name)
                if user_obj:
                    results[opt_text].append(user_obj)
                    voted_names.add(full_name)
                    
        silent_users = [u for u in all_users if u.full_name not in voted_names]
        
        lines = []

        # ==========================================
        # 1. ПЕРШЕ ПОВІДОМЛЕННЯ (ОСНОВНИЙ ЗВІТ)
        # ==========================================
        if poll_info and poll_info.type in ['rozvid_1', 'rozvid_2']:
            if getattr(stopped_poll, "question", None):
                lines.append(f"<b>{html.escape(stopped_poll.question)}</b>")
                lines.append("")
            lines.append(f"З/с - {total_users}/{total_females}") # БЕЗ "за списком"
            lines.append("") 
            
            def format_user(u: User, with_details: bool) -> str:
                if not with_details:
                    return f"- {html.escape(u.full_name)}"
                parts = ["С-55"]
                addr = (getattr(u, "address", None) or "").strip()
                phone = (getattr(u, "phone_number", None) or "").strip()
                if addr:
                    parts.append(addr)
                if phone:
                    parts.append(phone)
                return f"- {html.escape(u.full_name)} ({html.escape(', '.join(parts))})"

            # Порядок пунктів — як у самому опитуванні (Telegram poll options)
            for opt in stopped_poll.options:
                voters = results.get(opt.text, [])
                count = len(voters)
                if count == 0:
                    continue

                girls_count = sum(1 for u in voters if getattr(u, 'is_female', False))
                hide_students = option_hides_students(opt.text)
                display_opt_text = option_display_text(opt.text)
                lines.append(f"<b>{html.escape(display_opt_text)} {count}/{girls_count}</b>")

                if hide_students:
                    lines.append("- Дані студентів приховано для цього пункту")
                    lines.append("")
                    continue

                voters.sort(key=lambda x: (x.list_number if x.list_number is not None else 999, x.full_name))
                for u in voters:
                    lines.append(format_user(u, with_details=(display_opt_text != "В/н")))
                lines.append("")

        # ==========================================
        # 2. ДРУГЕ ПОВІДОМЛЕННЯ (МОВЧУНИ З ТЕГАМИ)
        # ==========================================
        silent_lines = ["<b>Ті хто не проголосував:</b>"]
        silent_count = len(silent_users)
        
        if silent_count > 0:
            silent_users.sort(key=sort_by_list_number)
            for u in silent_users: 
                # ПОВЕРНУЛИ ЯК БУЛО (без @username)
                silent_lines.append(f"- {u.full_name}")
        else:
            silent_lines.append("Усі курсанти успішно проголосували!")
        # Функція повертає дві змінні!
        return "\n".join(lines).strip(), "\n".join(silent_lines).strip()
        
    except Exception as e:
        logging.error(f"Generate report error: {e}")
        return f"⚠️ Помилка: {e}", "Помилка"