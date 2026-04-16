"""Окреме меню /sne — стягнення та заохочення. Відкривається тільки командою, не в панелях."""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.config import (
    SNE_SPREADSHEET_ID, SNE_CREDENTIALS_PATH, SNE_DATA_START_ROW,
    SNE_PENALTIES, SNE_REWARDS
)
from database.requests import check_is_admin, async_session
from database.models import User
from sqlalchemy import select

router = Router()

SNE_OWNERS = {}  # Окремий словник для меню /sne


def _get_sheet_client():
    """Повертає клієнт gspread або None якщо не налаштовано."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(SNE_CREDENTIALS_PATH, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        logging.error(f"SNE: не вдалося підключитися до Google Sheets: {e}")
        return None


def _update_sne_cell(list_number: int, col_letter: str, value_delta: float) -> tuple[bool, str]:
    """В тупу додає value_delta до клітинки у діапазоні D4:T31"""
    client = _get_sheet_client()
    if not client:
        return False, "❌ Google Sheets не налаштовано."
    try:
        sh = client.open_by_key(SNE_SPREADSHEET_ID)
        ws = sh.sheet1
        
        # Оскільки №1 починається з 4-го рядка, обчислюємо так:
        row = 3 + list_number 
        cell_addr = f"{col_letter}{row}"
        
        # 1. Читаємо поточне значення
        current = ws.acell(cell_addr).value
        
        # 2. Робимо з нього нормальне число для Python
        if not current:
            current_val = 0.0
        else:
            # Прибираємо пробіли і міняємо кому на крапку
            clean_str = str(current).strip().replace(",", ".")
            try:
                current_val = float(clean_str)
            except ValueError:
                current_val = 0.0 # Якщо там був якийсь текст
                
        # 3. Додаємо нове значення і округлюємо
        new_val = round(current_val + value_delta, 2)
        
        # 4. Формуємо рядок з комою (як прийнято у твоїй таблиці)
        final_str_val = str(new_val).replace(".", ",")
        
        # 5. ВАЖЛИВО: Записуємо як USER_ENTERED! 
        # Це змушує Google Sheets сприйняти це як введення з клавіатури (числом), а не як голий текст.
        ws.update(
            range_name=cell_addr,
            values=[[final_str_val]],
            value_input_option="USER_ENTERED"
        )
        
        return True, f"✅ Оновлено ({current_val} ➡️ {new_val})"
    except Exception as e:
        import logging
        logging.exception(f"SNE update error in {cell_addr}: {e}")
        return False, "❌ Помилка при оновленні таблиці (див. лог)."


def _sne_main_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📉 Стягнення", callback_data="sne_penalties")
    b.button(text="📈 Заохочення", callback_data="sne_rewards")
    b.button(text="❌ Закрити", callback_data="sne_close")
    b.adjust(1)
    return b.as_markup()


def _sne_types_kb(types_dict: dict, prefix: str):
    b = InlineKeyboardBuilder()
    for key, (_, _, label) in types_dict.items():
        b.button(text=label, callback_data=f"sne_type_{key}")
    b.button(text="🔙 Назад", callback_data="sne_main")
    b.adjust(1)
    return b.as_markup()


def is_sne_owner(callback: CallbackQuery) -> bool:
    owner_id = SNE_OWNERS.get(callback.message.message_id)
    return not owner_id or owner_id == callback.from_user.id


@router.message(Command("sne"))
async def cmd_sne(message: Message):
    """Окреме меню стягнень/заохочень. Тільки для адмінів."""
    if not await check_is_admin(message.from_user.id):
        await message.answer("❌ Команда доступна лише адміністраторам.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    msg = await message.answer(
        "📋 <b>Стягнення та заохочення</b>\n\n"
        "Оберіть категорію:",
        reply_markup=_sne_main_kb(),
        parse_mode="HTML"
    )
    SNE_OWNERS[msg.message_id] = message.from_user.id


@router.callback_query(F.data == "sne_main")
async def sne_main(callback: CallbackQuery):
    if not is_sne_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    await callback.message.edit_text(
        "📋 <b>Стягнення та заохочення</b>\n\nОберіть категорію:",
        reply_markup=_sne_main_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "sne_penalties")
async def sne_penalties(callback: CallbackQuery):
    if not is_sne_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    await callback.message.edit_text(
        "📉 <b>Стягнення</b>\n\nОберіть тип:",
        reply_markup=_sne_types_kb(SNE_PENALTIES, "pen"),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "sne_rewards")
async def sne_rewards(callback: CallbackQuery):
    if not is_sne_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    await callback.message.edit_text(
        "📈 <b>Заохочення</b>\n\nОберіть тип:",
        reply_markup=_sne_types_kb(SNE_REWARDS, "rew"),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sne_type_"))
async def sne_choose_cadet(callback: CallbackQuery):
    if not is_sne_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    entry_key = callback.data.replace("sne_type_", "")
    all_entries = {**SNE_PENALTIES, **SNE_REWARDS}
    if entry_key not in all_entries:
        return await callback.answer("Невідомий тип", show_alert=True)
    col_letter, value, label = all_entries[entry_key]
    SNE_OWNERS[callback.message.message_id] = callback.from_user.id

    async with async_session() as session:
        users = (
            await session.execute(
                select(User).order_by(User.list_number.asc().nulls_last(), User.full_name)
            )
        ).scalars().all()

    b = InlineKeyboardBuilder()
    for u in users:
        num = u.list_number if u.list_number is not None else 0
        if num < 1:
            continue
        b.button(
            text=f"{num}. {u.full_name}",
            callback_data=f"sne_apply_{entry_key}_{num}"
        )
    b.button(text="🔙 Назад", callback_data="sne_penalties" if entry_key.startswith("sne_pen_") else "sne_rewards")
    b.adjust(1)

    await callback.message.edit_text(
        f"📋 <b>{label}</b>\n\nОберіть курсанта:",
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sne_apply_"))
async def sne_apply(callback: CallbackQuery):
    if not is_sne_owner(callback):
        return await callback.answer("❌ Це меню викликав інший користувач!", show_alert=True)
    if not await check_is_admin(callback.from_user.id):
        return await callback.answer("❌ Немає прав!", show_alert=True)
    rest = callback.data.replace("sne_apply_", "")
    parts = rest.rsplit("_", 1)
    if len(parts) != 2:
        return await callback.answer("Помилка даних", show_alert=True)
    entry_key, list_num_str = parts
    try:
        list_num = int(list_num_str)
    except ValueError:
        return await callback.answer("Невірний номер", show_alert=True)
    all_entries = {**SNE_PENALTIES, **SNE_REWARDS}
    if entry_key not in all_entries:
        return await callback.answer("Невідомий тип", show_alert=True)
    col_letter, value, label = all_entries[entry_key]
    ok, msg = _update_sne_cell(list_num, col_letter, value)
    await callback.answer(msg, show_alert=True)
    if ok:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text="🔙 Головне меню", callback_data="sne_main")
        await callback.message.edit_text(
            f"✅ Запис оновлено.\n\n{label}\nКурсант №{list_num}.",
            reply_markup=kb_builder.as_markup(),
            parse_mode="HTML"
        )
        SNE_OWNERS[callback.message.message_id] = callback.from_user.id


@router.callback_query(F.data == "sne_close")
async def sne_close(callback: CallbackQuery):
    if is_sne_owner(callback):
        await callback.message.delete()
        mid = callback.message.message_id
        if mid in SNE_OWNERS:
            del SNE_OWNERS[mid]
    await callback.answer("Закрито")
