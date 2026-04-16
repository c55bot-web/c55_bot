import os

# Пути к папкам (ЗБЕРЕЖЕНО ТВІЙ ФУНКЦІОНАЛ)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Настройки парсинга (Змінено лише дефолтне ім'я, бо тепер воно динамічне)
PDF_FILENAME = "current_schedule.pdf"
TARGET_GROUP = "C-55"
DEFAULT_OS_COUNT = 28  # Количество о/с для отчета

# Регулярные выражения для поиска дней недели
DAYS_PATTERN = r"^(Пн|Вт|Ср|Чт|Пт|Сб|Субота|Понеділок|Вівторок|Середа|Четвер|П'ятниця)"