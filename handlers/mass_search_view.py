import asyncio, os, json
from aiogram import Router, types, F, Bot
from app.db import (
    get_task_by_id, get_task_logs, get_task_result_text,
    get_mass_search_tasks  # убедись что есть в db.py, иначе напиши простую обертку SELECT * FROM tasks WHERE type='mass_group_search'
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, FSInputFile
from aiogram.exceptions import TelegramBadRequest


router = Router()

def task_card_keyboard(task_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить информацию", callback_data=f"refresh_task_card_{task_id}")],
            [InlineKeyboardButton(text="📄 Показать лог", callback_data=f"show_task_log_{task_id}")],
            [InlineKeyboardButton(text="📊 Показать результат", callback_data=f"show_task_result_{task_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить задачу", callback_data=f"delete_task_{task_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="tasktype_mass_search")]
        ]
    )

async def safe_edit_text(msg, text, *, reply_markup=None, parse_mode="HTML"):
    try:
        await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # ничего не менялось — просто игнорируем
            return
        raise

@router.callback_query(F.data == "tasktype_mass_search")
async def open_mass_search_tasks(callback: types.CallbackQuery):
    tasks = get_mass_search_tasks(limit=10)
    if not tasks:
        await callback.message.answer("Нет задач массового парсинга групп.")
        await callback.answer()
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📋 Задача #{t['id']} — {t['created_at'].strftime('%d.%m %H:%M') if hasattr(t['created_at'], 'strftime') else t['created_at']}",
                    callback_data=f"task_card_{t['id']}"
                )
            ] for t in tasks
        ] + [
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        "<b>Выберите задачу массового парсинга групп:</b>",
        parse_mode="HTML", reply_markup=keyboard
    )
    await callback.answer()

def format_mass_search_card(task, log_lines=None):
    payload = task.get("payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    progress = task.get("progress")
    progress_text = ""
    if progress:
        prog = json.loads(progress)
        total = prog.get("total_keywords", 1)
        done = prog.get("processed_keywords", 0)
        found = prog.get("groups_found", 0)
        percent = int(done / total * 100)
        bar = "▓" * (percent // 10) + "░" * (10 - percent // 10)
        progress_text = (
            f"\n\n🔎 <b>Массовый парсинг групп</b>\n"
            f"Обработано ключей: <b>{done}/{total}</b>\n"
            f"Найдено групп: <b>{found}</b>\n"
            f"Прогресс: <b>{percent}%</b>\n"
            f"{bar}\n"
        )

    text = (
        f"<b>📋 Задача #{task['id']}</b>\n"
        f"Тип: <b>Массовый парсинг групп</b>\n"
        f"Дата создания: <code>{task.get('created_at')}</code>\n\n"
        f"🔑 <b>Ключи:</b> {', '.join(payload.get('keywords', []))}\n"
        f"👥 <b>Мин. участников:</b> {payload.get('min_members')}\n"
        f"⏱️ <b>Задержка между аккаунтами:</b> {payload.get('delay_between_accounts')}\n"
        f"⏱️ <b>Задержка между ключами:</b> {payload.get('delay_between_queries')}\n"
        f"📝 <b>Статус:</b> {task.get('status', 'неизвестно')}\n"
    )

    if log_lines:
        text += f"\nПоследние логи:\n" + "\n".join(log_lines)

    text += progress_text

    return text

async def send_task_card(bot: Bot, user_id: int, task_id: int, msg_to_edit: types.Message | None = None):
    task = get_task_by_id(task_id)
    if not task:
        # если редактировать нечего — отправим одно короткое сообщение
        if msg_to_edit:
            await safe_edit_text(msg_to_edit, "❗ Задача не найдена.", reply_markup=None, parse_mode="HTML")
        else:
            await bot.send_message(user_id, "❗ Задача не найдена.")
        return

    def _card_text():
        logs = get_task_logs(task_id)
        log_lines = [
            f"{l['timestamp']:%H:%M:%S} — {l['message']}" if hasattr(l["timestamp"], "strftime") else f"{l['timestamp']} — {l['message']}"
            for l in logs[:5]
        ]
        return format_mass_search_card(task, log_lines)

    text = _card_text()

    # создаём/берём «липкое» сообщение
    if msg_to_edit is None:
        msg_to_edit = await bot.send_message(user_id, "⋯")

    # первичная отрисовка
    await safe_edit_text(msg_to_edit, text, reply_markup=task_card_keyboard(task_id), parse_mode="HTML")

    # обновления, пока задача активна
    while task.get("status") in ("pending", "running"):
        await asyncio.sleep(2)
        task = get_task_by_id(task_id)
        text = _card_text()
        await safe_edit_text(msg_to_edit, text, reply_markup=task_card_keyboard(task_id), parse_mode="HTML")

    # финальное обновление
    task = get_task_by_id(task_id)
    text = _card_text()
    await safe_edit_text(msg_to_edit, text, reply_markup=task_card_keyboard(task_id), parse_mode="HTML")



@router.callback_query(F.data.startswith("task_card_"))
async def show_task_card(callback: types.CallbackQuery):
    await callback.answer()
    task_id = int(callback.data.split("_")[-1])
    await send_task_card(callback.bot, callback.from_user.id, task_id, msg_to_edit=callback.message)




ok_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ OK (Удалить файл)", callback_data="groupcheck_delete_file_msg")]
    ]
)

@router.callback_query(F.data.startswith("show_task_log_"))
async def show_task_log(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    logs = get_task_logs(task_id)
    file_path = f"/tmp/task_log_{task_id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        for l in logs:
            ts = l["timestamp"]
            ts_str = ts if isinstance(ts, str) else ts.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts_str}] {l['message']}\n")
    await callback.message.answer_document(
        FSInputFile(file_path),
        caption=f"📝 Лог задачи #{task_id}",
        reply_markup=ok_keyboard
    )
    os.remove(file_path)
    await callback.answer()

@router.callback_query(F.data.startswith("show_task_result_"))
async def show_task_result(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    result_text = get_task_result_text(task_id)
    if not result_text:
        await callback.message.answer("❗ Результат задачи отсутствует.")
        await callback.answer()
        return
    file_path = f"/tmp/task_result_{task_id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(result_text)
    await callback.message.answer_document(
        FSInputFile(file_path),
        caption=f"📄 Результат задачи #{task_id}",
        reply_markup=ok_keyboard
    )
    os.remove(file_path)
    await callback.answer()

@router.callback_query(F.data.startswith("refresh_task_card_"))
async def refresh_task_card(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    task = get_task_by_id(task_id)
    if not task:
        await callback.message.answer("❗ Задача не найдена.")
        return

    logs = get_task_logs(task_id)
    log_lines = [
        f"{l['timestamp']:%H:%M:%S} — {l['message']}" if hasattr(l["timestamp"], "strftime") else f"{l['timestamp']} — {l['message']}"
        for l in logs[:5]
    ]

    # Здесь также получаем полную карточку с прогрессом и логами
    text = format_mass_search_card(task, log_lines)

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=task_card_keyboard(task_id))
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.answer("Нет новых изменений.", show_alert=False)
        else:
            raise
    else:
        await callback.answer("Информация обновлена!")

