# 📆 Основной стартовый каркас Telegram-бота для проекта (aiogram v3)

import os
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import BotCommand
from handlers import register_all_handlers
from config import BOT_TOKEN, ADMIN_IDS
from app.db import DB_CONFIG  # проверяем, что конфиг БД подтянулся
from app.lic_client import LicenseClient, LicenseError

# ── Логирование ────────────────────────────────────────────────────────────────
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

print("✅ Database config loaded successfully!")

async def on_startup(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="boost", description="👁 Накрутка просмотров постов"),
        # Добавь сюда другие команды по мере необходимости
    ])

# ── Основной async-вход ───────────────────────────────────────────────────────
# ── Основной async-вход ───────────────────────────────────────────────────────
async def main() -> None:
    # 1) Лицензия
    lic = LicenseClient()
    try:
        await lic.ensure_license()
    except LicenseError as e:
        log.error("License check failed: %s", e)
        raise SystemExit(1)
    #lic.spawn_auto_renew(asyncio.get_event_loop())

    # 2) Бот/диспетчер
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(fsm_strategy=FSMStrategy.CHAT)

    # >>> ВРЕМЕННЫЕ ТЕСТОВЫЕ ХЭНДЛЕРЫ (по желанию для диагностики)
    # from aiogram import Router, types, F
    # test = Router()
    # @test.message(F.text == "/ping")
    # async def ping(m: types.Message): await m.answer("pong")
    # @test.message()
    # async def mirror(m: types.Message): await m.answer(f"echo: {m.text}")
    # dp.include_router(test)
    # <<<

    register_all_handlers(dp)
    dp.startup.register(on_startup)

    # >>> ВСТАВЬ ВОТ ЭТИ 3 СТРОКИ ПЕРЕД start_polling <<<
    me = await bot.get_me()
    print(f"🤖 Running as @{me.username} (id={me.id})")
    await bot.delete_webhook(drop_pending_updates=True)
    # >>> КОНЕЦ ВСТАВКИ <<<

    log.info("🤖 Bot is starting polling…")
    await dp.start_polling(bot)


# ── Точка старта ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(main())
