from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from app.db import get_account_by_id
from app.telegram_client import get_client

from telethon.errors import FloodWaitError, RPCError

router = Router()

class TestSendGroupFSM(StatesGroup):
    waiting_for_account = State()
    waiting_for_group = State()
    waiting_for_text = State()

@router.message(F.text == "/testsendgroup")
async def start_testsendgroup(message: types.Message, state: FSMContext):
    await state.set_state(TestSendGroupFSM.waiting_for_account)
    await message.answer(
        "Введите ID аккаунта, через который пробовать отправку в группу:\n"
        "(Посмотреть ID можно в панели аккаунтов или в базе)"
    )

@router.message(TestSendGroupFSM.waiting_for_account)
async def get_account(message: types.Message, state: FSMContext):
    acc_id = message.text.strip()
    # Можно добавить проверку, что это число и что аккаунт реально есть
    acc = get_account_by_id(acc_id)
    if not acc:
        await message.answer("❗️ Не найден аккаунт с таким ID. Введите другой ID:")
        return
    await state.update_data(account_id=acc_id)
    await state.set_state(TestSendGroupFSM.waiting_for_group)
    await message.answer("Введи username или ссылку на группу (например, @mygroup или https://t.me/mygroup):")

@router.message(TestSendGroupFSM.waiting_for_group)
async def get_group(message: types.Message, state: FSMContext):
    group = message.text.strip()
    await state.update_data(group=group)
    await state.set_state(TestSendGroupFSM.waiting_for_text)
    await message.answer("Введи текст сообщения для отправки:")

@router.message(TestSendGroupFSM.waiting_for_text)
async def send_test_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    acc_id = data["account_id"]
    group = data["group"]
    text = message.text.strip()
    await message.answer("⏳ Пытаюсь отправить сообщение...")

    # Пытаемся отправить сообщение через Telethon
    result = await test_send_message_to_group(acc_id, group, text)
    await message.answer(result)
    await state.clear()

# -- Утилита отправки сообщения через Telethon --
async def test_send_message_to_group(account_id, group_username_or_link, text):
    from telethon.errors import FloodWaitError, RPCError
    try:
        acc = get_account_by_id(account_id)
        if not acc:
            return "❗️ Аккаунт не найден."

        proxy = {
            "proxy_host": acc.get("proxy_host"),
            "proxy_port": acc.get("proxy_port"),
            "proxy_username": acc.get("proxy_username"),
            "proxy_password": acc.get("proxy_password"),
        } if acc.get("proxy_host") else None
        client = await get_client(acc["session_string"], proxy)
        await client.start()
        try:
            entity = await client.get_entity(group_username_or_link)
            await client.send_message(entity, text)
            result = "✅ Сообщение в группу отправлено успешно!"
        except FloodWaitError as e:
            result = f"❗️ FloodWait: попробуй через {e.seconds} секунд"
        except RPCError as e:
            result = f"❗️ Ошибка RPC: {e}"
        except Exception as e:
            result = f"❗️ Не удалось отправить: {e}"
        await client.disconnect()
    except Exception as e:
        result = f"❗️ Ошибка на этапе инициализации клиента: {e}"
    return result
