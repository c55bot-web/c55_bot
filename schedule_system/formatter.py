import re

# Фамілія -> повний ПІБ викладача (розклад часто містить тільки фамілію)
TEACHERS_FULL = {
    "Бузань": "Бузань В.Ю.",
    "Крошко": "Крошко Н.В.",
    "Білий": "Білий О.Г.",
    "Гордієнко": "Гордієнко О.С.",
    "Браєвська": "Браєвська А.І.",
    "Гришко": "Гришко Л.Г.",
    "Качалов": "Качалов О.Ю.",
    "Субач": "Субач І.Ю.",
    "Шолохов": "Шолохов С.М.",
    "Мітін": "Мітін С.В.",
    "Куліков": "Куліков В.М.",
}


def expand_teacher(teacher: str) -> str:
    """Якщо в розкладі лише фамілія — підставляє повний ПІБ."""
    if not teacher or " " in teacher.strip():
        return teacher  # вже є ініціали
    surname = teacher.strip()
    return TEACHERS_FULL.get(surname, teacher)


# Коди предметів для підстановки тексту при дистанційному (відповідає core.config.SUBJECT_CODES)
SUBJECT_CODES_MATCH = ["УКРЄ", "МА2", "АМ1", "ФВ1", "СБД", "5КСАК", "3ТЙ", "5АП2"]

def extract_subject_code(lesson_text: str) -> str | None:
    """Витягує код предмету з lesson_text для підстановки тексту при дистанційному.
    Наприклад: '5АП2 (2/10пз) Куліков' -> '5АП2', 'МА2 (2/9л) Крошко' -> 'МА2'."""
    if not lesson_text:
        return None
    text_upper = lesson_text.upper().strip()
    # Фізкультура -> ФВ1
    if "ФВ" in text_upper or "ФІЗ" in text_upper or "ФИЗ" in text_upper:
        return "ФВ1"
    # Сортуємо за довжиною (довші спочатку), щоб "МА2" не співпав з частиною іншого
    for code in sorted(SUBJECT_CODES_MATCH, key=len, reverse=True):
        if code in text_upper:
            return code
    return None

def parse_lesson(raw_text):
    if not raw_text or not raw_text.strip():
        return None

    text_upper = raw_text.upper().strip()

    # 1. Жорстке правило для Фізкультури
    if "ФВ" in text_upper or "КАЧАЛОВ" in text_upper or "ГРИШКО" in text_upper:
        loc = "фіз. виховання, спорткомплекс"
        if "ЯДРО" in text_upper:
            loc = "фіз. виховання, МАЛЕ ЯДРО"
        return {"full": "Фіз. виховання", "loc": loc}

    # 2. Шукаємо корпуси і аудиторії
    matches = re.findall(r'(\d+)-(\d+)к', raw_text, re.IGNORECASE)

    # 3. Перевірка на Самостійну роботу (СР)
    # Якщо є "СР", але немає кабінету — ігноруємо пару повністю
    parts_upper = text_upper.split()
    if ("СР" in parts_upper or "С/Р" in parts_upper or text_upper == "СР") and not matches:
        return None

    # 4. Витягуємо назву предмета та тип
    parts = raw_text.split()
    subject = ""
    lesson_type = ""
    teacher = ""
    
    if len(parts) >= 1:
        subject = parts[0]
    if len(parts) >= 2:
        # Перевіряємо чи є цифри або слеш у другому слові (зазвичай це тип: 2/7пз, 2/1л)
        if any(char.isdigit() for char in parts[1]) or '/' in parts[1]:
            lesson_type = parts[1]
            teacher = " ".join(parts[2:])
        else:
            teacher = " ".join(parts[1:])

    if matches:
        locations = []
        for aud, nk in matches:
            loc_str = f"{nk} НК, {aud} ауд"
            if loc_str not in locations:
                locations.append(loc_str)
        loc_final = " / ".join(locations)
        
        # Для очного: Предмет (тип) НК, ауд
        if subject and lesson_type:
            full_text = f"{subject} ({lesson_type}) {loc_final}"
        elif subject:
            full_text = f"{subject} {loc_final}"
        else:
            full_text = loc_final
            
    else:
        # НЕМАЄ АУДИТОРІЇ
        # Просто збираємо предмет і викладача до купи
        clean_text = " ".join(parts)
        
        if subject and lesson_type:
            full_text = f"{subject} ({lesson_type})"
            if teacher:
                full_text += f" {expand_teacher(teacher)}"
        elif subject:
            full_text = f"{subject} {expand_teacher(teacher)}".strip()
        else:
            full_text = clean_text

        # Оскільки кабінету немає, у командирський звіт піде назва предмета, щоб пара не була пустою
        loc_final = full_text

    return {"full": full_text.strip(), "loc": loc_final.strip()}