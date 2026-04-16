"""Меню /options — налаштування текстів для предметів при дистанційному навчанні. Тільки для адмінів."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from core.config import SUBJECT_CODES, MENU_OWNERS
from core.keyboards import get_options_kb, get_back_btn
from core.states import OptionsPanel
from database.requests import check_is_admin, get_subject_text, set_subject_text

router = Router()

def is_owner(callback: CallbackQuery) -> bool:
    owner_id = MENU_OWNERS.get(callback.message.message_id)
    return not owner_id or owner_id == callback.from_user.id

@router.message(Command("options"))
async def cmd_options(message: Message, state: FSMContext):
    if not await check_is_admin(message.from_user.id):
        return
    await state.clear()
    msg = await message.answer(
        "⚙️ <b>Налаштування текстів для дистанційного розкладу</b>\n\n"
        "Оберіть предмет, щоб налаштувати текст або посилання, яке відображається під парою при дистанційному навчанні:",
        reply_markup=get_options_kb(),
        parse_mode="HTML"
    )
    MENU_OWNERS[msg.message_id] = message.from_user.id

@router.callback_query(F.data == "options_main")
async def options_main(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Налаштування текстів для дистанційного розкладу</b>\n\n"
        "Оберіть предмет:",
        reply_markup=get_options_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("opt_subj_"))
async def options_choose_subject(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback): return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id): return
    subject = callback.data.replace("opt_subj_", "")
    if subject not in SUBJECT_CODES:
        return await callback.answer("Невідомий предмет", show_alert=True)
    
    current = await get_subject_text(subject)
    await state.update_data(editing_subject=subject)
    await state.set_state(OptionsPanel.waiting_for_subject_text)
    
    text_preview = current[:50] + "..." if len(current) > 50 else (current or "(порожньо)")
    await callback.message.edit_text(
        f"✍️ <b>Предмет: {subject}</b>\n\n"
        f"Поточне значення: <i>{text_preview}</i>\n\n"
        "Надішліть новий текст або посилання (відобразиться під парою при дистанційному):",
        reply_markup=get_back_btn("options_main"),
        parse_mode="HTML"
    )

@router.message(OptionsPanel.waiting_for_subject_text, F.text)
async def options_save_subject_text(message: Message, state: FSMContext):
    data = await state.get_data()
    subject = data.get("editing_subject")
    if subject not in SUBJECT_CODES:
        await state.clear()
        return
    text = message.text.strip()
    await set_subject_text(subject, text)
    await state.clear()
    await message.answer(
        f"✅ Текст для <b>{subject}</b> збережено!",
        reply_markup=get_back_btn("options_main"),
        parse_mode="HTML"
    )
