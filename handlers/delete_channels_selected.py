import asyncio, os, sys, json
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from aiogram import Router, types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, FSInputFile
from utils.check_access import admin_only
from app.db import get_all_accounts, create_task_entry, get_task_del_logs, get_account_groups_with_count
from handlers.delete_old_channels import delete_old_channels_handler
from keyboards.main_menu import start_menu_keyboard
from aiogram.exceptions import TelegramBadRequest  # ДОБАВЬ
from typing import List, Dict, Any




router = Router()
selected_accounts_del: dict[int, list[int]] = {}
selected_page_del: dict[int, int] = {}  # текущая страница выбора на пользователя

PER_PAGE_DEL = 10

async def safe_edit_markup(message: types.Message, reply_markup: InlineKeyboardMarkup):
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        # гасим только безвредный кейс "message is not modified"
        if "message is not modified" not in str(e):
            raise

def delch_accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected_ids: list[int] | set[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    groups: List[Dict[str, Any]] | None = None,   # ← NEW
) -> InlineKeyboardMarkup:
    selected = set(selected_ids or [])
    start = page * per_page
    chunk = accounts[start : start + per_page]

    rows = []
    for acc in chunk:
        acc_id = acc["id"]
        uname = acc.get("username") or "-"
        if uname != "-" and not str(uname).startswith("@"):
            uname = f"@{uname}"
        phone = acc.get("phone") or "-"
        mark  = "✅" if acc_id in selected else "⏹️"
        txt   = f"{mark} {acc_id} ▸ {uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"delch_toggle:{acc_id}")])

    # пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"delch_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"delch_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп (только группы с count>=1)
    chips = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name  = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"delch_group_pick:{g['id']}"))
    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые кнопки
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="delch_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="delch_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="delch_next"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)




@router.callback_query(F.data == "task_delete_channels_del")
@admin_only
async def handle_task_delete_channels_del(callback: types.CallbackQuery):
    accounts = get_all_accounts()
    groups   = get_account_groups_with_count()  # ← NEW
    user_id = callback.from_user.id
    selected_accounts_del[user_id] = []
    selected_page_del[user_id] = 0

    await callback.message.edit_text(
        "🧹 Выберите аккаунты для удаления каналов:",
        reply_markup=delch_accounts_keyboard(accounts, [], page=0, groups=groups),  # ← pass groups
        parse_mode="HTML"
    )
    await callback.answer()



@router.callback_query(F.data.startswith("delch_toggle:"))
@admin_only
async def delch_toggle_account(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    acc_id = int(callback.data.split(":")[1])

    selected = set(selected_accounts_del.get(user_id, []))
    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)
    selected_accounts_del[user_id] = list(selected)

    accounts = get_all_accounts()
    groups = get_account_groups_with_count()
    page = int(selected_page_del.get(user_id, 0))
    await safe_edit_markup(
        callback.message,
        delch_accounts_keyboard(accounts, selected, page=page, groups=groups)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("delch_page:"))
@admin_only
async def delch_page_switch(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    selected_page_del[user_id] = page

    accounts = get_all_accounts()
    groups = get_account_groups_with_count()
    selected = selected_accounts_del.get(user_id, [])
    await safe_edit_markup(
        callback.message,
        delch_accounts_keyboard(accounts, selected, page=page, groups=groups)
    )
    await callback.answer()

@router.callback_query(F.data == "delch_select_all")
@admin_only
async def delch_select_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()
    all_ids = [a["id"] for a in accounts]
    selected_accounts_del[user_id] = all_ids

    page = int(selected_page_del.get(user_id, 0))
    await safe_edit_markup(
        callback.message,
        delch_accounts_keyboard(accounts, all_ids, page=page, groups=groups)
    )
    await callback.answer("✅ Выбраны все")

@router.callback_query(F.data == "delch_clear_all")
@admin_only
async def delch_clear_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()
    selected_accounts_del[user_id] = []

    page = int(selected_page_del.get(user_id, 0))
    await safe_edit_markup(
        callback.message,
        delch_accounts_keyboard(accounts, [], page=page, groups=groups)
    )
    await callback.answer("♻️ Сброшен выбор")


@router.callback_query(F.data == "delch_next")
@admin_only
async def delch_next(callback: types.CallbackQuery):
    # просто переиспользуем существующий раннер
    await run_deletion_del(callback, callback.message.bot)



@router.callback_query(F.data == "proceed_delete_channels_del")
@admin_only
async def run_deletion_del(callback: types.CallbackQuery, bot: Bot):
    print("[DEBUG] 👉 Вызван run_deletion_del")

    user_id = callback.from_user.id
    selected_ids = selected_accounts_del.get(user_id, [])

    if not selected_ids:
        await callback.answer("⚠️ Ни один аккаунт не выбран!", show_alert=True)
        return

    # 1. Создаём task_id
    
    payload = json.dumps({"accounts": selected_ids})
    task_id = create_task_entry(task_type="delete_channels", created_by=user_id, payload=payload)


    # 2. Уведомление
    await callback.message.edit_text(
        "⏳ Задача *удаление каналов* начата.\nЧерез пару секунд вы получите лог.",
        parse_mode="Markdown"
    )
    await asyncio.sleep(2)

    # 3. Возврат в меню
    await callback.message.edit_text(
        "Ваша задача создана! Ожидайте лог!\n\n Выберете что необходимо сделать далее.",
        reply_markup=start_menu_keyboard()
    )

    # 4. Запускаем задачи параллельно
    async def run_one(acc_id):
        fake_message = Message.model_construct(
            message_id=callback.message.message_id,
            date=callback.message.date,
            chat=callback.message.chat,
            from_user=callback.from_user,
            text="/delete_old_channels"
        )
        await delete_old_channels_handler(fake_message, bot, only_account_id=acc_id, task_id=task_id)

    await asyncio.gather(*[run_one(acc_id) for acc_id in selected_ids])

    # 5. Получаем логи из task_del
    task_logs = get_task_del_logs(task_id)  # List[str]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines = [
        f"🗓️ Дата и время запуска задачи: {now_str}",
        f"👤 ID выбранных аккаунтов: {', '.join(str(i) for i in selected_ids)}",
        ""
    ]

    # Форматируем каждый лог по аккаунту
    for log in task_logs:
        lines = log.strip().splitlines()
        if not lines:
            continue
        header = lines[0].replace("🔸 Аккаунт", "🔸 В аккаунте")
        log_lines.append(header)
        log_lines.extend(lines[1:])
        log_lines.append("___________________________________________\n")

    # 6. Сохраняем лог в файл
    log_text = "\n".join(log_lines).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/delete_channels_log_{timestamp}.txt"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_text)

    # 7. Отправляем лог
    await callback.message.answer_document(
        FSInputFile(log_path),
        caption="🧹 Лог удаления каналов",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆗 ОК", callback_data="delete_log_message")]
        ])
    )


    selected_accounts_del.pop(user_id, None)
    selected_page_del.pop(user_id, None)






@router.callback_query(F.data == "back_to_task_menu")
@admin_only
async def back_to_task_menu(callback: types.CallbackQuery):
    print("[DEBUG] 🔙 Назад к выбору задач")
    await callback.message.edit_text(
        "📋 Выберите задачу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧹 Удалить все каналы", callback_data="task_delete_channels_del")],
            [InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="menu_main")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "delete_log_message")
@admin_only
async def delete_log_message(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        print(f"[ERROR] Не удалось удалить сообщение с логом: {e}")

@router.callback_query(F.data.startswith("delch_group_pick:"))
@admin_only
async def delch_pick_group(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    group_id = int(callback.data.split(":")[1])

    accounts = get_all_accounts()
    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await callback.answer("В этой группе нет аккаунтов")
        return

    # перезаписываем выбор
    selected_accounts_del[user_id] = list(ids_in_group)

    page = int(selected_page_del.get(user_id, 0))
    groups = get_account_groups_with_count()
    await safe_edit_markup(
        callback.message,
        delch_accounts_keyboard(accounts, ids_in_group, page=page, groups=groups)
    )
    await callback.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")
