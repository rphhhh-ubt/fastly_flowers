from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from app.db import get_connection
from aiogram.exceptions import TelegramBadRequest

router = Router()

def get_task_card_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_check_groups_task_{task_id}")],
        [InlineKeyboardButton(text="📄 ЛОГ", callback_data=f"download_check_groups_log_{task_id}")],
        [InlineKeyboardButton(text="💡 Создать еще одну задачу", callback_data="menu_tasks")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tasktype_check_groups")]
    ])

@router.callback_query(F.data.startswith("show_check_groups_task_"))
async def show_check_groups_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
    task = cur.fetchone()
    if not task:
        await callback.answer("❌ Задача не найдена", show_alert=True)
        return

    # -- tuple layout:
    # (id, account_id, type, payload, status, ..., created_at, ...)
    payload = task[3] if isinstance(task[3], dict) else None
    # Если payload вдруг строка (маловероятно, но иногда бывает):
    if payload is None and isinstance(task[3], str):
        import json
        payload = json.loads(task[3])
    min_members = payload.get('min_members', 0) if payload else 0
    total_groups = len(payload.get('links', [])) if payload else 0

    created_at = task[6]
    status = task[4]

    # Общая статистика
    cur.execute("""
        SELECT
            COUNT(*) AS total_checked,
            SUM(CASE WHEN result = 'ok' THEN 1 ELSE 0 END) AS passed_filter,
            SUM(CASE WHEN result = 'small' THEN 1 ELSE 0 END) AS less_than_filter,
            SUM(CASE WHEN result = 'bad' THEN 1 ELSE 0 END) AS errors
        FROM check_groups_log
        WHERE task_id = %s;
    """, (task_id,))
    stats = cur.fetchone()
    X, Z, B, T = stats[0] or 0, stats[1] or 0, stats[2] or 0, stats[3] or 0

    cur.execute("SELECT DISTINCT account_id, account_username FROM check_groups_log WHERE task_id=%s", (task_id,))
    accounts_list = cur.fetchall()

    cur.close()
    conn.close()
    
    
    # --- Красивые статусы для пользователя ---
    status_map = {
        "pending": "⏳ В процессе",
        "done": "✅ Завершена",
        "completed": "✅ Завершена",
        "error": "❌ Ошибка",
        # добавь другие статусы по необходимости
    }
    status_nice = status_map.get(status, status)

    # --- Авто-завершение по количеству проверенных групп ---
    if status == "pending" and X == total_groups and total_groups > 0:
        status_nice = "✅ Завершена"

    msg = f"""
<b>Задача #{task_id} — Проверка групп</b>
Старт задачи: <code>{created_at}</code>
Статус: <b>{status_nice}</b>
Аккаунтов: <b>{len(accounts_list)}</b>

Всего групп в задаче: <b>{total_groups}</b>
Проверено на данный момент: <b>{X}</b>

👥Сколько минимум подписчиков должно быть: <b>{min_members}</b>
💎Подходящие группы: <b>{Z}</b>
🗑Меньше чем нужно: <b>{B}</b>
⛔️Группы с ошибками: <b>{T}</b>
    """.strip()

    await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=get_task_card_keyboard(task_id))
    await callback.answer()



@router.callback_query(F.data.startswith("refresh_check_groups_task_"))
async def refresh_check_groups_task(callback: types.CallbackQuery):
    try:
        await show_check_groups_task(callback)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Данные актуальны. Изменений нет.", show_alert=False)
        else:
            raise



@router.callback_query(F.data.startswith("download_check_groups_log_"))
async def download_check_groups_log(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[-1])
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT payload FROM tasks WHERE id=%s", (task_id,))
    task = cur.fetchone()
    payload = task[0]
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    min_members = payload.get('min_members', 0)

    # Получаем общую статистику
    cur.execute("""
        SELECT
            COUNT(*) AS total_checked,
            SUM(CASE WHEN result = 'ok' THEN 1 ELSE 0 END) AS passed_filter,
            SUM(CASE WHEN result = 'small' THEN 1 ELSE 0 END) AS less_than_filter,
            SUM(CASE WHEN result = 'bad' THEN 1 ELSE 0 END) AS errors
        FROM check_groups_log
        WHERE task_id = %s;
    """, (task_id,))
    stats = cur.fetchone()
    X, Z, B, T = stats[0] or 0, stats[1] or 0, stats[2] or 0, stats[3] or 0

    # Собираем все ссылки по категориям (сначала общий блок)
    passed_links = []
    small_links = []
    error_links = []

    cur.execute("""
        SELECT checked_group, result
        FROM check_groups_log
        WHERE task_id = %s
        ORDER BY checked_at;
    """, (task_id,))
    for checked_group, result in cur.fetchall():
        if result == "ok":
            passed_links.append(checked_group)
        elif result == "small":
            small_links.append(checked_group)
        elif result == "bad":
            error_links.append(checked_group)

    # Формируем лог: сначала три блока, потом аккаунты
    log_lines = [
        f"🗂 Всего проверено групп: {X}",
        f"🔍 Фильтр: {min_members}",
        f"✅ Подходят под фильтр: {Z}",
    ]
    log_lines += passed_links if passed_links else ["—"]

    log_lines += [
        "",
        f"🪧 Меньше фильтра: {B}",
    ]
    log_lines += small_links if small_links else ["—"]

    log_lines += [
        "",
        f"❌ Группы с ошибками: {T}",
    ]
    log_lines += error_links if error_links else ["—"]
    log_lines.append("")

    # Теперь блок по аккаунтам (как было)
    cur.execute("""
        SELECT account_id, account_username
        FROM check_groups_log
        WHERE task_id = %s
        GROUP BY account_id, account_username
        ORDER BY account_id;
    """, (task_id,))
    accounts = cur.fetchall()

    for acc_id, acc_username in accounts:
        cur.execute("""
            SELECT checked_group, result, members, error_message
            FROM check_groups_log
            WHERE task_id = %s AND account_id = %s
            ORDER BY checked_at;
        """, (task_id, acc_id))
        groups = cur.fetchall()

        log_lines.append(f"👤Аккаунт {acc_id} {acc_username}")
        log_lines.append("📝проверены группы:")
        for checked_group, result, members, error in groups:
            if result == "ok":
                line = f"{checked_group} — {members}"
            elif result == "small":
                line = f"{checked_group} — {members} (меньше фильтра)"
            elif result == "bad":
                line = f"{checked_group} — ошибка: {error or ''}"
            else:
                line = f"{checked_group} — {result or ''} {error or ''}"
            log_lines.append(line)
        log_lines.append(f"Всего проверено групп: {len(groups)}")
        log_lines.append("_" * 40)

    cur.close()
    conn.close()

    file_text = "\n".join(log_lines)
    await callback.message.answer_document(
        BufferedInputFile(file_text.encode("utf-8"), filename=f"check_groups_log_{task_id}.txt"),
        caption="🗂 Лог задачи",
        reply_markup=ok_to_delete_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "tasktype_check_groups")
async def show_check_groups_tasks_list(callback: types.CallbackQuery):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, created_at FROM tasks WHERE type='check_groups' ORDER BY created_at DESC LIMIT 10"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    keyboard = []
    for task_id, created_at in rows:
        keyboard.append([
            types.InlineKeyboardButton(
                text=f"Задача #{task_id} от {created_at:%d.%m %H:%M}",
                callback_data=f"show_check_groups_task_{task_id}"
            )
        ])
    keyboard.append([
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")
    ])
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    await callback.message.edit_text("Выбери задачу для просмотра:", reply_markup=markup)
    await callback.answer()

def ok_to_delete_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ OK (Удалить файл)", callback_data="groupcheck_delete_file_msg")]
        ]
    )

@router.callback_query(F.data == "groupcheck_delete_file_msg")
async def groupcheck_delete_file_msg(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("✅ Сообщение удалено!", show_alert=False)
