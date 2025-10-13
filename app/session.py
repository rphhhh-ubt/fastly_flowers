from telethon.sessions import StringSession
from telethon import TelegramClient
import os
import asyncio

async def convert_session_to_string(session_path, api_id, api_hash):
    """
    Конвертация .session файла в строку StringSession.
    Параметры:
      - session_path: путь к .session файлу
      - api_id, api_hash: Telegram API ID и API HASH для клиента
    """
    if not os.path.exists(session_path):
        raise FileNotFoundError(f"Файл сессии не найден: {session_path}")

    client = TelegramClient(session_path, api_id, api_hash)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        raise Exception("Клиент не авторизован. Нельзя конвертировать.")

    string_session = client.session.save()

    await client.disconnect()

    return string_session



def get_session_for_account(session_string):
    return StringSession(session_string)
