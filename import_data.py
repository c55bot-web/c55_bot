import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import json
from sqlalchemy import select
from database.requests import engine, async_session, init_db
from database.models import User, UserDiscipline

async def load_users_from_json():
    await init_db()
    
    with open('users_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    async with async_session() as session:
        for tg_id_str, info in data.items():
            tg_id = int(tg_id_str)
            user = await session.scalar(select(User).where(User.tg_id == tg_id))

            phone = None if info.get('phone') == "Не_налаштував" else info.get('phone')
            addr = None if info.get('address') == "Не_налаштував" else info.get('address')

            if not user:
                user = User(
                    tg_id=tg_id,
                    full_name=info['full_name'],
                    username=info.get('username'),
                    phone_number=phone,
                    address=addr,
                    in_dorm=info.get('in_dorm', True),
                    list_number=None
                )
                session.add(user)
                session.add(UserDiscipline(tg_id=tg_id))
            else:
                user.full_name = info['full_name']
                user.username = info.get('username')
                user.in_dorm = info.get('in_dorm', True)

        await session.commit()
        
    print(f"✅ Успішно імпортовано/оновлено {len(data)} курсантів до бази даних SQLite!")

if __name__ == '__main__':
    asyncio.run(load_users_from_json())