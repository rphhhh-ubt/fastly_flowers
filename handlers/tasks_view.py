# handlers/tasks_view.py

import pytz, io, uuid, os, asyncio, re, math
from aiogram import Router, types, F
from utils.check_access import admin_only
from keyboards.back_menu import back_to_main_menu_keyboard
from app.memory_storage import bulk_profile_tasks_storage
from keyboards.task_list_keyboard import task_list_keyboard
from utils.task_card_helpers import format_task_card, get_accounts_count
from app.db import (
    get_tasks_by_type,
    get_task_by_id,
    get_task_logs_by_task_id,
    get_task_del_logs_by_task_id,
    get_connection,
    get_all_accounts,
    delete_task,
    get_account_by_id,
    get_all_join_groups_tasks,
    get_join_group_task_by_id,
    get_task_summary,
    get_join_groups_logs,
    delete_task_from_db,
    get_twofa_tasks,
    read_twofa_task,
    read_twofa_logs,
    count_twofa_logs,
)
from keyboards.tasks_view_keyboards import tasks_type_keyboard
from keyboards.task_card_keyboard import get_task_card_keyboard
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from aiogram.fsm.context import FSMContext
from handlers.bulk_profile_update_task import start_bulk_update
from keyboards.delete_channels_keyboards import delete_channels_select_accounts_keyboard as build_delete_accounts_keyboard
from handlers.delete_channels_selected import handle_task_delete_channels_del
# from handlers.create_channels_task import start_create_channels  ← будущий импорт
from handlers.channel_creation import get_task_create_logs  # или импортируй из app.db
from keyboards.create_task_keyboards import create_task_type_keyboard
from utils.freeze_checker import run_freeze_check
from aiogram.filters import Command
from .join_groups_task_view import create_join_groups_task_card
from collections import defaultdict
from .like_task_view import create_like_task_card
from .twofa_task_view import create_twofa_task_card
from typing import List, Dict, Any, Tuple, Optional
from aiogram.exceptions import TelegramBadRequest
from utils.task_cards import build_reauth_task_card_text
from .comment_check_task_view import create_cchk_task_card





TASK_CREATE_HANDLERS = {
    "bulk_profile_update": start_bulk_update,
    #"delete_channels": repeat_delete_channels_task,
    #"create_channels": start_create_channels, ← добавим позже
}

router = Router()

async def _render_task_card_smart(message: types.Message, task: dict):
    """
    Пытается отрисовать карточку специализированным рендером.
    Если типа нет в реестре — падает обратно на format_task_card().
    """
    t = (task.get("type") or "").strip()

    # Реестр: тип -> асинхронная функция, которая сама редактирует message
    ASYNC_RENDERERS = {
        "like_comments": render_like_task,  # уже есть функция ниже в файле
        # сюда можно добавлять другие типы, если у них асинхронный рендер
    }

    # Реестр: тип -> функция, возвращающая (text, kb)
    PLAIN_RENDERERS = {
        "check_comments": create_cchk_task_card,  # наша новая карточка
    }

    if t in ASYNC_RENDERERS:
        await ASYNC_RENDERERS[t](message, task["id"])
        return

    if t in PLAIN_RENDERERS:
        text, kb = PLAIN_RENDERERS[t](task)
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return

    # Fallback: универсальная карточка
    text = format_task_card(task)
    keyboard = get_task_card_keyboard(task["type"], task["id"])
    await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def render_like_task(message: types.Message, task_id: int):
    from app.db import get_task_by_id, get_connection
    import json

    task = get_task_by_id(task_id)
    if not task:
        await message.edit_text("❌ Задача не найдена.")
        return

    payload = task.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    task_data = {**task, **payload}
    

    # агрегаты из логов
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN status='ok'   THEN 1 END), 0) AS likes_done,
            COALESCE(SUM(CASE WHEN status='skip' THEN 1 END), 0) AS skipped,
            COALESCE(SUM(CASE WHEN status='fail' THEN 1 END), 0) AS errors
        FROM like_comments_log
        WHERE task_id = %s
    """, (task_id,))
    likes_done, skipped, errors = cur.fetchone() or (0, 0, 0)
    cur.close(); conn.close()

    # подмешиваем
    task_data["likes_done"] = task_data.get("likes_done") or likes_done
    task_data["skipped"]    = task_data.get("skipped")    or skipped
    task_data["errors"]     = task_data.get("errors")     or errors

    channels = task_data.get("channels") or []
    posts_last = task_data.get("posts_last")
    if (task_data.get("total_posts") in (None, 0)) and channels and isinstance(posts_last, int):
        task_data["total_posts"] = len(channels) * posts_last

    # === 🔥 НОВАЯ ЛОГИКА: ОТОБРАЖЕНИЕ СТАТУСА И ОШИБКИ ===
    status = task_data.get("status", "unknown")
    last_error = task_data.get("last_error")

    if status == "error":
        status_emoji = "🔴"
        status_text = f"<b>Ошибка</b>"
        error_hint = f"\n\n<code>{last_error}</code>" if last_error else "\n\n<em>Причина не указана</em>"
    elif status == "completed":
        status_emoji = "🟢"
        status_text = "<b>Завершена</b>"
        error_hint = ""
    else:
        status_emoji = "🟡"
        status_text = f"<b>{status.capitalize()}</b>"
        error_hint = ""
    
    # карточка
    from .like_task_view import create_like_task_card
    text, kb = create_like_task_card(task_data)

    try:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        # безопасно игнорируем 'message is not modified' и похожие
        if "message is not modified" not in str(e).lower():
            raise




@router.callback_query(F.data == "repeat_task_delete_channels")
@admin_only
async def repeat_delete_channels_task(callback: types.CallbackQuery):
    print("[DEBUG] 🔁 Повтор задачи: delete_channels")
    await handle_task_delete_channels_del(callback)
    await callback.answer()



# Просмотр задач типа «Массовое обновление профиля»
@router.callback_query(F.data == "tasktype_bulk_profile_update")
@admin_only
async def view_bulk_profile_tasks(callback: types.CallbackQuery):
    tasks = get_tasks_by_type("bulk_profile_update", limit=10)

    if not tasks:
        await callback.message.edit_text(
            "🔄 <b>Массовое обновление профиля</b>\n\nПока нет сохранённых задач.",
            reply_markup=back_to_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for task in tasks:
        task_id = task["id"]
        status = task["status"]
        accounts = get_accounts_count(task)
        start_date = task["scheduled_at"].astimezone(pytz.timezone("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")

        status_symbol = {
            "completed": "✅",
            "active": "🟢",
            "error": "✅"
        }.get(status, "⏳")

        text = f"📋 #{task_id} | 👤 {accounts} | {status_symbol} | 🕓 {start_date}"
        callback_data = f"view_task_{task_id}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])

    await callback.message.edit_text(
        "🔄 <b>Массовое обновление профиля</b>\n\nВыберите задачу для просмотра:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "tasktype_delete_channels")
@admin_only
async def view_delete_channels_tasks(callback: types.CallbackQuery):
    tasks = get_tasks_by_type("delete_channels")  # получаем задачи этого типа

    if not tasks:
        await callback.message.edit_text(
            "🧹 <b>Удаление каналов</b>\n\nПока нет задач.",
            reply_markup=back_to_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for task in tasks:
        task_id = task["id"]
        status = task["status"]
        accounts = get_accounts_count(task)
        start_date = task["scheduled_at"].astimezone(pytz.timezone("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")

        status_map = {
            "completed": "✅ Завершена",
            "active": "🟢 Активна",
            "pending": "⏳ В очереди",
            "error": "❌ Ошибка"
        }
        status_text = status_map.get(task["status"], "⏳ Неизвестно")

        account_count = get_accounts_count(task)
        account_part = f"{account_count} аккаунт" if account_count == 1 else f"{account_count} аккаунта"

        text = f"🧹 #{task_id} | {status_text} | 👤 {account_part} | 🕓 {start_date}"

        callback_data = f"view_task_{task_id}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])

    await callback.message.edit_text(
        "🧹 <b>Удаление всех каналов</b>\n\nВыберите задачу для просмотра:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()



# Просмотр конкретной задачи по ID
@router.callback_query(F.data.startswith("view_task_"))
@admin_only
async def view_task_details(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[2])
        task = get_task_by_id(task_id)
        if not task:
            await callback.answer("⚠️ Задача не найдена.", show_alert=True)
            return

        await _render_task_card_smart(callback.message, task)
        await callback.answer()

    except Exception as e:
        print(f"❗ Ошибка при просмотре карточки задачи: {e}")
        await callback.answer("⚠️ Ошибка при открытии задачи.", show_alert=True)
        
@router.callback_query(F.data.startswith("repeat_task_"))
@admin_only
async def repeat_task(callback: types.CallbackQuery, state: FSMContext):
    task_type = callback.data.split("_", 2)[2]
    handler = TASK_CREATE_HANDLERS.get(task_type)

    if handler:
        await handler(callback, state)
    else:
        await callback.message.edit_text(
            f"⚠️ Повтор для задачи типа '{task_type}' пока не поддерживается.",
            reply_markup=back_to_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()


@router.callback_query(F.data.startswith("show_logs_"))
@admin_only
async def show_task_logs(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    print(f"[DEBUG] show_task_logs вызван для task_id={task_id}")
    
    task = get_task_by_id(task_id)
    if task and task["type"] == "delete_channels":
        logs = get_task_del_logs_by_task_id(task_id)
        if not logs:
            await callback.message.answer("⚠️ Логи не найдены.")
            return

        content = "\n\n".join(
            [f"🔸 Аккаунт ID {row['account_id']}\n{row['log_text'].strip()}" for row in logs]
        )
        path = f"/tmp/task_{task_id}_log.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        await callback.message.answer_document(
            document=FSInputFile(path),
            caption=f"📁 Лог удаления каналов #{task_id}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ OK (Удалить лог)", callback_data="delete_log_message")]
            ])
        )
        os.remove(path)
        await callback.answer()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, message FROM task_logs 
        WHERE task_id = %s 
        ORDER BY timestamp
    """, (task_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await callback.message.answer("⚠️ Логи не найдены для этой задачи.")
        return

    # Удаляем дубли (сохраняя порядок)
    seen = set()
    unique_lines = []
    for row in rows:
        line = f"{row[0].strftime('%Y-%m-%d %H:%M:%S')} — {row[1]}"
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)

    full_log = "\n".join(unique_lines)

    # Сохраняем в .log файл
    log_path = f"/tmp/task_log_{task_id}_{uuid.uuid4().hex}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(full_log)

    try:
        await callback.message.answer_document(
            document=FSInputFile(log_path),
            caption=f"📁 Логи задачи #{task_id}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ OK (Удалить лог)", callback_data="delete_log_message")]
            ])
        )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при отправке логов: {e}")

    try:
        os.remove(log_path)
    except Exception as e:
        print(f"[WARN] Не удалось удалить временный файл: {e}")

    await callback.answer()
    
@router.callback_query(F.data.startswith("delete_task_"))
@admin_only
async def delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])

    # Удаляем из базы
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    cur.close()
    conn.close()

    await callback.answer("✅ Задача удалена.", show_alert=True)
    await show_task_types_menu(callback)


@router.callback_query(F.data.startswith("confirm_delete_task_"))
@admin_only
async def confirm_delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_task_{task_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"view_task_{task_id}")]
    ])
    await callback.message.edit_text(
        f"❗ Вы уверены, что хотите удалить задачу #{task_id}?",
        reply_markup=keyboard
    )
    await callback.answer()




@router.callback_query(F.data == "menu_task_execution")
@admin_only
async def show_task_types_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📋 Выберите тип задач:",
        reply_markup=tasks_type_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "tasktype_create_and_set_channel")
@admin_only
async def view_create_channel_tasks(callback: types.CallbackQuery):
    

    tasks = get_tasks_by_type("create_and_set_channel", limit=10)
    

    if not tasks:
        await callback.message.edit_text(
            "📡 <b>Создание и установка каналов</b>\n\nПока нет сохранённых задач.",
            reply_markup=back_to_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    
    for task in tasks:
        task_id = task["id"]
        status = task["status"]
        accounts = task.get("accounts_count", 0)


        start_date = task["scheduled_at"].astimezone(pytz.timezone("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")

        status_symbol = {
            "completed": "✅",
            "active": "🟢",
            "error": "❌"
        }.get(status, "⏳")

        text = f"📋 #{task_id} | 👤 {accounts} | {status_symbol} | 🕓 {start_date}"
        callback_data = f"view_create_channel_task_{task_id}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])

    await callback.message.edit_text(
        "📡 <b>Создание и установка каналов</b>\n\nВыберите задачу для просмотра:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("view_create_channel_task_"))
@admin_only
async def view_create_channel_task_details(callback: types.CallbackQuery):
    

    try:
        task_id = int(callback.data.split("_")[-1])
        task = get_task_by_id(task_id)

        if not task:
            await callback.answer("⚠️ Задача не найдена.", show_alert=True)
            return

        text = format_task_card(task)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Показать лог задачи", callback_data=f"show_create_log_{task_id}")],
            [InlineKeyboardButton(text="🆕 Создать еще одну задачу", callback_data="show_create_task_menu")],            
            [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"delete_create_channel_task_{task_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="tasktype_create_and_set_channel")]
        ])

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        print(f"❗ Ошибка при просмотре карточки задачи: {e}")
        await callback.answer("⚠️ Ошибка при открытии задачи.", show_alert=True)

@router.callback_query(F.data.startswith("show_create_log_"))
@admin_only
async def show_create_task_log(callback: types.CallbackQuery):
    

    task_id = int(callback.data.split("_")[-1])
    logs = get_task_create_logs(task_id)
    

    if not logs:
        await callback.message.answer("⚠️ Логи по этой задаче не найдены.")
        return

    log_lines = [f"Аккаунт {account_id}:\n{log_text}" for account_id, log_text in logs]
    log_str = "\n\n".join(log_lines)
    path = f"/tmp/create_channels_log_{task_id}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_str)

    await callback.message.answer_document(
        FSInputFile(path),
        caption=f"📄 Лог создания и установки каналов для задачи #{task_id}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ОК", callback_data="delete_log_message")]
        ])
    )
    import os
    os.remove(path)
    await callback.answer()



@router.callback_query(F.data == "show_create_task_menu")
@admin_only
async def show_create_task_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🆕 <b>Меню создания задач</b>\n\nВыберите тип задачи:",
        reply_markup=create_task_type_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()



@router.callback_query(F.data.startswith("delete_create_channel_task_"))
@admin_only
async def confirm_delete_create_channel_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_delete_task_{task_id}"),
            InlineKeyboardButton(text="🗑 Подтвердить удаление", callback_data=f"confirm_delete_task_{task_id}"),
        ]
    ])
    await callback.message.edit_text(
        f"⚠️ Вы уверены, что хотите <b>удалить задачу #{task_id}</b>?\n\n"
        "Это действие необратимо и удалит всю информацию о задаче.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("cancel_delete_task_"))
@admin_only
async def cancel_delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    # Можно вернуть пользователя обратно в карточку задачи
    await callback.message.edit_text(
        "Удаление отменено.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку задач", callback_data="tasktype_create_and_set_channel")]]
        )
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_task_"))
@admin_only
async def do_delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    delete_task(task_id)
    await callback.message.edit_text(
        f"🗑️ Задача #{task_id} удалена.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку задач", callback_data="tasktype_create_and_set_channel")]]
        )
    )
    await callback.answer()


@router.callback_query(F.data == "task_check_freeze")
@admin_only
async def show_freeze_task(callback: CallbackQuery):
    accounts = get_all_accounts()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{acc['id']} — @{acc.get('username', 'без username')}", callback_data=f"start_freeze_check:{acc['id']}")]
        for acc in accounts if acc.get("username")
    ])
    await callback.message.edit_text("🧊 Выберите аккаунт, с которого будет производиться проверка:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("start_freeze_check:"))
@admin_only
async def start_freeze_check(callback: CallbackQuery):
    account_id = int(callback.data.split(":")[1])
    account = get_account_by_id(account_id)

    if not account or not account.get("session_string"):
        await callback.answer("⚠️ Ошибка: нет сессии для этого аккаунта.", show_alert=True)
        return

    await callback.message.edit_text("🔍 Начинаю проверку аккаунтов на заморозку. Это займёт немного времени...")

    asyncio.create_task(run_freeze_check(account))  # без блокировки
    await callback.answer("✅ Проверка запущена. Результаты появятся позже.")


@router.callback_query(F.data == "menu_join_groups_tasks")
async def show_join_groups_tasks(callback: types.CallbackQuery):
    from app.db import get_all_join_groups_tasks  # Импортируй правильно!
    tasks = get_all_join_groups_tasks()
    if not tasks:
        await callback.message.edit_text("❌ Нет задач на вступление в группы.")
        return

    keyboard = []
    for task in tasks:
        # Вытаскиваем из payload, если оно там есть
        total_accounts = "-"
        total_groups = "-"
        payload = task.get("payload")
        if payload:
            import json
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                total_accounts = data.get("total_accounts", "-")
                total_groups = data.get("total_groups", "-")
            except Exception:
                pass
        keyboard.append([
            InlineKeyboardButton(
                text=f"Задача #{task['id']} | {total_accounts} акк. | {total_groups} групп",
                callback_data=f"show_join_groups_task_{task['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")])
    await callback.message.edit_text(
        "Список задач «Вступление в группы»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("show_join_groups_task_"))
async def show_join_groups_task_card(callback: types.CallbackQuery):
    from app.db import get_join_group_task_by_id
    task_id = int(callback.data.split("_")[-1])
    task_data = get_join_group_task_by_id(task_id)
    if not task_data:
        await callback.answer("Задача не найдена!", show_alert=True)
        return

    # Добавь task_id вручную:
    if isinstance(task_data, dict):
        task_data["task_id"] = task_id
    elif isinstance(task_data, tuple):
        # например, если у тебя tuple вида (id, ...), то так:
        task_data = {
            "task_id": task_id,
            # дальше распакуй по нужным индексам,
            # например "total_accounts": task_data[1], ...
        }
    card_text, card_markup = create_join_groups_task_card(task_data)
    await callback.message.edit_text(card_text, reply_markup=card_markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("show_join_task_log_"))
async def show_join_task_log(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    logs = get_join_groups_logs(task_id)
    if not logs:
        await callback.message.answer("⚠️ Логи не найдены.")
        return

    
    acc_blocks = defaultdict(lambda: defaultdict(list))
    all_accs = set()

    # Подстрой индексы под свой формат!
    for row in logs:
        acc_id = row[2]           # <-- твой account_id (проверь индекс!)
        group_link = row[3]
        status = row[4]
        msg = row[5]
        all_accs.add(acc_id)
        acc_blocks[acc_id][status].append((group_link, msg))

    log_lines = []
    log_lines.append(f"Задача №{task_id}")
    log_lines.append(f"📝 Всего аккаунтов: {len(all_accs)}\n")
    for acc_id in all_accs:
        log_lines.append(f"\nАккаунт ID {acc_id}:\n")
        if acc_blocks[acc_id].get("no_captcha"):
            links = [g for g, _ in acc_blocks[acc_id]["no_captcha"]]
            log_lines.append("✅ Вступил в группы без капчи:\n" + "\n".join(links))
        if acc_blocks[acc_id].get("with_captcha"):
            links = [g for g, _ in acc_blocks[acc_id]["with_captcha"]]
            log_lines.append("🤖 Вступил в группы с капчей:\n" + "\n".join(links))
        if acc_blocks[acc_id].get("requested"):
            links = [g for g, _ in acc_blocks[acc_id]["requested"]]
            log_lines.append("⏳ Заявка на вступление подана (ожидает одобрения администратора):\n" + "\n".join(links))
        if acc_blocks[acc_id].get("fail"):
            fails = [f"{g} — {m}" for g, m in acc_blocks[acc_id]["fail"]]
            log_lines.append("❌ Не удалось вступить в группы:\n" + "\n".join(fails))

    log_str = "\n".join(log_lines)
    path = f"/tmp/join_groups_log_{task_id}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_str)

    await callback.message.answer_document(
        document=FSInputFile(path),
        caption=f"📄 Лог задачи вступления в группы №{task_id}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ OK (Удалить лог)", callback_data="join_groups_delete_log_msg")]
        ])
    )
    import os
    os.remove(path)
    await callback.answer()



@router.callback_query(F.data.startswith("delete_join_task_"))
async def delete_join_task(callback: types.CallbackQuery):
    import re
    match = re.match(r"delete_join_task_(\d+)", callback.data)
    if not match:
        await callback.answer("Не удалось определить ID задачи.", show_alert=True)
        return
    task_id = int(match.group(1))
    # Подтверждение
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить задачу №{task_id}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_join_task_{task_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"show_join_groups_task_{task_id}")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_join_task_"))
async def confirm_delete_join_task(callback: types.CallbackQuery):
    import re
    match = re.match(r"confirm_delete_join_task_(\d+)", callback.data)
    if not match:
        await callback.answer("Не удалось определить ID задачи.", show_alert=True)
        return
    task_id = int(match.group(1))
    delete_task_from_db(task_id)
    await callback.message.edit_text(
        "🗑️ Задача успешно удалена.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_join_groups_tasks")]
        ])
    )
    await callback.answer()





# --- Лайкинг задачи ---

def status_to_emoji(status: str) -> str:
    """
    Преобразует статус задачи в цветной эмодзи + текст.
    """
    emoji_map = {
        "running": "🟡",
        "completed": "✅",
        "error": "🔴",
        "skip": "⚪",
        "pending": "⏳",
        "paused": "⏸️",
        None: "❓"
    }
    emoji = emoji_map.get(status.lower(), "❓")
    return f"{emoji} {status}"

@router.callback_query(F.data == "menu_like_tasks")
async def show_like_tasks(callback: types.CallbackQuery):
    from app.db import get_tasks_by_type

    tasks = get_tasks_by_type("like_comments", limit=10)

    if not tasks:
        await callback.message.edit_text("❌ Нет задач на лайкинг.", reply_markup=back_to_main_menu_keyboard())
        return

    keyboard = []
    for task in tasks:
        # Извлекаем статус из payload (если он там, а не в корне таблицы)
        # Если статус в корне — используйте task['status']
        # Если в payload — используйте task['payload'].get('status', 'unknown')
        #status = task.get('status')  # ← если статус в основном поле
        # ИЛИ если статус внутри payload:
        status = task.get('payload', {}).get('status', 'unknown')

        display_status = status_to_emoji(status)
        button_text = f"Задача #{task['id']} | {display_status}"

        keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"show_like_task_{task['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")])

    await callback.message.edit_text(
        "📋 Список задач «Лайкинг комментариев»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("show_like_task_"))
async def show_like_task(callback: types.CallbackQuery):
    from app.db import get_task_by_id, get_connection
    import json

    task_id = int(callback.data.split("_")[-1])
    task_data = get_task_by_id(task_id)
    if not task_data:
        await callback.answer("Задача не найдена!", show_alert=True)
        return

    # payload → dict
    payload = task_data.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    task_data.update(payload)

    # === NEW: агрегаты из логов, если в payload пусто/нули ===
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN status='ok'   THEN 1 ELSE 0 END), 0) AS likes_done,
            COALESCE(SUM(CASE WHEN status='skip' THEN 1 ELSE 0 END), 0) AS skipped,
            COALESCE(SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END), 0) AS errors
        FROM like_comments_log
        WHERE task_id = %s
    """, (task_id,))
    agg = cur.fetchone() or (0, 0, 0)
    cur.close(); conn.close()

    # если в payload этих полей нет или они 0 — подставим агрегацию
    task_data["likes_done"] = task_data.get("likes_done") or agg[0] or 0
    task_data["skipped"]    = task_data.get("skipped")    or agg[1] or 0
    task_data["errors"]     = task_data.get("errors")     or agg[2] or 0

    # посчитаем total_posts, если 0 и есть исходные параметры
    channels = task_data.get("channels") or []
    posts_last = task_data.get("posts_last")
    if (task_data.get("total_posts") in (None, 0)) and channels and isinstance(posts_last, int):
        task_data["total_posts"] = len(channels) * posts_last

    # карточка
    from .like_task_view import create_like_task_card
    card_text, card_markup = create_like_task_card(task_data)
    await callback.message.edit_text(card_text, reply_markup=card_markup, parse_mode="HTML")


@router.callback_query(F.data == "like_delete_log_message")
async def like_delete_log_message(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
        await callback.answer("✅ Сообщение удалено.")
    except Exception:
        # fallback: просто снимаем клавиатуру
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        await callback.answer("⚠️ Не удалось удалить, снял кнопки.")


@router.callback_query(F.data.startswith("show_like_log_"))
async def show_like_task_log(callback: types.CallbackQuery):
    from app.db import get_connection
    from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
    import uuid, os

    task_id = int(callback.data.split("_")[-1])

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            COALESCE(created_at, NOW()) AS t,
            COALESCE(account_id, 0),
            COALESCE(channel, ''),
            COALESCE(post_id, 0),
            COALESCE(comment_id, 0),
            COALESCE(reaction, ''),
            COALESCE(status, ''),
            COALESCE(message, '')
        FROM like_comments_log
        WHERE task_id = %s
        ORDER BY t
    """, (task_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()

    if not rows:
        await callback.message.answer("⚠️ Логи по этой задаче не найдены.")
        await callback.answer()
        return

    lines = []
    for t, acc_id, channel, post_id, comment_id, reaction, status, message in rows:
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | acc:{acc_id} | ch:{channel} | post:{post_id} | cm:{comment_id} | {status}"
        if reaction: line += f" | rx:'{reaction}'"
        if message:  line += f" | msg:{message}"
        lines.append(line)

    path = f"/tmp/like_task_{task_id}_{uuid.uuid4().hex}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОК (Удалить лог)", callback_data="like_delete_log_message")]
    ])
    await callback.message.answer_document(
        document=FSInputFile(path),
        caption=f"📁 Лог лайкинга #{task_id}",
        reply_markup=kb
    )
    try: os.remove(path)
    except: pass
    await callback.answer()



@router.callback_query(F.data.startswith("delete_like_task_"))
async def delete_like_task(callback: types.CallbackQuery):
    from app.db import get_connection
    task_id = int(callback.data.split("_")[-1])

    conn = get_connection()
    cur = conn.cursor()
    # удаляем саму задачу типа like_comments
    cur.execute("DELETE FROM tasks WHERE id = %s AND type = 'like_comments'", (task_id,))
    tasks_deleted = cur.rowcount

    # удаляем логи по задаче
    cur.execute("DELETE FROM like_comments_log WHERE task_id = %s", (task_id,))
    logs_deleted = cur.rowcount

    conn.commit()
    cur.close(); conn.close()

    await callback.answer(f"🗑 Удалено: задач={tasks_deleted}, логов={logs_deleted}", show_alert=True)

    # вернём список задач
    from app.db import get_tasks_by_type
    tasks = get_tasks_by_type("like_comments", limit=10) or []
    keyboard = [[InlineKeyboardButton(
        text=f"Задача #{t['id']} | {t['status']}",
        callback_data=f"show_like_task_{t['id']}"
    )] for t in tasks]
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")])

    await callback.message.edit_text(
        "Список задач «Лайкинг комментариев»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("show_like_task_"))
async def show_like_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    await render_like_task(callback.message, task_id)
    await callback.answer()

@router.callback_query(F.data.startswith("refresh_like_task_"))
async def refresh_like_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    await render_like_task(callback.message, task_id)
    await callback.answer("Обновлено ✅")





# twofa хендлеры

@router.callback_query(F.data == "menu_twofa_tasks")
@admin_only
async def show_twofa_tasks(callback: types.CallbackQuery):
    tasks = get_twofa_tasks(limit=20)
    if not tasks:
        await callback.message.edit_text(
            "🔐 <b>2FA</b>\n\nЗадач пока нет.",
            reply_markup=back_to_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    kb = []
    tz = pytz.timezone("Europe/Moscow")
    for t in tasks:
        task_id = t["id"]
        status = t["status"]
        accs = t["payload"].get("accounts_count", 0)
        dt = (t.get("scheduled_at") or t.get("created_at"))
        dt_txt = dt.astimezone(tz).strftime("%d.%m.%Y %H:%M") if dt else "—"
        status_symbol = {
            "completed": "✅",
            "done": "✅",
            "running": "🟡",
            "active": "🟢",
            "pending": "⏳",
            "error": "❌",
        }.get((status or "").lower(), "❓")
        text = f"🔐 #{task_id} | 👤 {accs} | {status_symbol} | 🕓 {dt_txt}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"view_twofa_task_{task_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_task_execution")])

    await callback.message.edit_text(
        "🔐 <b>2FA — список задач</b>\nВыберите задачу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_twofa_task_"))
@admin_only
async def view_twofa_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    task = read_twofa_task(task_id)
    if not task:
        await callback.answer("⚠️ Задача не найдена.", show_alert=True)
        return

    logs_cnt = count_twofa_logs(task_id)

    task_for_card = {
        "id": task["id"],
        "status": task["status"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        # finished_at специально не передаём — тебе не нужно его показывать
        "payload": {
            "mode": task["mode"],
            "kill_other": task["kill_other"],
            "accounts": task["accounts_json"] or [],
            "new_password": task.get("new_password"),
            "old_password": task.get("old_password"),
            "logs_cnt": logs_cnt,  # ← ключевая штука для правильного статуса
        }
    }

    text, kb = create_twofa_task_card(task_for_card)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("show_twofa_log_"))
@admin_only
async def show_twofa_log(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    logs = read_twofa_logs(task_id, limit=5000)
    if not logs:
        await callback.message.answer("⚠️ Логи не найдены.")
        await callback.answer()
        return

    lines = []
    for row in logs:
        ts = row["ts"].strftime("%Y-%m-%d %H:%M:%S")
        u  = row.get("username") or row.get("account_id")
        ok = "OK" if row["ok"] else "ERR"
        rm = "removed=1" if row["removed_other"] else "removed=0"
        msg= row.get("message") or ""
        lines.append(f"[{ts}] {u}: {ok} | {rm} | {msg}")

    import uuid, os
    path = f"/tmp/twofa_task_{task_id}_{uuid.uuid4().hex}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОК (Удалить лог)", callback_data="delete_log_message")]
    ])
    await callback.message.answer_document(FSInputFile(path),
                                           caption=f"📁 Лог 2FA #{task_id}",
                                           reply_markup=kb)
    try: os.remove(path)
    except: pass
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_task_"))
@admin_only
async def confirm_delete_any_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_task_{task_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"view_task_{task_id}")]
    ])
    await callback.message.edit_text(
        f"❗ Вы уверены, что хотите удалить задачу #{task_id}?",
        reply_markup=keyboard
    )
    await callback.answer()
    


# переавторизация!
# handlers/tasks_view.py
# -*- coding: utf-8 -*-


# ---------- ВСПОМОГАТЕЛЬНЫЕ SQL-ФУНКЦИИ ----------

def _fetch_reauth_tasks(page: int, per_page: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """
    Возвращает список задач reauthorize_accounts и общее количество задач (для пагинации).
    page - с 1.
    """
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM tasks WHERE type='reauthorize_accounts'")
        total = cur.fetchone()[0]
        offset = (page - 1) * per_page
        cur.execute("""
            SELECT
              id,
              type,
              status,
              to_char(created_at AT TIME ZONE 'Europe/Moscow','YYYY-MM-DD HH24:MI:SS') AS created_msk,
              payload
            FROM tasks
            WHERE type='reauthorize_accounts'
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = cur.fetchall()
        # rows -> dict
        cols = [d.name for d in cur.description]
        tasks = [dict(zip(cols, r)) for r in rows]
        return tasks, total
    finally:
        cur.close(); conn.close()


def _fetch_one_task(task_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
              id,
              type,
              status,
              to_char(created_at AT TIME ZONE 'Europe/Moscow','YYYY-MM-DD HH24:MI:SS') AS created_msk,
              payload
            FROM tasks
            WHERE id = %s
        """, (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))
    finally:
        cur.close(); conn.close()


def _fetch_task_logs(task_id: int, limit: int = 50) -> List[Dict[str, str]]:
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
              to_char("timestamp" AT TIME ZONE 'Europe/Moscow','YYYY-MM-DD HH24:MI:SS') AS ts,
              message
            FROM task_logs
            WHERE task_id = %s
            ORDER BY id ASC
            LIMIT %s
        """, (task_id, limit))
        rows = cur.fetchall()
        return [{"ts": r[0], "message": r[1]} for r in rows]
    finally:
        cur.close(); conn.close()


# ---------- КЛАВИАТУРЫ ----------

def _kb_tasks_root():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Переавторизация", callback_data="task_reauth_list:1")],
        # при желании сюда добавишь другие типы задач
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_main")],
    ])

def _kb_reauth_list(page: int, pages: int, items: List[Dict[str, Any]]):
    rows = []
    for t in items:
        t_id = t["id"]
        status = t.get("status") or "-"
        created = t.get("created_msk") or "-"
        btn_text = f"#{t_id} • {status} • {created}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"task_reauth_open:{t_id}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"task_reauth_list:{page-1}"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"task_reauth_list:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_task_execution")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _kb_task_card(task_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"task_reauth_open:{task_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="task_reauth_list:1")],
    ])


# ---------- ХЕНДЛЕРЫ ----------

@router.callback_query(F.data == "menu_task_execution")
@admin_only
async def tasks_root(call: types.CallbackQuery):
    await call.message.edit_text("📋 <b>Список задач</b>\nВыбери категорию:", parse_mode="HTML",
                                 reply_markup=_kb_tasks_root())
    await call.answer()

@router.callback_query(F.data.startswith("task_reauth_list:"))
@admin_only
async def reauth_list(call: types.CallbackQuery):
    page = int(call.data.split(":")[1])
    page = max(1, page)
    per_page = 10

    items, total = _fetch_reauth_tasks(page, per_page)
    pages = max(1, math.ceil(total / per_page))

    text = f"🔁 <b>Переавторизация</b>\nВсего задач: <b>{total}</b>\nСтр. {page}/{pages}\n\nВыбери задачу:"
    kb = _kb_reauth_list(page, pages, items)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@router.callback_query(F.data.startswith("task_reauth_open:"))
async def task_reauth_open(call: types.CallbackQuery):
    # извлекаем task_id из callback_data
    parts = call.data.split(":")
    task_id = int(parts[1])

    # читаем строку задачи
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, type, status, created_at, payload
        FROM tasks
        WHERE id = %s
    """, (task_id,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        await call.answer("Задача не найдена", show_alert=True)
        return

    # row -> dict
    task = {
        "id": row[0],
        "type": row[1],
        "status": row[2],
        "created_at": row[3],   # timezone-aware в твоей БД
        "payload": row[4],
    }

    text = build_reauth_task_card_text(task)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Логи", callback_data=f"task_reauth_logs:{task['id']}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"task_reauth_delete:{task['id']}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку аккаунтов", callback_data="accounts_list")],
        [InlineKeyboardButton(text="⬅️ Назад к списку задач", callback_data="task_reauth_list:1")],
        
    ])

    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data.startswith("task_reauth_logs:"))
async def task_reauth_logs(call: types.CallbackQuery):
    task_id = int(call.data.split(":")[1])

    # тянем все логи по задаче
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT to_char("timestamp" AT TIME ZONE 'Europe/Moscow','YYYY-MM-DD HH24:MI:SS') AS ts_msk,
               message
        FROM task_logs
        WHERE task_id = %s
        ORDER BY id ASC
    """, (task_id,))
    logs = cur.fetchall()
    cur.close(); conn.close()

    # формируем текст
    if not logs:
        content = f"Задача #{task_id}\nЛоги отсутствуют."
    else:
        lines = [f"Задача #{task_id} — логи\n"]
        for ts, msg in logs:
            # на всякий случай страхуемся от None
            ts = ts or "-"
            msg = msg or ""
            lines.append(f"{ts}  —  {msg}")
        content = "\n".join(lines)

    # превращаем в файл и отправляем
    from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
    doc = BufferedInputFile(content.encode("utf-8"), filename=f"reauth_task_{task_id}_logs.txt")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="OK", callback_data="task_logs_close")]
    ])
    await call.message.answer_document(
        document=doc,
        caption=f"Логи задачи #{task_id}",
        reply_markup=kb
    )
    await call.answer()

@router.callback_query(F.data == "task_logs_close")
async def task_logs_close(call: types.CallbackQuery):
    try:
        # Удаляем сообщение, где нажата кнопка OK
        await call.message.delete()
    except Exception:
        pass
    await call.answer("Закрыто")

@router.callback_query(F.data.startswith("task_reauth_delete:"))
async def task_reauth_delete(call: types.CallbackQuery):
    tid = int(call.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"task_reauth_delete_confirm:{tid}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"task_reauth_open:{tid}")],
    ])
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        # если текст/клавиатура не изменились — перерисуем всю карточку
        await task_reauth_open(call)
    await call.answer("Подтвердите удаление задачи.")

def _delete_task_and_logs(task_id: int) -> bool:
    conn = get_connection(); cur = conn.cursor()
    try:
        # сначала удаляем логи, потом саму задачу
        cur.execute("DELETE FROM task_logs WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        deleted = cur.rowcount  # кол-во удалённых строк в последнем запросе
        conn.commit()
        return deleted == 1
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass

@router.callback_query(F.data.startswith("task_reauth_delete_confirm:"))
async def task_reauth_delete_confirm(call: types.CallbackQuery):
    tid = int(call.data.split(":")[1])
    ok = _delete_task_and_logs(tid)
    if ok:
        text = f"🧩 Задача #{tid} удалена."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 К списку задач", callback_data="task_reauth_list:1")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer("Удалено.")
    else:
        await call.answer("Не удалось удалить: задача не найдена.", show_alert=True)

@router.callback_query(F.data == "tasktype_check_comments")
@admin_only
async def view_check_comments_tasks(callback: types.CallbackQuery):
    from app.db import get_tasks_by_type
    tasks = get_tasks_by_type("check_comments", limit=20)
    if not tasks:
        await callback.message.edit_text("💬 Пока нет задач проверки комментариев.", reply_markup=back_to_main_menu_keyboard(), parse_mode="HTML")
        await callback.answer(); return

    kb = []
    for t in tasks:
        tid = t["id"]; st = t["status"]
        kb.append([InlineKeyboardButton(text=f"#{tid} | {st}", callback_data=f"view_task_{tid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_task_execution")])
    await callback.message.edit_text("💬 Задачи проверки комментариев:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("show_cchk_log_"))
@admin_only
async def show_cchk_log(callback: types.CallbackQuery):
    from app.db import get_comment_check_logs
    import uuid, os
    task_id = int(callback.data.split("_")[-1])
    rows = get_comment_check_logs(task_id)  # account_id, channel, can_comment, mode, message, ts
    if not rows:
        await callback.message.answer("⚠️ Логи не найдены.")
        await callback.answer(); return

    lines = []
    for acc_id, ch, can, mode, msg, ts in rows:
        can_txt = "YES" if can is True else ("NO" if can is False else "UNK")
        lines.append(f"{ts:%Y-%m-%d %H:%M:%S} | acc:{acc_id or '-'} | {ch:<32} | {can_txt:<3} | {mode or '-'} | {msg or ''}")

    path = f"/tmp/cchk_{task_id}_{uuid.uuid4().hex}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    await callback.message.answer_document(FSInputFile(path), caption=f"📁 Лог проверки комментариев #{task_id}")
    try: os.remove(path)
    except: pass
    await callback.answer()
