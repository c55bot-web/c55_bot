#!/bin/bash

# Переходимо в папку з проєктом
cd ~/telegram_bot/C55_bot/c55_bot

# Запускаємо screen у фоновому режимі (-dm) з назвою "bot_session".
# Всередині ми по черзі: вмикаємо Conda -> активуємо bot_env -> запускаємо бота.
# ; exec bash в кінці не дасть екрану закритися, якщо бот раптом видасть помилку.
screen -dmS bot_session bash -c 'source $HOME/miniconda/bin/activate && conda activate bot_env && python main.py; exec bash'

echo "✅ Бот успішно запущено у фоні (сесія screen: bot_session)!"
