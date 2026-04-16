from schedule_system.extractor import get_raw_schedule
from schedule_system.formatter import format_to_report

def run_test():
    print("🔄 Начинаю парсинг PDF...")
    try:
        raw = get_raw_schedule()
        if not raw:
            print("❌ Не удалось извлечь данные. Проверьте путь к файлу.")
            return
            
        final_report = format_to_report(raw)
        print("\n=== СФОРМИРОВАННЫЙ ОТЧЕТ ===\n")
        print(final_report)
        
        # Сохраним результат в файл для проверки
        with open("schedule_system/output/test_report.txt", "w", encoding="utf-8") as f:
            f.write(final_report)
        print("\n✅ Отчет также сохранен в schedule_system/output/test_report.txt")
        
    except Exception as e:
        print(f"💥 Произошла ошибка: {e}")

if __name__ == "__main__":
    run_test()