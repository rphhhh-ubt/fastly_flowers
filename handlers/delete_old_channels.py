# handlers/delete_old_channels.py

from aiogram import Router, types
from aiogram.filters import Command
from utils.check_access import admin_only
from app.telegram_client import get_client
from app.db import get_all_accounts
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.functions.channels import DeleteChannelRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from aiogram import Bot
from app.db import insert_task_del_log
from datetime import datetime
import asyncio

router = Router()



@router.message(Command("delete_old_channels"))
@admin_only
async def delete_old_channels_handler(message: types.Message, bot: Bot, only_account_id=None, task_id=None, return_log=False):
    from app.db import update_task_status  # ✅ импорт внутрь, чтобы избежать циклов

    full_log = []
    accounts = get_all_accounts()
    if only_account_id:
        accounts = [acc for acc in accounts if acc["id"] == only_account_id]

    if not accounts:
        return "❌ Нет доступных аккаунтов." if return_log else None

    for acc in accounts:
        acc_log = []
        session = acc.get("session_string")
        account_id = acc["id"]
        username = acc.get("username") or acc.get("label") or f"ID {account_id}"
        acc_log.append(f"🔸 Аккаунт @{username}")

        try:
            client = await get_client(session)
            await client.connect()

            result = await client(
                GetDialogsRequest(
                    offset_date=None,
                    offset_id=0,
                    offset_peer=InputPeerEmpty(),
                    limit=100,
                    hash=0
                )
            )

            count_deleted = 0
            for chat in result.chats:
                if getattr(chat, "creator", False):
                    try:
                        await client(DeleteChannelRequest(channel=chat))
                        acc_log.append(f"✅ Удалён канал: {chat.title}")
                        count_deleted += 1
                    except Exception as e:
                        acc_log.append(f"⚠️ Не удалось удалить {chat.title}: {e}")

            if count_deleted == 0:
                acc_log.append("ℹ️ Нет каналов для удаления.")

            await client.disconnect()
        except Exception as e:
            acc_log.append(f"❌ Ошибка @{username}: {e}")

        acc_log_text = "\n".join(acc_log)
        full_log.append(acc_log_text)

        if task_id:
            insert_task_del_log(task_id, account_id, acc_log_text)

    # ✅ Обновляем статус задачи, если передан task_id
    if task_id:
        update_task_status(task_id, "completed")

    final_log = "\n\n".join(full_log).strip()
    return final_log if return_log else None



