from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import POLL_DISPLAY_NAMES, SUBJECT_CODES

# --- НИЖНЯ ПАНЕЛЬ (Reply) ---
def get_reply_kb(
    is_admin: bool,
    webapp_url: str = "",
    webapp_admin_v045_url: str = "",
) -> ReplyKeyboardMarkup:
    if webapp_url:
        rows = [[KeyboardButton(text="🌐 Відкрити C55 Web App", web_app=WebAppInfo(url=webapp_url))]]
        if webapp_admin_v045_url and is_admin:
            rows.append(
                [
                    KeyboardButton(
                        text="⚙️ Адмін C55 (v0.45)",
                        web_app=WebAppInfo(url=webapp_admin_v045_url),
                    )
                ]
            )
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, persistent=True)
    buttons = [[KeyboardButton(text="🎓 Панель курсанта")]]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Панель адміністратора")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, persistent=True)

# --- ПАНЕЛЬ КУРСАНТА (Inline) ---
def get_student_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мій профіль", callback_data="my_profile_inline")
    builder.button(text="📝 Подати запит", callback_data="request_menu")
    builder.button(text="🛠 Створити своє голосування", callback_data="custom_poll_start_student")
    builder.button(text="📖 Переглянути розклад", callback_data="user_sch_current")
    builder.button(text="❌ Закрити панель", callback_data="close_panel")
    builder.adjust(1)
    return builder.as_markup()

# --- ПАНЕЛЬ АДМІНІСТРАТОРА (Inline) ---
def get_main_menu_kb(is_admin: bool, approvals_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_admin:
        app_text = f"🔔 Запити ({approvals_count})" if approvals_count > 0 else "🔔 Запити"
        builder.button(text=app_text, callback_data="menu_approvals")
        builder.button(text="📋 Розрахунки о/с", callback_data="menu_start_poll")
        builder.button(text="🛠 Створити своє голосування", callback_data="custom_poll_start_admin")
        builder.button(text="📅 Керування розкладом", callback_data="admin_sch_current")
        builder.button(text="🛑 Закрити опитування", callback_data="menu_close_polls")
        builder.button(text="🔔 Покликати всіх", callback_data="ping_all")
        builder.button(text="👥 Курсанти", callback_data="menu_users")
        builder.button(text="⚙️ Авто-опитування", callback_data="menu_auto_polls")
        builder.button(text="📊 Історія", callback_data="menu_history")
        builder.button(text="❌ Закрити панель", callback_data="close_panel")

    builder.adjust(1)
    return builder.as_markup()

# --- КЛАВІАТУРА РОЗКЛАДУ ---
def get_schedule_kb(mode: str, is_next_week: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
    week_type = "next" if is_next_week else "curr"

    for d in days:
        builder.button(text=d, callback_data=f"sch_view_{week_type}_{d}_{mode}")

    if is_next_week:
        week_cb = "admin_sch_current" if mode == "admin" else "user_sch_current"
        builder.button(text="⬅️ Поточний тиждень", callback_data=week_cb)
    else:
        week_cb = "admin_sch_next" if mode == "admin" else "user_sch_next"
        builder.button(text="Наступний тиждень ➡️", callback_data=week_cb)

    if mode == "admin":
        builder.button(text="🔄 Завантажити (очно)", callback_data=f"sch_upd_{week_type}_offline")
        builder.button(text="🔄 Завантажити (онлайн)", callback_data=f"sch_upd_{week_type}_online")
        builder.button(text="🗑 Очистити", callback_data=f"sch_clear_{week_type}")
        builder.button(text="📄 Згенерувати звіт", callback_data=f"sch_rep_{week_type}")
        builder.adjust(3, 3, 1, 2, 1, 1)
        builder.button(text="🔙 Назад", callback_data="menu_main")
    else:
        builder.adjust(3, 3, 1)
        builder.button(text="🔙 Назад", callback_data="student_panel_main")

    return builder.as_markup()

def get_profile_kb(tg_id: int, is_admin_mode: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if is_admin_mode:
        builder.button(text="🗑 Видалити з бази", callback_data=f"delete_user_{tg_id}")
    
    # ЦІ КНОПКИ ТЕПЕР ДОСТУПНІ І АДМІНУ, І КУРСАНТУ
    builder.button(text="✏️ Змінити ПІБ", callback_data="edit_fullname")
    builder.button(text="📱 Змінити телефон", callback_data="edit_phone")
    builder.button(text="📍 Змінити адресу", callback_data="edit_address")
    builder.button(text="🔢 Номер за списком", callback_data="edit_listnum")
    builder.button(text="🚻 Змінити стать", callback_data="edit_gender")
    builder.button(text="🏠 Статус гуртожитку", callback_data="edit_dorm")
    
    if is_admin_mode:
        builder.button(text="🔙 До списку", callback_data="menu_users")
    else:
        builder.button(text="🔙 Назад", callback_data="student_panel_main")
        
    builder.adjust(1)
    return builder.as_markup()

# --- ІНШІ КЛАВІАТУРИ ---
def get_poll_types_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="на 08:00", callback_data="start_poll_rozvid_1")
    builder.button(text="на 21:30", callback_data="start_poll_rozvid_2")
    builder.button(text="на ФВ1", callback_data="start_poll_fp")
    builder.button(text="🚨 на зв'язку", callback_data="start_poll_alarm")
    builder.button(text="🏠 Сплата гуртожитку", callback_data="start_poll_dorm_rent")
    builder.button(text="💰 Фонд гуртожитку", callback_data="start_poll_dorm_fund")
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

def get_active_polls_keyboard(polls: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in polls:
        time_str = p.created_at.strftime('%H:%M')
        poll_name = POLL_DISPLAY_NAMES.get(p.type, p.type)
        builder.button(text=f"🛑 Закрити: {poll_name} ({time_str})", callback_data=f"close_poll_{p.tg_poll_id}")
    
    if polls:
        builder.button(text="🛑 Закрити ВСІ", callback_data="close_all_polls")
        
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

def get_users_list_kb(users: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for u in users:
        num = u.list_number if u.list_number is not None else "?"
        builder.button(text=f"{num}. {u.full_name}", callback_data=f"view_user_{u.tg_id}")
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

def get_auto_polls_kb(settings: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Додано "morning_schedule" у список
    polls = [
        ("rozvid_1", "на 08:00"),
        ("rozvid_2", "на 21:30"),
        ("dorm_rent", "Сплата гуртожитку"),
        ("dorm_fund", "Фонд гуртожитку"),
        ("morning_schedule", "Розклад о 20:00 (завтра)"),
        ("zv_reminders", "Нагадування Зв"),
    ]
    
    for key, name in polls:
        is_on = str(settings.get(f"auto_{key}", "True")) == "True"
        icon = "✅" if is_on else "❌"
        builder.button(text=f"{icon} {name}", callback_data=f"toggle_auto_{key}")
        
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()


def get_approvals_categories_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    dorm_count = counts.get("zv_dorm", 0) + counts.get("zv_release", 0)
    city_count = counts.get("zv_city", 0)
    other_count = counts.get("other", 0)
    builder.button(text=f"🏠 Зв від гурту ({dorm_count})" if dorm_count else "🏠 Зв від гурту", callback_data="menu_approvals_zv_dorm")
    builder.button(text=f"🏙 Зв у місто ({city_count})" if city_count else "🏙 Зв у місто", callback_data="menu_approvals_zv_city")
    builder.button(text=f"📝 Інше ({other_count})" if other_count else "📝 Інше", callback_data="menu_approvals_other")
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

def get_approvals_users_kb(users_with_counts: list) -> InlineKeyboardMarkup:
    """Список курсантів, у яких є запити + завжди звіт Зв на тиждень."""
    builder = InlineKeyboardBuilder()
    for user, count in users_with_counts:
        num = user.list_number if user.list_number is not None else "?"
        label = f"{num}. {user.full_name} ({count})"
        builder.button(text=label, callback_data=f"approvals_user_{user.tg_id}")
    builder.button(text="📋 Зв на цей тиждень (усі)", callback_data="export_zv_week")
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()


def get_approvals_users_kb_filtered(users_with_counts: list, category: str, show_city_report: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user, count in users_with_counts:
        num = user.list_number if user.list_number is not None else "?"
        label = f"{num}. {user.full_name} ({count})"
        builder.button(text=label, callback_data=f"approvals_user_{category}_{user.tg_id}")
    if category in ("zv_city", "zv_dorm"):
        builder.button(text="✅ Підтвердити всі", callback_data=f"approvals_confirm_all_{category}")
    if show_city_report:
        builder.button(text="📄 Звіт", callback_data="approvals_city_report")
    builder.button(text="🔙 До категорій", callback_data="menu_approvals")
    builder.adjust(1)
    return builder.as_markup()

def get_user_requests_kb(apps: list, user_id: int, user_full_name: str = "", category: str = "other") -> InlineKeyboardMarkup:
    """Список запитів конкретного курсанта."""
    from core.zv_helpers import zv_request_button_label

    builder = InlineKeyboardBuilder()
    fields_map = {'fullname': 'ПІБ', 'phone': 'Телефон', 'address': 'Адреса', 'listnum': '№ за списком', 'gender': 'Стать', 'dorm': 'Гуртожиток'}
    for app in apps:
        if app.type == 'admin_request':
            label = "🚀 Права Адміна"
        elif app.type == 'custom_request':
            preview = (app.new_value or "")[:30] + "..." if len(app.new_value or "") > 30 else (app.new_value or "")
            label = f"📝 {preview}"
        elif app.type in ('zv_release', 'zv_dorm'):
            label = f"📋 {zv_request_button_label(user_full_name)}"
            if len(label) > 62:
                label = label[:59] + "..."
        elif app.type == 'zv_city':
            label = "🏙 Подання у Зв у місто"
        else:
            field_name = fields_map.get(app.field, app.field)
            label = f"👤 {field_name}: {app.new_value}"
        builder.button(text=label, callback_data=f"view_app_{app.id}")
    builder.button(text="🔙 До списку", callback_data=f"approvals_back_{category}")
    builder.adjust(1)
    return builder.as_markup()

def get_approval_action_kb(app_id: int, is_custom: bool = False, back_to_user_id: int = None, use_full_buttons: bool = False) -> InlineKeyboardMarkup:
    """Кнопки для запиту. use_full_buttons=True — ті ж 4 кнопки що й у поданого запиту."""
    builder = InlineKeyboardBuilder()
    back_cb = "menu_approvals"
    if is_custom or use_full_buttons:
        if is_custom:
            builder.button(text="✅ Погодитись", callback_data=f"app_custom_yes_{app_id}")
            builder.button(text="❌ Відмовити", callback_data=f"app_custom_no_{app_id}")
            builder.button(text="✍️ Написати вручну", callback_data=f"app_custom_manual_{app_id}")
            builder.button(text="❓ Задати запитання", callback_data=f"app_custom_question_{app_id}")
        else:
            builder.button(text="✅ Підтвердити", callback_data=f"app_yes_{app_id}")
            builder.button(text="❌ Відхилити", callback_data=f"app_no_{app_id}")
            builder.button(text="✍️ Написати вручну", callback_data=f"app_profile_manual_{app_id}")
            builder.button(text="❓ Задати запитання", callback_data=f"app_profile_question_{app_id}")
        builder.button(text="🔙 Назад", callback_data=back_cb)
        builder.adjust(2, 2, 1)
    else:
        builder.button(text="✅ Підтвердити", callback_data=f"app_yes_{app_id}")
        builder.button(text="❌ Відхилити", callback_data=f"app_no_{app_id}")
        builder.button(text="🔙 Назад", callback_data=back_cb)
        builder.adjust(2, 1)
    return builder.as_markup()

def get_history_days_kb(dates: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in dates: builder.button(text=f"📅 {d}", callback_data=f"hist_day_{d}")
    builder.button(text="🔙 Назад", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

def get_history_polls_kb(polls: list, date_str: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in polls:
        time_str = p.created_at.strftime('%H:%M')
        poll_name = POLL_DISPLAY_NAMES.get(p.type, p.type)
        builder.button(text=f"🕒 {time_str} - {poll_name}", callback_data=f"hist_poll_{p.tg_poll_id}")
    builder.button(text="🔙 Назад до днів", callback_data="menu_history")
    builder.adjust(1)
    return builder.as_markup()

def get_history_report_kb(date_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 До списку опитувань", callback_data=f"hist_day_{date_str}")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu_main")]
    ])

def get_back_btn(target: str = "menu_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=target)]])

def get_reply_to_request_kb(app_id: int) -> InlineKeyboardMarkup:
    """Кнопка «Відповісти» під запитанням адміна для студента."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Відповісти", callback_data=f"reply_to_request_{app_id}")]
    ])

# --- OPTIONS: тексти для предметів при дистанційному ---
def get_options_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code in SUBJECT_CODES:
        builder.button(text=code, callback_data=f"opt_subj_{code}")
    builder.button(text="🔙 Закрити", callback_data="close_panel")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()