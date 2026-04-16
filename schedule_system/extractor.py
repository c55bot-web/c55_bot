import pdfplumber
import os
from .config import DATA_DIR, PDF_FILENAME, TARGET_GROUP

def get_raw_schedule():
    pdf_path = os.path.join(DATA_DIR, PDF_FILENAME)
    
    if not os.path.exists(pdf_path):
        print(f"🚨 ПОМИЛКА: Файл не знайдено: {pdf_path}")
        return []

    raw_data = []

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if not tables:
            return []

        target_variants = {
            TARGET_GROUP.replace("C", "С").replace(" ", "").upper(),
            TARGET_GROUP.replace("С", "C").replace(" ", "").upper(),
        }
        day_tokens = {
            "ПОНЕДІЛОК": "Пн",
            "ВІВТОРОК": "Вт",
            "СЕРЕДА": "Ср",
            "ЧЕТВЕР": "Чт",
            "П'ЯТНИЦЯ": "Пт",
            "ПЯТНИЦЯ": "Пт",
            "СУБОТА": "Сб",
        }

        # Підтримка різних форматів: група може бути в будь-якій колонці будь-якої таблиці.
        for table in tables:
            if not table:
                continue

            day_positions = []
            header_row = table[0] if table else []
            for col_idx, cell in enumerate(header_row):
                cell_upper = str(cell or "").upper()
                for token, day_short in day_tokens.items():
                    if token in cell_upper:
                        day_positions.append((col_idx, day_short))
                        break
            day_positions.sort(key=lambda x: x[0])

            c55_rows = []
            group_col_idx = None
            found = False

            for row in table:
                normalized_cells = [str(cell or "").replace(" ", "").upper() for cell in row]
                found_idx = next((i for i, val in enumerate(normalized_cells) if val in target_variants), None)

                if found_idx is not None:
                    found = True
                    group_col_idx = found_idx
                    c55_rows.append(row)
                    continue

                if found and group_col_idx is not None:
                    group_cell = str(row[group_col_idx] or "").strip() if group_col_idx < len(row) else ""
                    normalized_group_cell = group_cell.replace(" ", "").upper()
                    if not group_cell or normalized_group_cell in target_variants:
                        c55_rows.append(row)
                    else:
                        break

            if not c55_rows or group_col_idx is None:
                continue

            merged_cols = {}
            for row in c55_rows:
                for col_idx, cell in enumerate(row):
                    if col_idx == group_col_idx:
                        continue
                    if cell and str(cell).strip():
                        if col_idx not in merged_cols:
                            merged_cols[col_idx] = []
                        merged_cols[col_idx].append(str(cell).strip().replace("\n", " "))

            if day_positions:
                # Беремо колонки пар за реальною позицією дня в хедері.
                # Це не зсуває номера пар, якщо 1-ша (або будь-яка) пара порожня.
                for i, (start_col, day_short) in enumerate(day_positions):
                    next_start = day_positions[i + 1][0] if i + 1 < len(day_positions) else None
                    for pair_num in range(1, 5):
                        col_idx = start_col + (pair_num - 1)
                        if next_start is not None and col_idx >= next_start:
                            break
                        raw_text_cell = " ".join(merged_cols.get(col_idx, [])).strip()
                        if not raw_text_cell:
                            continue
                        raw_data.append({
                            "day": day_short,
                            "pair": pair_num,
                            "raw_text": raw_text_cell
                        })
            else:
                # Fallback для старих/нестандартних таблиць без явних днів у першому рядку.
                schedule_cols = sorted(merged_cols.keys())
                days_seq = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
                for seq_idx, col_idx in enumerate(schedule_cols):
                    day_idx = seq_idx // 4
                    if day_idx >= len(days_seq):
                        continue
                    pair_num = (seq_idx % 4) + 1
                    raw_text_cell = " ".join(merged_cols[col_idx]).strip()
                    if not raw_text_cell:
                        continue
                    raw_data.append({
                        "day": days_seq[day_idx],
                        "pair": pair_num,
                        "raw_text": raw_text_cell
                    })

        # Якщо PDF розбитий на кілька таблиць, можуть бути дублікати по (день, пара).
        # Віддаємо пріоритет більш інформативному тексту (не "СР", довший рядок).
        dedup = {}
        for row in raw_data:
            key = (row["day"], row["pair"])
            prev = dedup.get(key)
            if not prev:
                dedup[key] = row
                continue
            prev_text = (prev.get("raw_text") or "").strip().upper()
            new_text = (row.get("raw_text") or "").strip().upper()
            prev_is_sr = prev_text in ("СР", "С/Р")
            new_is_sr = new_text in ("СР", "С/Р")
            if prev_is_sr and not new_is_sr:
                dedup[key] = row
            elif len(new_text) > len(prev_text):
                dedup[key] = row
        raw_data = list(dedup.values())

        # Сортуємо для порядку
        days_order = {"Пн": 1, "Вт": 2, "Ср": 3, "Чт": 4, "Пт": 5, "Сб": 6}
        raw_data.sort(key=lambda x: (days_order.get(x["day"], 99), x["pair"]))
        
    return raw_data