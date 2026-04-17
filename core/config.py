import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", 0))

_thread_id_str = os.getenv("MESSAGE_THREAD_ID", "")
MESSAGE_THREAD_ID = int(_thread_id_str) if _thread_id_str.isdigit() else None

# Додано змінну для треду розкладу (якщо не вказано, кине в загальний MESSAGE_THREAD_ID)
_sch_thread_id_str = os.getenv("SCHEDULE_THREAD_ID", "")
SCHEDULE_THREAD_ID = int(_sch_thread_id_str) if _sch_thread_id_str.isdigit() else None

# URL Telegram Mini App для подання "Зв з гуртожитку" (HTTPS, публічно доступний)
ZV_DORM_WEBAPP_URL = os.getenv("ZV_DORM_WEBAPP_URL", "").strip()
# Єдиний URL C55 Web App (якщо не задано — використовуємо ZV_DORM_WEBAPP_URL)
C55_WEBAPP_URL = os.getenv("C55_WEBAPP_URL", ZV_DORM_WEBAPP_URL).strip()
# Опційно: повний URL старої збірки адмін-панелі (v0.45). Якщо порожньо — шлях /v0.45/ вставляється перед /webapp/ чи /docs/.
C55_WEBAPP_URL_V045 = os.getenv("C55_WEBAPP_URL_V045", "").strip()

# Публічний HTTPS endpoint для Mini App API (не github.io). Потрібен, щоб WebApp міг робити fetch без tg.sendData.
C55_WEBAPP_API_URL = os.getenv("C55_WEBAPP_API_URL", "").strip().rstrip("/")
# aiohttp слухач для API (зазвичай за nginx TLS reverse-proxy)
C55_WEBAPP_API_HOST = os.getenv("C55_WEBAPP_API_HOST", "127.0.0.1").strip()
_c55_api_port = os.getenv("C55_WEBAPP_API_PORT", "8787").strip()
C55_WEBAPP_API_PORT = int(_c55_api_port) if _c55_api_port.isdigit() else 8787

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# Чат для сповіщень про нові запити (якщо не вказано — перший адмін)
_req_chat = os.getenv("REQUEST_NOTIFY_CHAT_ID", "")
REQUEST_NOTIFY_CHAT_ID = int(_req_chat) if _req_chat.strip().isdigit() else (ADMIN_IDS[0] if ADMIN_IDS else None)

if not BOT_TOKEN:
    raise ValueError("Токен бота не знайдено! Перевір файл .env")

# Google Sheets: Стягнення/Заохочення (команда /sne)
# За замовчуванням використовуємо останню таблицю С-55_Заохочення_Стягнення
SNE_SPREADSHEET_ID = os.getenv("SNE_SPREADSHEET_ID", "1tGO_htCdJCS8Gh87UynExCp-_grIRUA7BF3-gaZK8RY")
SNE_CREDENTIALS_PATH = os.getenv("SNE_CREDENTIALS_PATH", "sne_credentials.json")
# Перший рядок даних курсантів (рядок 4 = 01., 5 = 02., ...)
SNE_DATA_START_ROW = 4

# Стягнення: callback_key -> (колонка A=1, значення для додавання, назва)
SNE_PENALTIES = {
    "sne_pen_robota": ("D", -1, "Не здана робота (-1 б.)"),
    "sne_pen_at1": ("E", -1.5, "I атестація (-1,5 б.)"),
    "sne_pen_at2": ("F", -1.5, "II атестація (-1,5 б.)"),
    "sne_pen_zap": ("G", -1, "Запізнення (-1 б.)"),
    "sne_pen_ranok": ("H", -1, "Ранковий огляд (-1 б.)"),
    "sne_pen_stroy": ("I", -1, "Дисципліна в строю (-1 б.)"),
    "sne_pen_nezjav": ("J", -2, "Не з'явився без причини (-2 б.)"),
    "sne_pen_inshi": ("K", -1, "Інші (-1 б.)"),
}
# Заохочення
SNE_REWARDS = {
    "sne_rew_para": ("L", 0.1, "Відповідь на парі (+0,1 б.)"),
    "sne_rew_raport": ("M", 0.4, "Розказати рапорт (+0,4 б.)"),
    "sne_rew_at1": ("N", 1.5, "I атестація (+1,5 б.)"),
    "sne_rew_at2": ("O", 1.5, "II атестація (+1,5 б.)"),
    "sne_rew_poza": ("P", 2.5, "Позачерг. нар. (+2,5 б.)"),
    "sne_rew_zahody": ("Q", 2, "Заходи (+2 б.)"),
    "sne_rew_smittya": ("R", 1, "Винести сміття (+1 б.)"),
    "sne_rew_cherga": ("S", 1, "Доп. черг. по ауд. (+1 б.)"),
    "sne_rew_inshi": ("T", 0.5, "Інші (+0,5 б.)"),
}

# Словник для збереження власників меню (захист від чужих натискань)
MENU_OWNERS = {}

# Коди предметів для налаштування тексту при дистанційному навчанні
SUBJECT_CODES = ["УКРЄ", "МА2", "АМ1", "ФВ1", "СБД", "5КСАК", "3ТЙ", "5АП2"]

# Відображувані назви опитувань (відповідають кнопкам)
POLL_DISPLAY_NAMES = {
    "rozvid_1": "Ранковий (08:00)",
    "rozvid_2": "Вечірній (21:30)",
    "fp": "Фіз. виховання",
    "alarm": "🚨 На зв'язку",
    "dorm_rent": "🏠 Оплата гуртожитку",
    "dorm_fund": "💰 Фонд гуртожитку",
    "custom": "Власне голосування",
}

# Конфігурація всіх опитувань (ПОВНІСТЮ ТВОЯ)
POLLS_CONFIG = {
    "rozvid_1": {
        "question": "Розрахунок о/с групи С-55 станом на 08:00 {date}",
        "options": [
            "В/н",
            "Зв/г",
            "Зв/к",
            "В",
            "Хв/г",
            "Хв/к",
            "Хв/зв",
            "Ш"
        ]
    },
    "rozvid_2": {
        "question": "Розрахунок о/с групи С-55 станом на 21:30 {date}",
        "options": [
            "В/н",
            "Зв/г",
            "Зв/к",
            "В",
            "Хв/г",
            "Хв/к",
            "Хв/зв",
            "Ш"
        ]
    },
    "fp": {
        "question": "Розрахунок о/с групи С-55 на пару Фізичного виховання {date}",
        "options": [
            "В/н",
            "З/в",
            "Зв/г",
            "Зв/к",
            "Хв/г",
            "Хв/к",
            "Хв/зв",
            "Ш"
        ]
    },
    "alarm": {
        "question": "🚨 На зв'язку {date}",
        "options": [
            "✅ 1 Віділення",
            "❌ 1 Віділення",
            "✅ 2 Віділення",
            "❌ 2 Віділення"
        ]
    },
    "dorm_rent": {
        "question": "🏠 Оплата гуртожитку (за {month})",
        "options": [
            "✅ 1 Віділення",
            "❌ 1 Віділення",
            "✅ 2 Віділення",
            "❌ 2 Віділення"
        ]
    },
    "dorm_fund": {
        "question": "💰 Фонд гуртожитку (за {month})",
        "options": [
            "✅ 1 Віділення",
            "❌ 1 Віділення",
            "✅ 2 Віділення",
            "❌ 2 Віділення"
        ]
    }
}