from aiogram import Router, types
from aiogram.filters import Command
from app.telegram_client import get_client  # твой способ получения Telethon-клиента
from utils.search_groups import search_public_groups

router = Router()

@router.message(Command("search_groups"))
async def cmd_search_groups(message: types.Message):
    # Получаем поисковый запрос (например: /search_groups Python)
    args = message.get_args()
    if not args:
        await message.answer("🔍 Укажи поисковое слово: /search_groups [ключ]")
        return

    # Выбираем аккаунт, через который будем делать поиск (например, первый доступный)
    from app.db import get_all_accounts
    accounts = get_all_accounts()
    if not accounts:
        await message.answer("⚠️ Нет аккаунтов для поиска.")
        return
    account = accounts[0]

    # Подключаемся через Telethon
    client = await get_client(account["session_string"])

    await client.connect()
    try:
        results = await search_public_groups(client, args, limit=20)
    finally:
        await client.disconnect()

    if not results:
        await message.answer("❌ Ничего не найдено.")
        return

    # Формируем и отправляем результат
    text = "🔍 Найдено:\n\n"
    for g in results:
        url = f"https://t.me/{g['username']}"
        text += f"• <b>{g['title']}</b> — <a href='{url}'>{url}</a>\n"
        if g['members']:
            text += f"  👥 {g['members']} участников\n"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
