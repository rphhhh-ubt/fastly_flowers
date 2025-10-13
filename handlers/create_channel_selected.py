from aiogram import Router, types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, FSInputFile
from utils.check_access import admin_only
from app.db import get_all_accounts, create_task_entry, insert_task_create_log
from keyboards.create_channel_keyboards import build_create_channel_keyboard
from aiogram.fsm.context import FSMContext
from handlers.channel_creation import create_channels_process  # Добавьте в начало файла
from datetime import datetime
import asyncio, os
from io import StringIO
from contextlib import redirect_stdout
router = Router()
# Удаляем отдельный словарь и используем глобальный selected_accounts_create из channel_creation
from handlers.channel_creation import selected_accounts_create
# == НОВЫЕ ИМПОРТЫ ==
from aiogram.exceptions import TelegramBadRequest
from app.db import get_all_accounts, get_account_groups_with_count
from keyboards.create_channel_accounts_keyboard import create_channel_accounts_keyboard


# == ЛОКАЛЬНЫЕ КОНСТАНТЫ ДЛЯ СОСТОЯНИЯ ВЫБОРА ==
STATE_ACCS = "crch_accounts"
STATE_SEL  = "crch_selected"
STATE_PAGE = "crch_page"
PER_PAGE   = 10

# == ХЕЛПЕР БЕЗОПАСНОЙ ПЕРЕРИСОВКИ ==
async def safe_edit_markup(msg: types.Message, kb):
    try:
        await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise




@router.callback_query(F.data == "task_create_channels")
@admin_only
async def crch_start(callback: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    groups   = get_account_groups_with_count()

    # очистим старый выбор (если вдруг был)
    await state.update_data(**{STATE_ACCS: accounts, STATE_SEL: set(), STATE_PAGE: 0})

    kb = create_channel_accounts_keyboard(
        accounts, selected=set(), page=0, per_page=PER_PAGE, groups=groups
    )
    await callback.message.edit_text(
        "📡 Шаг 1: выберите аккаунты для создания каналов.",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("create_channel_toggle_"))
@admin_only
async def toggle_account_create_channel(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    current = selected_accounts_create.get(user_id, [])
    if acc_id in current:
        current.remove(acc_id)
    else:
        current.append(acc_id)
    selected_accounts_create[user_id] = current
    print(f"[DEBUG] 🔄 Текущий выбор после нажатия: {selected_accounts_create}")
    accounts = get_all_accounts()
    await callback.message.edit_text(
        "📡 Выберите аккаунты для создания и установки канала:",
        reply_markup=build_create_channel_keyboard(accounts, current),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("crch_toggle:"))
async def crch_toggle(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    selected = list(data.get(STATE_SEL, []))  # список

    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.append(acc_id)

    await state.update_data(**{STATE_SEL: selected})
    kb = create_channel_accounts_keyboard(
        accounts, set(selected),  # тут можно в set() только для отрисовки галочек
        page=int(data.get(STATE_PAGE, 0)),
        per_page=PER_PAGE,
        groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("crch_page:"))
@admin_only
async def crch_page(callback: types.CallbackQuery, state: FSMContext):
    new_page = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    selected = set(data.get(STATE_SEL, set()))
    await state.update_data(**{STATE_PAGE: new_page})

    kb = create_channel_accounts_keyboard(
        accounts, selected, page=new_page, per_page=PER_PAGE, groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer()

@router.callback_query(F.data == "crch_select_all")
@admin_only
async def crch_select_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    selected = {a["id"] for a in accounts}
    await state.update_data(**{STATE_SEL: selected})

    page = int(data.get(STATE_PAGE, 0))
    kb = create_channel_accounts_keyboard(
        accounts, selected, page=page, per_page=PER_PAGE, groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer("✅ Выбраны все аккаунты")

@router.callback_query(F.data == "crch_clear_all")
@admin_only
async def crch_clear_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    await state.update_data(**{STATE_SEL: set()})

    page = int(data.get(STATE_PAGE, 0))
    kb = create_channel_accounts_keyboard(
        accounts, set(), page=page, per_page=PER_PAGE, groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer("♻️ Сброшен выбор")

# == ЧИПС ГРУППЫ (выбираем ровно эту группу) ==
@router.callback_query(F.data.startswith("crch_group:"))
@admin_only
async def crch_group_pick(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    page     = int(data.get(STATE_PAGE, 0))

    ids_in_group = [a["id"] for a in accounts if a.get("group_id") == group_id]
    if not ids_in_group:
        await callback.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(**{STATE_SEL: ids_in_group})

    kb = create_channel_accounts_keyboard(
        accounts, set(ids_in_group),
        page=page, per_page=PER_PAGE, groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")


# == ДАЛЕЕ: пробросим выбор в твою существующую логику ==
from handlers.channel_creation import selected_accounts_create  # как и было у тебя



@router.callback_query(F.data == "create_channel_select_all")
@admin_only
async def select_all_accounts_create_channel(callback: types.CallbackQuery):
    print("[DEBUG] 🟢 Начинаю 'Выбрать все'")
    accounts = get_all_accounts()
    print(f"[DEBUG] 📥 Получены аккаунты: {accounts}")
    selected_ids = [acc["id"] for acc in accounts]
    selected_accounts_create[callback.from_user.id] = selected_ids
    print(f"[DEBUG] ✅ Все аккаунты выбраны: {selected_ids}")
    await callback.message.edit_text(
        "📡 Все аккаунты выбраны.\nНажмите «Далее».",
        reply_markup=build_create_channel_keyboard(accounts, selected_ids),
        parse_mode="HTML"
    )
    await callback.answer()

from handlers.channel_creation import ChannelCreation, selected_accounts_create
from keyboards.cancel_keyboard import cancel_keyboard

@router.callback_query(F.data == "proceed_create_channel")
@admin_only
async def crch_proceed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = list(data.get(STATE_SEL, set()))
    if not selected_ids:
        await callback.answer("⚠️ Ни один аккаунт не выбран!", show_alert=True)
        return

    # проброс для совместимости со сценарием channel_creation
    user_id = callback.from_user.id
    selected_accounts_create[user_id] = selected_ids

    # запускаем сценарий создания каналов (как в channel_creation)
    await state.clear()
    await state.set_state(ChannelCreation.waiting_for_titles)

    sent = await callback.message.answer(
        "📥 Пришлите файл или текст с названиями каналов (по одному в строке):",
        reply_markup=cancel_keyboard()
    )
    await state.update_data(
        bot_message_id=sent.message_id,
        selected_account_ids=selected_ids  # channel_creation читает это поле
    )

    # можно удалить предыдущую клавиатуру, чтобы не путать пользователя
    try:
        await callback.message.delete()
    except: 
        pass

    await callback.answer("✅ Аккаунты выбраны. Начинаем настройку…")

from handlers.channel_creation import ChannelCreation, selected_accounts_create
from keyboards.cancel_keyboard import cancel_keyboard

@router.callback_query(F.data == "crch_next")   # <— НОВЫЙ callback
@admin_only
async def crch_proceed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = list(data.get(STATE_SEL, []))
    print("[DEBUG] crch_next selected_ids =", selected_ids)  # временный лог

    if not selected_ids:
        await callback.answer("⚠️ Ни один аккаунт не выбран!", show_alert=True)
        return

    # пробрасываем в старый сценарий (он этого ждёт)
    selected_accounts_create[callback.from_user.id] = selected_ids

    await state.clear()
    await state.set_state(ChannelCreation.waiting_for_titles)
    sent = await callback.message.answer(
        "📥 Пришлите файл или текст с названиями каналов (по одному в строке):",
        reply_markup=cancel_keyboard()
    )
    await state.update_data(
        bot_message_id=sent.message_id,
        selected_account_ids=selected_ids
    )
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("✅ Аккаунты выбраны. Начинаем настройку…")
