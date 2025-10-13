# handlers/bulk_profile_update_task.py

import os, zipfile, uuid, datetime, pytz, asyncio, json
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from states.bulk_profile_update_states import BulkProfileUpdateFSM
from utils.check_access import admin_only
from app.db import get_all_accounts, get_account_by_id, get_connection
from aiogram.types import FSInputFile
from app.telegram_client import get_client
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from app.memory_storage import bulk_profile_tasks_storage
from random import choice
from telethon.errors import UsernameOccupiedError, UsernameInvalidError
from PIL import Image
from telethon.tl.types import InputFile
from telethon.tl.functions.photos import GetUserPhotosRequest, DeletePhotosRequest
from telethon.tl.types import InputPhoto
from keyboards.main_menu import start_menu_keyboard as main_menu_keyboard
from typing import List, Dict, Any, Iterable, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest  # у тебя используется в try/except
from app.db import get_account_groups_with_count   # чтобы подгружать группы



from keyboards.bulk_profile_update_keyboards import (
    skip_firstname_keyboard,
    skip_lastname_keyboard,
    skip_bio_keyboard,
    run_now_keyboard,
    confirm_task_keyboard,
    ok_to_delete_keyboard,
    skip_avatar_keyboard,
    skip_username_keyboard,
)      

router = Router()




STATE_KEYS = {
    "ACCOUNTS": "bulk_all_accounts",
    "SELECTED": "bulk_selected_ids",
    "GROUP": "bulk_active_group",
    "PAGE": "bulk_page",
}

STATE_ACCOUNTS = "bulk_all_accounts"
STATE_SELECTED = "bulk_selected_ids"
STATE_PAGE     = "bulk_page"
PER_PAGE = 10  # синхронно с твоим bulk_accounts_keyboard


async def _get_bulk_state(state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_KEYS["ACCOUNTS"], [])
    selected = set(data.get(STATE_KEYS["SELECTED"], set()))
    active_group = data.get(STATE_KEYS["GROUP"], "all")
    page = int(data.get(STATE_KEYS["PAGE"], 0))
    return accounts, selected, active_group, page

async def _set_bulk_state(state: FSMContext, **kwargs):
    await state.update_data(**kwargs)

def _group_ids(accounts: List[Dict[str, Any]], group_id: int) -> set[int]:
    return {a["id"] for a in accounts if a.get("group_id") == group_id}



async def safe_edit_markup(message: types.Message, reply_markup: InlineKeyboardMarkup):
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def safe_edit_text(message: types.Message, text: str, reply_markup: InlineKeyboardMarkup, parse_mode: str | None = None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def bulk_accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected: Iterable[int] | None,
    page: int = 0,
    per_page: int = 10,
    groups: Optional[List[Dict[str, Any]]] = None,  # [{'id','name','emoji','count'}, ...]
) -> InlineKeyboardMarkup:
    selected = set(selected or [])

    total = len(accounts)
    start = page * per_page
    chunk = accounts[start:start + per_page]

    rows: List[List[InlineKeyboardButton]] = []

    # список аккаунтов (текущая страница)
    for acc in chunk:
        acc_id = acc["id"]
        uname  = acc.get("username") or "-"
        if uname != "-" and not str(uname).startswith("@"):
            uname = f"@{uname}"
        phone  = acc.get("phone") or "-"
        mark   = "✅" if acc_id in selected else "⏹️"
        txt    = f"{mark} {acc_id} ▸ {uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"bulk_toggle:{acc_id}")])

    # навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"bulk_page:{page-1}"))
    if start + per_page < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"bulk_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп (внизу): быстрый выбор всех аккаунтов группы
    chips: List[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue  # показываем только группы с 1+
            name = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"bulk_group_pick:{g['id']}"))

    # по 3 чипса в ряд
    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия (глобально)
    rows.append([
        InlineKeyboardButton(text="✅ Выбрать все", callback_data="bulk_select_all"),
        InlineKeyboardButton(text="⏹️ Снять все",   callback_data="bulk_clear_all"),
    ])

    rows.append([
        InlineKeyboardButton(text="➡ Далее",  callback_data="bulk_next"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="menu_main"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)






# Старт процесса массового обновления профиля
@router.callback_query(F.data == "start_bulk_profile_update")
@admin_only
async def start_bulk_update(callback: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    if not accounts:
        await callback.message.edit_text("⚠️ Нет доступных аккаунтов.")
        await callback.answer()
        return

    groups = get_account_groups_with_count()

    await state.set_state(BulkProfileUpdateFSM.selecting_accounts)
    await state.update_data(
        accounts=accounts,
        selected_accounts=[],
        page=0,
    )

    await callback.message.edit_text(
        "🔄 <b>Шаг 1:</b> Выберите аккаунты для обновления профиля.\n\n"
        "Вы можете выбрать вручную или нажать «✅ Выбрать все».\n"
        "Также можно быстро добавить всех из выбранной группы (кнопки ниже списка).\n"
        "Когда выберете аккаунты — нажмите «➡ Далее».",
        reply_markup=bulk_accounts_keyboard(accounts, selected=[], page=0, groups=groups),
        parse_mode="HTML"
    )
    await callback.answer()



@router.callback_query(F.data.startswith("bulk_toggle:"), BulkProfileUpdateFSM.selecting_accounts)
@admin_only
async def bulk_toggle_account(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    page = int(data.get("page", 0))

    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)
    await state.update_data(selected_accounts=list(selected))

    try:
        await callback.message.edit_reply_markup(
            reply_markup=bulk_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()

@router.callback_query(F.data.startswith("bulk_page:"), BulkProfileUpdateFSM.selecting_accounts)
@admin_only
async def bulk_page(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    await state.update_data(page=page)

    await callback.message.edit_reply_markup(
        reply_markup=bulk_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    )
    await callback.answer()

@router.callback_query(F.data == "bulk_select_all", BulkProfileUpdateFSM.selecting_accounts)
@admin_only
async def bulk_select_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    all_ids = [a["id"] for a in accounts]
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=all_ids)

    await callback.message.edit_reply_markup(
        reply_markup=bulk_accounts_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count())
    )
    await callback.answer("✅ Выбраны все")

@router.callback_query(F.data == "bulk_clear_all", BulkProfileUpdateFSM.selecting_accounts)
@admin_only
async def bulk_clear_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=[])

    await callback.message.edit_reply_markup(
        reply_markup=bulk_accounts_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count())
    )
    await callback.answer("♻️ Сброшен выбор")



# Обработчик нажатия "Далее" после выбора аккаунтов
@router.callback_query((F.data == "bulk_next") | (F.data == "proceed_after_selecting_accounts"))
@admin_only
async def proceed_after_selecting_accounts(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])

    if not selected_ids:
        await callback.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return

    await state.update_data(selected_accounts=selected_ids)
    await state.set_state(BulkProfileUpdateFSM.uploading_avatars)

    new_msg = await callback.message.edit_text(
        "🖼 <b>Шаг 2:</b> Загрузите ZIP архив с аватарками (.jpg).\n\n"
        "Допустимы только файлы JPG. Другие файлы будут проигнорированы.",
        reply_markup=skip_avatar_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)
    await callback.answer()


# Обработчик загрузки ZIP архива с аватарками
@router.message(BulkProfileUpdateFSM.uploading_avatars, F.document)
@admin_only
async def upload_avatars_zip(message: types.Message, state: FSMContext):
    document = message.document

    if not document.file_name.endswith(".zip"):
        await message.answer("⚠️ Пожалуйста, отправьте ZIP архив с аватарками (.jpg).")
        return
    
    # Сохраняем ID сообщения с архивом
    data = await state.get_data()
    messages_to_delete = data.get("messages_to_delete", [])
    messages_to_delete.append(message.message_id)
    await state.update_data(messages_to_delete=messages_to_delete)
    # ✅ Пытаемся сразу удалить сообщение
    try:
        await message.delete()
    except Exception as e:
        print(f"[WARN] Не удалось удалить ZIP-файл из чата: {e}")

    # Сохраняем файл временно
    temp_folder = f"/tmp/bulk_profile_update_{uuid.uuid4().hex}/"
    os.makedirs(temp_folder, exist_ok=True)

    file_path = temp_folder + document.file_name

    await message.bot.download(document, destination=file_path)

    # Распаковываем архив
    avatars_folder = temp_folder + "avatars/"
    os.makedirs(avatars_folder, exist_ok=True)

    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(avatars_folder)
    except Exception as e:
        await message.answer(f"❌ Ошибка при распаковке ZIP: {e}")
        return

    # Фильтруем только JPG файлы
    jpg_files = []
    for root, _, files in os.walk(avatars_folder):
        for file in files:
            if file.lower().endswith(".jpg"):
                jpg_files.append(os.path.join(root, file))

    if not jpg_files:
        await message.answer("❌ В архиве не найдено ни одного JPG файла!")
        return

    # Сохраняем пути к аватаркам в состоянии
    await state.update_data(avatars_folder=avatars_folder, avatars_list=jpg_files)
    # Удаляем старое меню
    data = await state.get_data()
    old_menu_id = data.get("current_menu_id")
    if old_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_menu_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить старое меню: {e}")


    # Переход к следующему шагу
    await state.set_state(BulkProfileUpdateFSM.uploading_usernames)

    new_msg = await message.answer(
        "✍️ <b>Шаг 3:</b> Теперь отправьте список username:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл",
        reply_markup=skip_username_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)

# Обработчик загрузки юзернеймов (текст или .txt файл)
@router.message(BulkProfileUpdateFSM.uploading_usernames)
@admin_only
async def upload_usernames(message: types.Message, state: FSMContext):
    usernames = []

    if message.document:
        # Пользователь отправил файл
        document = message.document
        if not document.file_name.endswith(".txt"):
            await message.answer("⚠️ Пожалуйста, отправьте TXT файл с юзернеймами или отправьте список в сообщении.")
            return
            
        # Сохраняем ID сообщения с архивом
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        messages_to_delete.append(message.message_id)
        await state.update_data(messages_to_delete=messages_to_delete)
        
        # ✅ Пытаемся сразу удалить
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить сообщение с username: {e}")

        temp_file = f"/tmp/{uuid.uuid4().hex}.txt"
        await message.bot.download(document, destination=temp_file)

        with open(temp_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            usernames = [line.strip() for line in lines if line.strip()]
        
        os.remove(temp_file)
    else:
        # Пользователь отправил просто текст
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить текстовое сообщение с username: {e}")
        
        lines = message.text.strip().splitlines()
        usernames = [line.strip() for line in lines if line.strip()]

    if not usernames:
        await message.answer("⚠️ Список юзернеймов пуст. Пожалуйста, попробуйте снова.")
        return

    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])

    if len(usernames) < len(selected_ids):
        await message.answer(
            f"❌ Недостаточно юзернеймов!\n\nВыбрано аккаунтов: {len(selected_ids)}\nОтправлено юзернеймов: {len(usernames)}\n\n"
            "Пожалуйста, отправьте достаточно юзернеймов, чтобы каждому аккаунту достался свой уникальный username.",
            parse_mode="HTML"
        )
        return

    # Сохраняем список юзернеймов в FSM
    await state.update_data(usernames_list=usernames)
    
    # Удаляем старое меню
    data = await state.get_data()
    old_menu_id = data.get("current_menu_id")
    if old_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_menu_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить старое меню: {e}")

    # Переход к следующему шагу
    await state.set_state(BulkProfileUpdateFSM.uploading_firstnames)

    new_msg = await message.answer(
        "👤 <b>Шаг 4:</b> Теперь отправьте список имён:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы пропустить обновление имён.",
        reply_markup=skip_firstname_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)
    
    
# Обработчик загрузки ИМЁН (текст или .txt файл)
@router.message(BulkProfileUpdateFSM.uploading_firstnames)
@admin_only
async def upload_firstnames(message: types.Message, state: FSMContext):
    firstnames = []

    if message.document:
        document = message.document
        if not document.file_name.endswith(".txt"):
            await message.answer("⚠️ Пожалуйста, отправьте TXT файл с именами или отправьте список в сообщении.")
            return
            
         # Сохраняем ID сообщения с архивом
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        messages_to_delete.append(message.message_id)
        await state.update_data(messages_to_delete=messages_to_delete)
        
        # ✅ Пытаемся сразу удалить
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить сообщение с firstname: {e}")

        temp_file = f"/tmp/{uuid.uuid4().hex}.txt"
        await message.bot.download(document, destination=temp_file)

        with open(temp_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            firstnames = [line.strip() for line in lines if line.strip()]
        
        os.remove(temp_file)
    else:
        # Пользователь отправил просто текст
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить текстовое сообщение с firstname: {e}")

        lines = message.text.strip().splitlines()
        firstnames = [line.strip() for line in lines if line.strip()]

    if not firstnames:
        await message.answer("⚠️ Список имён пуст. Пожалуйста, попробуйте снова или нажмите кнопку «Не обновлять Имя».")
        return

    # Сохраняем имена
    await state.update_data(firstnames_list=firstnames)
    
    # Удаляем старое меню
    data = await state.get_data()
    old_menu_id = data.get("current_menu_id")
    if old_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_menu_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить старое меню: {e}")

    # Переход к следующему шагу
    await state.set_state(BulkProfileUpdateFSM.uploading_lastnames)

    new_msg = await message.answer(
        "👤 <b>Шаг 5:</b> Теперь отправьте список фамилий:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы пропустить обновление фамилий.",
        reply_markup=skip_lastname_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)

# Обработчик загрузки ФАМИЛИЙ (текст или .txt файл)
@router.message(BulkProfileUpdateFSM.uploading_lastnames)
@admin_only
async def upload_lastnames(message: types.Message, state: FSMContext):
    lastnames = []

    if message.document:
        document = message.document
        if not document.file_name.endswith(".txt"):
            await message.answer("⚠️ Пожалуйста, отправьте TXT файл с фамилиями или отправьте список в сообщении.")
            return
            
         # Сохраняем ID сообщения с архивом
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        messages_to_delete.append(message.message_id)
        await state.update_data(messages_to_delete=messages_to_delete)
        
         # ✅ Пытаемся сразу удалить
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить сообщение с lastname: {e}")

        temp_file = f"/tmp/{uuid.uuid4().hex}.txt"
        await message.bot.download(document, destination=temp_file)

        with open(temp_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            lastnames = [line.strip() for line in lines if line.strip()]
        
        os.remove(temp_file)
    else:
        # Пользователь отправил просто текст
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить текстовое сообщение с lastname: {e}")
        lines = message.text.strip().splitlines()
        lastnames = [line.strip() for line in lines if line.strip()]

    if not lastnames:
        await message.answer("⚠️ Список фамилий пуст. Пожалуйста, попробуйте снова или нажмите кнопку «Не обновлять Фамилию».")
        return

    # Сохраняем фамилии
    await state.update_data(lastnames_list=lastnames)
    
    # Удаляем старое меню
    data = await state.get_data()
    old_menu_id = data.get("current_menu_id")
    if old_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_menu_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить старое меню: {e}")

    # Переход к следующему шагу
    await state.set_state(BulkProfileUpdateFSM.uploading_bios)

    new_msg = await message.answer(
        "📝 <b>Шаг 6:</b> Теперь отправьте список BIO:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы очистить био и продолжить без текста.",
        reply_markup=skip_bio_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)

# Обработчик загрузки БИО (текст или .txt файл)
@router.message(BulkProfileUpdateFSM.uploading_bios)
@admin_only
async def upload_bios(message: types.Message, state: FSMContext):
    bios = []

    if message.document:
        document = message.document
        if not document.file_name.endswith(".txt"):
            await message.answer("⚠️ Пожалуйста, отправьте TXT файл с био или отправьте список в сообщении.")
            return
            
         # Сохраняем ID сообщения с архивом
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete", [])
        messages_to_delete.append(message.message_id)
        await state.update_data(messages_to_delete=messages_to_delete)
        
         # ✅ Пытаемся сразу удалить
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить сообщение с bio: {e}")

        temp_file = f"/tmp/{uuid.uuid4().hex}.txt"
        await message.bot.download(document, destination=temp_file)

        with open(temp_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            bios = [line.strip() for line in lines if line.strip()]
        
        os.remove(temp_file)
    else:
         # Пользователь отправил просто текст
        try:
            await message.delete()
        except Exception as e:
            print(f"[WARN] Не удалось удалить текстовое сообщение с bio: {e}")
        lines = message.text.strip().splitlines()
        bios = [line.strip() for line in lines if line.strip()]

    if not bios:
        await message.answer("⚠️ Список BIO пуст. Пожалуйста, попробуйте снова или нажмите кнопку «Очистить BIO».")
        return

    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])

    if len(bios) < len(selected_ids):
        await message.answer(
            f"❌ Недостаточно BIO!\n\nВыбрано аккаунтов: {len(selected_ids)}\nОтправлено BIO: {len(bios)}\n\n"
            "Каждому аккаунту нужно своё уникальное BIO. Пожалуйста, загрузите корректный список.",
            parse_mode="HTML"
        )
        return

    # Сохраняем список BIO
    await state.update_data(bios_list=bios)
    
    # Удаляем старое меню
    data = await state.get_data()
    old_menu_id = data.get("current_menu_id")
    if old_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_menu_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить старое меню: {e}")

    # Переход к следующему шагу: выбор времени запуска
    await state.set_state(BulkProfileUpdateFSM.choosing_schedule)

    new_msg = await message.answer(
        "Нажмите кнопку для немедленного запуска.",
        reply_markup=run_now_keyboard(),
        parse_mode="HTML"
    )
    await state.update_data(current_menu_id=new_msg.message_id)



# Обработчик немедленного запуска
@router.callback_query(F.data == "run_now")
@admin_only
async def run_task_now(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(scheduled_at=None)  # Нет отложенного времени
    await state.set_state(BulkProfileUpdateFSM.confirming_task)

    await callback.message.edit_text(
        "✅ Задача будет запущена немедленно!\n\nНажмите ещё раз для подтверждения запуска.",
        reply_markup=confirm_task_keyboard()
    )
    await callback.answer()

# Обработчик установки времени запуска
@router.message(BulkProfileUpdateFSM.choosing_schedule)
@admin_only
async def set_task_schedule(message: types.Message, state: FSMContext):
    try:
        user_input = message.text.strip()
        dt = datetime.datetime.strptime(user_input, "%d.%m.%Y %H:%M")

        # Приведем к часовому поясу Москва (если хочешь, можно потом настроить другой)
        moscow_tz = pytz.timezone("Europe/Moscow")
        dt = moscow_tz.localize(dt)

        now = datetime.datetime.now(moscow_tz)
        if dt < now:
            await message.answer("❌ Указанное время уже прошло. Пожалуйста, укажите время в будущем.")
            return

        await state.update_data(scheduled_at=dt.isoformat())
        await state.set_state(BulkProfileUpdateFSM.confirming_task)

        await message.answer(
            f"✅ Задача будет запущена по расписанию: {dt.strftime('%d.%m.%Y %H:%M')}\n\nНажмите ещё раз для подтверждения запуска.",
            reply_markup=confirm_task_keyboard()
        )

    except Exception:
        await message.answer(
            "⚠️ Неверный формат времени!\nОтправьте дату и время в формате <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
            "Пример: <b>30.04.2025 14:00</b>",
            parse_mode="HTML"
        )


@router.callback_query(F.data == "confirm_bulk_profile_update")
@admin_only
async def confirm_bulk_profile_update(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    skip_avatar = data.get("skip_avatar", False)
    selected_accounts = data.get("selected_accounts", [])
    avatars = data.get("avatars_list", [])
    usernames = data.get("usernames_list", [])
    firstnames = data.get("firstnames_list", [])
    lastnames = data.get("lastnames_list", [])
    bios = data.get("bios_list", [])
    scheduled_at = data.get("scheduled_at", None)

    if scheduled_at:
        await callback.message.edit_text("🕑 Отложенный запуск задач пока не реализован.")
        await callback.answer()
        return
        
    conn = get_connection()
    cur = conn.cursor()
    
    task_type = "bulk_profile_update"
    payload = {
        "accounts": selected_accounts,
        "usernames": usernames,
        "firstnames": firstnames,
        "lastnames": lastnames,
        "bios": bios,
        "avatars": avatars,
        "skip_avatar": skip_avatar,
        "scheduled_at": scheduled_at
    }

    cur.execute(
        """
        INSERT INTO tasks (account_id, type, payload, status, is_active, is_master, created_at)
        VALUES (%s, %s, %s, %s, true, true, now())
        RETURNING id
        """,
        (None, task_type, json.dumps(payload), "pending")
    )
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    new_task = {
        "id": task_id,
        "created_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "status": "Активно",
        "accounts_count": len(selected_accounts),
        "description": "Массовое обновление профиля"
    }
    bulk_profile_tasks_storage["tasks"].append(new_task)

    launch_msg = await callback.message.edit_text(
    "🚀 Задача запущена! Идёт массовое обновление профилей, по окончанию задачи Вам придет лог!"
    )

    # Ждём 2 секунды, чтобы пользователь увидел сообщение
    await asyncio.sleep(2)

    # Пробуем заменить на главное меню (или меню задач)
    try:
        await launch_msg.edit_text(
            "📋 Главное меню или меню задач (вставь сюда нужный текст)",
            reply_markup=main_menu_keyboard()  # или menu_tasks_keyboard()
        )
    except Exception as e:
        print(f"[WARN] Не удалось заменить сообщение запуска: {e}")


    logs = []

    async def update_single_account(
        account_id, 
        avatar_path=None, 
        username=None, 
        firstname=None, 
        lastname=None, 
        bio=None, 
        logs=None,
        skip_avatar=False,
        task_log_id=None
    ):
        account_log = []
        try:
            account = get_account_by_id(account_id)
            proxy = None
            if account.get("proxy_host"):
                proxy = {
                    "proxy_host": account.get("proxy_host"),
                    "proxy_port": account.get("proxy_port"),
                    "proxy_username": account.get("proxy_username"),
                    "proxy_password": account.get("proxy_password"),
                }

            client = await get_client(account["session_string"], proxy)
            await client.connect()

            account_log.append(f"Аккаунт ID: {account_id}, Username: @{account.get('username', '-')}")
            print(f"[DEBUG] Внутри update_single_account: task_log_id = {task_log_id}")
            
            if not skip_avatar:
                account_log.append("🖼️ Начинаем обработку аватарок")
                photos = await client(GetUserPhotosRequest(
                    user_id='me',
                    offset=0,
                    max_id=0,
                    limit=10
                ))

                if photos.photos:
                    photo_ids = [InputPhoto(
                        id=p.id,
                        access_hash=p.access_hash,
                        file_reference=p.file_reference
                    ) for p in photos.photos]

                    await client(DeletePhotosRequest(id=photo_ids))
                    account_log.append(f"🗑 Удалено {len(photo_ids)} старых аватарок")
                    print(f"[DEBUG] Удалено {len(photo_ids)} аватарок у аккаунта ID {account_id}")
                else:
                    print(f"[DEBUG] У аккаунта нет текущих аватарок")

                if avatar_path and os.path.exists(avatar_path):
                    try:
                        size = os.path.getsize(avatar_path)
                        if size > 5 * 1024 * 1024:
                            raise ValueError("Файл слишком большой (>5MB)")
                        print(f"[DEBUG] Аватарка найдена: {avatar_path}, размер: {size} байт")
                        file = await client.upload_file(avatar_path)
                        await client(UploadProfilePhotoRequest(file=file))
                        account_log.append("✅ Успешно обновили аватар аккаунта")
                        print("[DEBUG] Аватар установлен")
                    except Exception as e:
                        print(f"[ERROR] Ошибка при установке аватара: {e}")
                        account_log.append(f"❌ Ошибка при обновлении аватара: {e}")
                else:
                    print(f"[WARN] Аватарка не найдена: {avatar_path}")
                    account_log.append("❌ Аватарка не найдена или путь некорректный")
            else:
                account_log.append("⏭ Шаг обновления аватара пропущен")
                print("[DEBUG] Шаг обновления аватара пропущен")

            if username:
                try:
                    await client(UpdateUsernameRequest(username=username))
                    account_log.append("✅ Успешно обновили username")
                except UsernameOccupiedError:
                    account_log.append("❌ Username занят")
                except UsernameInvalidError:
                    account_log.append("❌ Некорректный username")
                except Exception as e:
                    account_log.append(f"❌ Ошибка при обновлении username: {e}")

            update_data = {}
            if firstname:
                update_data["first_name"] = firstname
            if lastname:
                update_data["last_name"] = lastname
            if bio is not None:
                update_data["about"] = bio

            if update_data:
                try:
                    await client(UpdateProfileRequest(**update_data))
                    account_log.append("✅ Успешно обновили имя, фамилию и био")
                except Exception as e:
                    account_log.append(f"❌ Ошибка при обновлении профиля: {e}")

            await client.disconnect()

        except Exception as e:
            account_log.append(f"❌ Общая ошибка обработки аккаунта ID {account_id}: {e}")

        if logs is not None:
            logs.append("\n".join(account_log))
            logs.append("________________________")


    # Обрезаем списки, если они длиннее, чем аккаунтов
    if usernames and len(usernames) > len(selected_accounts):
        usernames = usernames[:len(selected_accounts)]
    if firstnames and len(firstnames) > len(selected_accounts):
        firstnames = firstnames[:len(selected_accounts)]
    if lastnames and len(lastnames) > len(selected_accounts):
        lastnames = lastnames[:len(selected_accounts)]
    if bios and len(bios) > len(selected_accounts):
        bios = bios[:len(selected_accounts)]

    # Проверяем длину юзернеймов
    if usernames and len(usernames) < len(selected_accounts):
        await callback.message.edit_text("❌ Недостаточно юзернеймов для всех аккаунтов.")
        await callback.answer()
        return

    tasks = []
    for idx, account_id in enumerate(selected_accounts):
        # Обработка аватарок
        avatar = None
        if not skip_avatar and avatars:
            if len(avatars) >= len(selected_accounts):
                avatar = avatars[idx]
            else:
                avatar = choice(avatars)

        # Обработка юзернеймов
        uname = usernames[idx] if usernames and idx < len(usernames) else None

        # Обработка имён
        fname = None
        if firstnames:
            if len(firstnames) >= len(selected_accounts):
                fname = firstnames[idx]
            else:
                fname = choice(firstnames)

        # Обработка фамилий
        lname = None
        if lastnames:
            if len(lastnames) >= len(selected_accounts):
                lname = lastnames[idx]
            else:
                lname = choice(lastnames)

        # Обработка BIO
        bio = None
        if bios:
            if len(bios) >= len(selected_accounts):
                bio = bios[idx]
            else:
                bio = choice(bios)

        tasks.append(
            update_single_account(
                account_id=account_id,
                avatar_path=avatar,
                username=uname,
                firstname=fname,
                lastname=lname,
                bio=bio,
                logs=logs,
                skip_avatar=skip_avatar,
                task_log_id=task_id
            )
        )

    # Добавляем заголовок задачи перед обработкой аккаунтов
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    logs.append(f"Задача №{task_id} начата")
    logs.append(f"🕓 Время: {now_str}")
    logs.append(f"👥 Всего аккаунтов: {len(selected_accounts)}\n")


    await asyncio.gather(*tasks)
    
    # ✅ ОБНОВЛЕНИЕ СТАТУСА ЗАДАЧИ В БД
    try:
        conn_update = get_connection()
        cur_update = conn_update.cursor()
        cur_update.execute("""
            UPDATE tasks
            SET status = %s, updated_at = now()
            WHERE id = %s
        """, ("completed", task_id))
        conn_update.commit()
        cur_update.close()
        conn_update.close()
        print(f"[INFO] Задача {task_id} завершена, статус обновлён на 'completed'")
    except Exception as e:
        print(f"[ERROR] Ошибка обновления статуса задачи {task_id}: {e}")
    
    # Сохраняем лог в БД построчно
    conn = get_connection()
    cur = conn.cursor()
    for entry in logs:
        cur.execute("""
            INSERT INTO task_logs (task_id, timestamp, message, status)
            VALUES (%s, now(), %s, 'done')
        """, (task_id, entry))
    conn.commit()
    cur.close()
    conn.close()


    for task in bulk_profile_tasks_storage["tasks"]:
        if task["id"] == task_id:
            task["status"] = "Завершено"
            task["finished_at"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            break

    temp_log_path = f"/tmp/bulk_profile_update_log_{uuid.uuid4().hex}.txt"

    if not logs:
        logs.append("❗ Все аккаунты завершились ошибками или не были обработаны.")

    try:
        with open(temp_log_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(logs))
            
    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка создания лог-файла: {e}")
        await state.clear()
        return
            
    # ⏺️ Сохраняем логи в БД построчно
    try:
        conn = get_connection()
        cur = conn.cursor()
        for entry in logs:
            cur.execute("""
                INSERT INTO task_logs (task_id, timestamp, message, status)
                VALUES (%s, now(), %s, 'done')
            """, (task_id, entry))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Ошибка при сохранении логов в БД: {e}")
  

    if os.path.exists(temp_log_path) and os.path.getsize(temp_log_path) > 0:
        try:
            log_file = FSInputFile(temp_log_path)
            await callback.message.answer_document(
                document=log_file,
                caption="📝 Лог выполнения задачи",
                reply_markup=ok_to_delete_keyboard()
            )
        except Exception as e:
            await callback.message.answer(f"⚠️ Ошибка отправки лог-файла: {e}")
    else:
        await callback.message.answer("⚠️ Задача завершена, но лог-файл пуст или не был создан.")

    try:
        os.remove(temp_log_path)
    except Exception:
        pass
        
    data = await state.get_data()
    messages_to_delete = data.get("messages_to_delete", [])
    user_id = callback.from_user.id

    for msg_id in messages_to_delete:
        try:
            await callback.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception as e:
            print(f"[WARN] Не удалось удалить сообщение {msg_id}: {e}")


    await state.clear()




# Обработчик кнопки ОК — удаление сообщения
@router.callback_query(F.data == "delete_log_message")
@admin_only
async def delete_log_message(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        print(f"[WARN] Не удалось удалить сообщение: {e}")

    # Всегда лучше отправлять ответ на callback, но оборачиваем в try на случай, если слишком поздно
    try:
        await callback.answer("✅ Лог удалён!", show_alert=False)
    except Exception as e:
        print(f"[WARN] Ответ на callback не отправлен: {e}")


# Обработчик кнопки "Очистить BIO"
@router.callback_query(F.data == "skip_bio")
@admin_only
async def skip_bio(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bios_list=None)  # BIO будет пустой
    await state.set_state(BulkProfileUpdateFSM.choosing_schedule)

    await callback.message.edit_text(
        "Нажмите кнопку для немедленного запуска.",
        reply_markup=run_now_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

# Обработчик кнопки "Не обновлять Имя"
@router.callback_query(F.data == "skip_firstname")
@admin_only
async def skip_firstname(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(firstnames_list=None)
    await state.set_state(BulkProfileUpdateFSM.uploading_lastnames)

    await callback.message.edit_text(
        "👤 <b>Шаг 5:</b> Теперь отправьте список фамилий:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы пропустить обновление фамилий.",
        reply_markup=skip_lastname_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

# Обработчик кнопки "Не обновлять Фамилию"
@router.callback_query(F.data == "skip_lastname")
@admin_only
async def skip_lastname(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(lastnames_list=None)
    await state.set_state(BulkProfileUpdateFSM.uploading_bios)

    await callback.message.edit_text(
        "📝 <b>Шаг 6:</b> Теперь отправьте список BIO:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы очистить био и продолжить без текста.",
        reply_markup=skip_bio_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "skip_avatar")
@admin_only
async def skip_avatar(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(
        avatars_list=None,
        skip_avatar=True
    )
    await state.set_state(BulkProfileUpdateFSM.uploading_usernames)

    await callback.message.edit_text(
        "✍️ Шаг 3: Теперь отправьте список username:\n\n"
        "- Либо текстом (по одному в строку)\n"
        "- Либо отправьте .txt файл\n\n"
        "Или нажмите кнопку, чтобы пропустить установку username.",
        reply_markup=skip_username_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "skip_username")
@admin_only
async def skip_username(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(usernames_list=None)
    await state.set_state(BulkProfileUpdateFSM.uploading_firstnames)
    await callback.message.edit_text(
        "👤 <b>Шаг 4:</b> Теперь отправьте список имён:\n\n- Либо текстом (по одному в строку)\n- Либо отправьте .txt файл\n\nИли нажмите кнопку, чтобы пропустить обновление имён.",
        reply_markup=skip_firstname_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "clear_bio")
@admin_only
async def clear_bio(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(bios_list=[""])  # Очистка био
    await state.set_state(BulkProfileUpdateFSM.choosing_schedule)
    await callback.message.edit_text(
        "Нажмите кнопку для немедленного запуска.",
        reply_markup=run_now_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "task_pick_accounts")
async def bulk_pick_accounts_start(callback: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()  # [{'id','username','phone','group_id', ...}]
    groups   = get_account_groups_with_count()

    await state.update_data(**{
        STATE_ACCOUNTS: accounts,
        STATE_SELECTED: set(),
        STATE_PAGE: 0,
    })

    kb = bulk_accounts_keyboard(accounts, set(), page=0, per_page=10, groups=groups)
    await callback.message.edit_text(
        "Шаг 1: Выберите аккаунты для обновления профиля.\n\n"
        "Вы можете выбрать вручную или нажать «✅ Выбрать все».\n"
        "Также можно быстро добавить всех из выбранной группы.\n"
        "Когда выберете аккаунты — нажмите «➡ Далее».",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("bulk_toggle:"))
async def bulk_toggle_account(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    selected = set(data.get(STATE_SELECTED, set()))
    page     = int(data.get(STATE_PAGE, 0))

    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.add(acc_id)

    await state.update_data(**{STATE_SELECTED: selected})

    groups = get_account_groups_with_count()
    kb = bulk_accounts_keyboard(accounts, selected, page=page, per_page=10, groups=groups)
    await callback.message.edit_text("Шаг 1: Выберите аккаунты для обновления профиля.", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("bulk_page:"))
async def bulk_change_page(callback: types.CallbackQuery, state: FSMContext):
    new_page = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    selected = set(data.get(STATE_SELECTED, set()))
    await state.update_data(**{STATE_PAGE: new_page})

    groups = get_account_groups_with_count()
    kb = bulk_accounts_keyboard(accounts, selected, page=new_page, per_page=10, groups=groups)
    await callback.message.edit_text("Шаг 1: Выберите аккаунты для обновления профиля.", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "bulk_select_all")
async def bulk_select_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    selected = {a["id"] for a in accounts}  # глобально все
    await state.update_data(**{STATE_SELECTED: selected})

    groups = get_account_groups_with_count()
    page = int(data.get(STATE_PAGE, 0))
    kb = bulk_accounts_keyboard(accounts, selected, page=page, per_page=10, groups=groups)
    await callback.message.edit_text("Шаг 1: Выберите аккаунты для обновления профиля.", reply_markup=kb)
    await callback.answer("Выбраны все аккаунты")

@router.callback_query(F.data == "bulk_clear_all")
async def bulk_clear_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    await state.update_data(**{STATE_SELECTED: set()})

    groups = get_account_groups_with_count()
    page = int(data.get(STATE_PAGE, 0))
    kb = bulk_accounts_keyboard(accounts, set(), page=page, per_page=10, groups=groups)
    await callback.message.edit_text("Шаг 1: Выберите аккаунты для обновления профиля.", reply_markup=kb)
    await callback.answer("Сняты все аккаунты")

# НОВОЕ: быстрый выбор по группе
    
@router.callback_query(F.data.startswith("bulk_group_pick:"), BulkProfileUpdateFSM.selecting_accounts)
@admin_only
async def bulk_pick_group(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    page     = int(data.get("page", 0))

    # ids всех акков этой группы
    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}

    # если группы пустая (не должно, мы показываем только count>=1) – на всякий
    if not ids_in_group:
        await callback.answer("В этой группе нет аккаунтов", show_alert=False)
        return

    # перезаписываем выбранные — только эта группа
    await state.update_data(selected_accounts=list(ids_in_group))

    # если на текущей странице выбор визуально не изменится — можно не редактировать
    start = page * PER_PAGE
    page_ids = {a["id"] for a in accounts[start:start + PER_PAGE]}
    changed_on_page = bool(ids_in_group & page_ids)  # на экране есть выбранные

    kb = bulk_accounts_keyboard(
        accounts, ids_in_group,
        page=page, per_page=PER_PAGE,
        groups=get_account_groups_with_count()
    )

    if changed_on_page:
        await safe_edit_markup(callback.message, kb)

    await callback.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")


    # перерисовываем только клавиатуру
    kb = bulk_accounts_keyboard(
        accounts, selected,
        page=page, per_page=PER_PAGE,
        groups=get_account_groups_with_count()
    )
    await safe_edit_markup(callback.message, kb)
    await callback.answer(f"Добавлено из группы: {len(to_add)}")


