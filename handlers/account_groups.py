from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from keyboards.account_groups import grantes_menu_keyboard
from app.db import create_account_group, get_account_groups, get_account_groups_with_count, get_connection, delete_group_by_id, get_all_accounts

router = Router()

STICKY_KEY_CHAT = "sticky_chat_id"
STICKY_KEY_MSG  = "sticky_msg_id"

# --- FSM для создания группы ---
class GroupDialog(StatesGroup):
    waiting_for_group_name = State()

class AddToGroupDialog(StatesGroup):
    selecting_accounts = State()

class RemoveFromGroupDialog(StatesGroup):
    selecting_accounts = State()

class RenameGroupDialog(StatesGroup):
    waiting_for_name = State()

def get_unassigned_accounts():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, username, label, group_id
            FROM accounts
            WHERE group_id IS NULL
            ORDER BY id
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_group_accounts(group_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, username, label, group_id
            FROM accounts
            WHERE group_id = %s
            ORDER BY id
        """, (group_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

async def _sticky_set_from_message(state: FSMContext, message: types.Message):
    # Сохраняем chat_id и id бот-сообщения, которое будем редактировать
    await state.update_data(**{
        STICKY_KEY_CHAT: message.chat.id,
        STICKY_KEY_MSG: message.message_id,
    })

async def _sticky_edit(state: FSMContext, bot: Bot, text: str, reply_markup: types.InlineKeyboardMarkup | None = None, parse_mode: str | None = "HTML"):
    data = await state.get_data()
    chat_id = data.get(STICKY_KEY_CHAT)
    msg_id  = data.get(STICKY_KEY_MSG)
    if chat_id and msg_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        # Фоллбек: если по какой-то причине нет сохранённых id — ничего не ломаем
        # (можно отправить новое сообщение, но стараемся всегда иметь sticky)
        pass


# --- Главное меню ---
@router.callback_query(F.data == "grantes_menu")
async def accountgroups_menu(callback: types.CallbackQuery, state: FSMContext):
    print("[DEBUG] Получен callback_data:", callback.data)
    # текущее callback.message — это и есть «липкое» бот-сообщение
    await _sticky_set_from_message(state, callback.message)
    await callback.message.edit_text(
        "Меню групп аккаунтов:",
        reply_markup=grantes_menu_keyboard(prefix="accountgroups_")
    )
    await callback.answer()


# --- Создание группы ---
@router.callback_query(F.data == "grantes_create")
async def accountgroups_create(callback: types.CallbackQuery, state: FSMContext):
    print("[DEBUG] Получен callback_data:", callback.data)
    # убеждаемся, что sticky привязан (на случай входа «в обход»)
    await _sticky_set_from_message(state, callback.message)

    await state.set_state(GroupDialog.waiting_for_group_name)
    await callback.message.edit_text(
        "Пришли название и эмодзи группы (например: 😜 Группа 1)",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_menu")]]
        )
    )
    await callback.answer()


@router.message(GroupDialog.waiting_for_group_name)
async def accountgroups_save_group_name(message: types.Message, state: FSMContext):
    # удаляем пользовательский ввод — чтобы не плодить «переписку»
    try:
        await message.delete()
    except Exception:
        pass  # не критично

    group_input = (message.text or "").strip()
    if " " in group_input:
        emoji, name = group_input.split(" ", 1)
    else:
        emoji, name = "", group_input

    group_id = create_account_group(name=name, emoji=emoji)

    # редактируем sticky-сообщение и сразу показываем меню групп
    kb = grantes_menu_keyboard(prefix="accountgroups_")
    await _sticky_edit(
        state,
        message.bot,
        text=f"✅ Группа <b>{emoji} {name}</b> создана! (id: {group_id})\n\nМеню групп аккаунтов:",
        reply_markup=kb
    )
    await state.clear()


# --- Редактирование группы ---
# --- Экран группы (после выбора группы из grantes_edit) ---
@router.callback_query(F.data.regexp(r"^grantes_edit_\d+$"))
async def grantes_group_menu(callback: types.CallbackQuery):
    parts = callback.data.split("_")  # ["grantes","edit","{group_id}"]
    group_id = int(parts[2])

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data=f"grantes_group_add_{group_id}")],
        [types.InlineKeyboardButton(text="➖ Удалить аккаунты",  callback_data=f"grantes_group_rm_{group_id}")],
        [types.InlineKeyboardButton(text="✏️ Переименовать",    callback_data=f"grantes_group_rename_{group_id}")],
        [types.InlineKeyboardButton(text="⬅️ Назад к группам",  callback_data="grantes_edit")]
    ])
    await callback.message.edit_text(f"Группа ID <b>{group_id}</b> — выбери действие:", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# Шаг 1: выбор группы (ровно grantes_add_{group_id})
@router.callback_query(F.data.regexp(r"^grantes_group_add_\d+$"))
async def grantes_add_select_group(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])  # grantes_group_add_{group_id}
    await state.update_data(target_group_id=group_id, selected_account_ids=set())
    await state.set_state(AddToGroupDialog.selecting_accounts)
    await _render_accounts_multiselect_add(callback.message, state)
    await callback.answer()

@router.callback_query(F.data.regexp(r"^grantes_add_toggle_\d+_\d+$"), AddToGroupDialog.selecting_accounts)
async def grantes_add_toggle_account(callback: types.CallbackQuery, state: FSMContext):
    _, _, _, group_id_s, acc_id_s = callback.data.split("_")
    group_id = int(group_id_s); acc_id = int(acc_id_s)

    data = await state.get_data()
    if data.get("target_group_id") != group_id:
        await callback.answer("Сеанс выбора устарел. Начни заново.", show_alert=True); return

    selected: set = set(data.get("selected_account_ids", set()))
    selected.symmetric_difference_update({acc_id})  # toggle
    await state.update_data(selected_account_ids=selected)
    await _render_accounts_multiselect_add(callback.message, state)
    await callback.answer()

@router.callback_query(F.data.regexp(r"^grantes_add_apply_\d+$"), AddToGroupDialog.selecting_accounts)
async def grantes_add_apply(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    if data.get("target_group_id") != group_id:
        await callback.answer("Сеанс выбора устарел. Начни заново.", show_alert=True); return

    selected: set = set(data.get("selected_account_ids", set()))
    if not selected:
        await callback.answer("Не выбрано ни одного аккаунта.", show_alert=True); return

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE accounts SET group_id = %s WHERE id = ANY(%s)", (group_id, list(selected)))
        conn.commit()
    finally:
        cur.close(); conn.close()

    await state.clear()
    await callback.message.edit_text(
        f"✅ Добавлено в группу {group_id}: {len(selected)}",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
        )
    )
    await callback.answer("Готово!")

@router.callback_query(F.data.regexp(r"^grantes_add_cancel_\d+$"), AddToGroupDialog.selecting_accounts)
async def grantes_add_cancel(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
    ))
    await callback.answer()

async def _render_accounts_multiselect_add(message: types.Message, state: FSMContext):
    data = await state.get_data()
    group_id = data["target_group_id"]
    selected: set = set(data.get("selected_account_ids", set()))

    accounts = get_unassigned_accounts()
    if not accounts:
        await message.edit_text(
            "Нет аккаунтов без группы.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
            )
        )
        return

    rows = []
    for acc in accounts:
        acc_id = acc["id"]
        username = (acc.get("username") or "").strip()
        label = (acc.get("label") or "").strip()
        display = f"@{username}" if username and not username.startswith("@") else (username or label or f"acc#{acc_id}")
        mark = "✅" if acc_id in selected else "➕"
        rows.append([types.InlineKeyboardButton(
            text=f"{mark} {display} [id:{acc_id}]",
            callback_data=f"grantes_add_toggle_{group_id}_{acc_id}"
        )])

    rows += [
        [types.InlineKeyboardButton(text="✅ Применить", callback_data=f"grantes_add_apply_{group_id}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grantes_edit_{group_id}"),
         types.InlineKeyboardButton(text="Отмена", callback_data=f"grantes_add_cancel_{group_id}")]
    ]

    await message.edit_text(
        f"Группа ID <b>{group_id}</b>\nВыбери аккаунты для <b>добавления</b> (видны только без группы):",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _render_accounts_multiselect(message: types.Message, state: FSMContext):
    """
    Рисуем список аккаунтов БЕЗ группы (group_id IS NULL) с чекбоксами.
    """
    data = await state.get_data()
    group_id = data["target_group_id"]
    selected: set = set(data.get("selected_account_ids", set()))

    accounts = get_unassigned_accounts()  # <-- только без группы
    if not accounts:
        await message.edit_text(
            "Нет аккаунтов без группы.\n"
            "Добавить можно только те, у кого не указана группа.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_edit")]]
            )
        )
        return

    rows = []
    for acc in accounts:
        acc_id = acc["id"]
        username = (acc.get("username") or "").strip()
        label = (acc.get("label") or "").strip()

        if username:
            display = f"@{username}" if not username.startswith("@") else username
        elif label:
            display = label
        else:
            display = f"acc#{acc_id}"

        mark = "✅" if acc_id in selected else "➕"
        btn_text = f"{mark} {display} [id:{acc_id}]"

        rows.append([
            types.InlineKeyboardButton(
                text=btn_text,
                callback_data=f"grantes_add_toggle_{group_id}_{acc_id}"
            )
        ])

    rows.append([
        types.InlineKeyboardButton(text="✅ Применить", callback_data=f"grantes_add_apply_{group_id}")
    ])
    rows.append([
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_edit"),
        types.InlineKeyboardButton(text="Отмена", callback_data=f"grantes_add_cancel_{group_id}")
    ])

    await message.edit_text(
        f"Группа ID <b>{group_id}</b>\nВыбери аккаунты для добавления (показаны только без группы):",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows)
    )


# --- Удаление группы ---
@router.callback_query(F.data.regexp(r"^grantes_group_rm_\d+$"))
async def grantes_rm_select_group(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])  # grantes_group_rm_{group_id}
    await state.update_data(target_group_id=group_id, selected_account_ids=set())
    await state.set_state(RemoveFromGroupDialog.selecting_accounts)
    await _render_accounts_multiselect_remove(callback.message, state)
    await callback.answer()

@router.callback_query(F.data.regexp(r"^grantes_rm_toggle_\d+_\d+$"), RemoveFromGroupDialog.selecting_accounts)
async def grantes_rm_toggle_account(callback: types.CallbackQuery, state: FSMContext):
    _, _, _, group_id_s, acc_id_s = callback.data.split("_")
    group_id = int(group_id_s); acc_id = int(acc_id_s)

    data = await state.get_data()
    if data.get("target_group_id") != group_id:
        await callback.answer("Сеанс выбора устарел. Начни заново.", show_alert=True); return

    selected: set = set(data.get("selected_account_ids", set()))
    selected.symmetric_difference_update({acc_id})
    await state.update_data(selected_account_ids=selected)
    await _render_accounts_multiselect_remove(callback.message, state)
    await callback.answer()

@router.callback_query(F.data.regexp(r"^grantes_rm_apply_\d+$"), RemoveFromGroupDialog.selecting_accounts)
async def grantes_rm_apply(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    if data.get("target_group_id") != group_id:
        await callback.answer("Сеанс выбора устарел. Начни заново.", show_alert=True); return

    selected: set = set(data.get("selected_account_ids", set()))
    if not selected:
        await callback.answer("Не выбрано ни одного аккаунта.", show_alert=True); return

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE accounts SET group_id = NULL WHERE id = ANY(%s) AND group_id = %s", (list(selected), group_id))
        conn.commit()
    finally:
        cur.close(); conn.close()

    await state.clear()
    await callback.message.edit_text(
        f"✅ Удалено из группы {group_id}: {len(selected)}",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
        )
    )
    await callback.answer("Готово!")

@router.callback_query(F.data.regexp(r"^grantes_rm_cancel_\d+$"), RemoveFromGroupDialog.selecting_accounts)
async def grantes_rm_cancel(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
    ))
    await callback.answer()

async def _render_accounts_multiselect_remove(message: types.Message, state: FSMContext):
    data = await state.get_data()
    group_id = data["target_group_id"]
    selected: set = set(data.get("selected_account_ids", set()))

    accounts = get_group_accounts(group_id)
    if not accounts:
        await message.edit_text(
            "В группе пока нет аккаунтов.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
            )
        )
        return

    rows = []
    for acc in accounts:
        acc_id = acc["id"]
        username = (acc.get("username") or "").strip()
        label = (acc.get("label") or "").strip()
        display = f"@{username}" if username and not username.startswith("@") else (username or label or f"acc#{acc_id}")
        mark = "✅" if acc_id in selected else "➖"
        rows.append([types.InlineKeyboardButton(
            text=f"{mark} {display} [id:{acc_id}]",
            callback_data=f"grantes_rm_toggle_{group_id}_{acc_id}"
        )])

    rows += [
        [types.InlineKeyboardButton(text="✅ Применить", callback_data=f"grantes_rm_apply_{group_id}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grantes_edit_{group_id}"),
         types.InlineKeyboardButton(text="Отмена", callback_data=f"grantes_rm_cancel_{group_id}")]
    ]

    await message.edit_text(
        f"Группа ID <b>{group_id}</b>\nВыбери аккаунты для <b>удаления</b> из группы:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows)
    )

# Список групп для редактирования (первый экран после "Редактировать группы")
@router.callback_query(F.data.in_({"grantes_edit", "accountgroups_edit"}))
async def grantes_edit_menu(callback: types.CallbackQuery, state: FSMContext):
    await _sticky_set_from_message(state, callback.message)  # фиксируем sticky, если пришли не из главного меню
    groups = get_account_groups()
    if not groups:
        await callback.answer("Нет групп для редактирования.", show_alert=True); return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{g['emoji']} {g['name']}", callback_data=f"grantes_edit_{g['id']}")]
        for g in groups
    ] + [[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_menu")]])

    await callback.message.edit_text("Выбери группу:", reply_markup=kb)
    await callback.answer()



@router.callback_query(F.data.regexp(r"^grantes_group_rename_\d+$"))
async def grantes_group_rename_start(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[3])  # grantes_group_rename_{group_id}
    await state.update_data(rename_group_id=group_id)
    await state.set_state(RenameGroupDialog.waiting_for_name)
    await callback.message.edit_text(
        f"✏️ Введите новое название группы (можно с эмодзи в начале, как при создании).",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к группе", callback_data=f"grantes_edit_{group_id}")]]
        )
    )
    await callback.answer()

@router.message(RenameGroupDialog.waiting_for_name)
async def grantes_group_rename_apply(message: types.Message, state: FSMContext):
    # чистим пользовательское сообщение
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    group_id = int(data["rename_group_id"])
    group_input = (message.text or "").strip()

    emoji, name = ("", group_input)
    if " " in group_input:
        emoji, name = group_input.split(" ", 1)

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE account_groups SET name = %s, emoji = %s WHERE id = %s", (name, emoji, group_id))
        conn.commit()
    finally:
        cur.close(); conn.close()

    await state.clear()

    # возвращаемся на экран группы тем же sticky-сообщением
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data=f"grantes_group_add_{group_id}")],
        [types.InlineKeyboardButton(text="➖ Удалить аккаунты",  callback_data=f"grantes_group_rm_{group_id}")],
        [types.InlineKeyboardButton(text="✏️ Переименовать",    callback_data=f"grantes_group_rename_{group_id}")],
        [types.InlineKeyboardButton(text="⬅️ Назад к группам",  callback_data="grantes_edit")]
    ])
    await _sticky_edit(
        state,
        message.bot,
        text=f"✅ Группа переименована: <b>{emoji} {name}</b>\n\nГруппа ID <b>{group_id}</b> — выбери действие:",
        reply_markup=kb
    )



# --- Список групп ---
@router.callback_query(F.data == "grantes_list")
async def accountgroups_list(callback: types.CallbackQuery):
    print("[DEBUG] Получен callback_data:", callback.data)
    groups = get_account_groups_with_count()
    if not groups:
        await callback.message.edit_text("Группы не найдены.")
        return
    text = "<b>Список групп:</b>\n"
    for g in groups:
        text += f"{g['emoji']} <b>{g['name']}</b> — <b>{g['count']}</b> аккаунтов\n"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_menu")]]
    ))
    await callback.answer()
    
# --- Удаление группы: список групп ---
@router.callback_query(F.data.in_({"grantes_delete", "accountgroups_delete"}))
async def grantes_delete_menu(callback: types.CallbackQuery):
    groups = get_account_groups()
    if not groups:
        await callback.answer("Нет групп для удаления.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text=f"{g['emoji']} {g['name']}",
            callback_data=f"grantes_delete_{g['id']}"
        )] for g in groups
    ] + [[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="grantes_menu")]])

    await callback.message.edit_text("Выбери группу для удаления:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.regexp(r"^grantes_delete_\d+$"))
async def grantes_delete_action(callback: types.CallbackQuery):
    group_id = int(callback.data.split("_")[2])

    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1) освобождаем аккаунты
        cur.execute("UPDATE accounts SET group_id = NULL WHERE group_id = %s", (group_id,))
        # 2) удаляем группу тем же курсором/в той же транзакции
        cur.execute("DELETE FROM account_groups WHERE id = %s", (group_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    await callback.message.edit_text(
        "✅ Группа удалена.",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ В меню групп", callback_data="grantes_menu")]]
        )
    )
    await callback.answer("Готово!")
