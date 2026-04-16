"""Команди бота: підказки в Telegram (/) та текст /help."""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault


def build_help_text(is_admin: bool) -> str:
    lines = [
        "<b>Команди бота (через /)</b>",
        "",
        "<b>Усім користувачам:</b>",
        "/start — реєстрація в базі бота",
        "/help — цей список",
        "/refresh — лише показати кнопки панелі (нічого не змінює в базі)",
        "/admin або /get_admin — подати запит на права адміністратора",
        "",
    ]
    if is_admin:
        lines.extend([
            "<b>Лише адміністраторам:</b>",
            "/options — тексти для предметів при дистанційному розкладі",
            "/sne — стягнення та заохочення (Google Таблиця)",
            "/clear_polls — повністю очистити таблицю опитувань у БД",
            "/db_export — вивантажити базу у файл Excel",
            "/discipline — <code>/discipline номер_у_списку [зміна_порушень]</code>; НА з таблиці SNE (E, F)",
            "",
        ])
    else:
        lines.extend([
            "<i>Команди для адмінів приховані, доки немає прав.</i>",
            "",
        ])
    lines.append("Підказки при введенні <code>/</code> з’являються після оновлення меню в Telegram.")
    return "\n".join(lines)


async def setup_bot_commands(bot: Bot) -> None:
    """Реєструє команди в Bot API — у клієнті Telegram показуються підказки після '/' ."""
    commands = [
        BotCommand(command="start", description="Реєстрація в базі бота"),
        BotCommand(command="help", description="Усі команди та опис"),
        BotCommand(command="refresh", description="Показати кнопки панелі (без змін у БД)"),
        BotCommand(command="admin", description="Запит на права адміністратора"),
        BotCommand(command="get_admin", description="Те саме, що /admin"),
        BotCommand(command="options", description="Дистанційні тексти предметів (адмін)"),
        BotCommand(command="sne", description="Стягнення/заохочення, таблиця (адмін)"),
        BotCommand(command="clear_polls", description="Очистити опитування в БД (адмін)"),
        BotCommand(command="db_export", description="Експорт бази в Excel (адмін)"),
        BotCommand(command="discipline", description="НА та порушень курсанта (адмін)"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
