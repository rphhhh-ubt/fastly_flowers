# handlers/proxies.py
import os
from aiogram.types import FSInputFile,InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from states.import_proxies import ImportProxiesStates
from utils.check_access import admin_only
from keyboards.proxy_menu import proxy_menu_keyboard
from keyboards.proxy_list import proxy_list_keyboard
from app.db import (
    save_proxy,
    get_all_proxies,
    update_proxy_status_by_id,
    delete_proxy_by_id,
    delete_bad_proxies,
    get_proxy_by_id,
    proxy_exists,
    get_all_accounts,
    get_proxy_by_id,
)
from app.utils.proxy_checker import is_proxy_working
from keyboards.back_to_proxies_menu import back_to_proxies_menu_keyboard


router = Router()

@router.callback_query(F.data == "import_proxies")
@admin_only
async def start_import_proxies(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📥 Отправьте список прокси в формате:\n\n<code>ip:port:login:password</code>\nили\n<code>ip:port</code>\n\nМожно сразу много — по одной на строку.",
        reply_markup=back_to_proxies_menu_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ImportProxiesStates.waiting_for_proxies)
    await callback.answer()

@router.message(ImportProxiesStates.waiting_for_proxies)
@admin_only
async def process_proxies_list(message: types.Message, state: FSMContext):
    

    proxies_raw = message.text.strip().splitlines()

    # Сразу отвечаем пользователю
    await message.answer("⏳ Идет импорт прокси...\nПо завершению Вам будет отправлен лог.")

    total_proxies = 0
    working_proxies = 0
    bad_proxies = 0
    duplicate_proxies = 0

    working_list = []
    bad_list = []
    duplicate_list = []

    for line in proxies_raw:
        line = line.strip()
        if not line:
            continue  # пропускаем пустые строки

        parts = line.split(":")
        
        # Поддерживаем 2 (ip:port) или 4 (ip:port:user:pass) части
        if len(parts) not in (2, 4):
            bad_proxies += 1
            bad_list.append(f"{line} → ❌ Неверный формат")
            continue

        host = parts[0].strip()
        port_str = parts[1].strip()

        # Проверяем, что порт — это число
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError("Порт вне диапазона")
        except ValueError:
            bad_proxies += 1
            bad_list.append(f"{line} → ❌ Некорректный порт: '{port_str}'")
            continue

        username = password = None
        if len(parts) == 4:
            username = parts[2].strip() or None
            password = parts[3].strip() or None

        # Проверка на дубликаты
        if proxy_exists(host, port, username, password):
            duplicate_proxies += 1
            duplicate_repr = f"{host}:{port}" + (f":{username}:{password}" if username else "")
            duplicate_list.append(duplicate_repr)
            continue

        # Теперь безопасно формируем proxy_conf
        proxy_conf = {
            "type": "socks5",
            "host": host,
            "port": port,  # ← уже int!
            "username": username,
            "password": password,
        }

        total_proxies += 1

        # Проверка на валидность
        is_ok = await is_proxy_working(proxy_conf)

        if is_ok:
            save_proxy(
                host=proxy_conf["host"],
                port=proxy_conf["port"],
                username=proxy_conf["username"],
                password=proxy_conf["password"]
            )
            working_proxies += 1
            working_list.append(f"{proxy_conf['host']}:{proxy_conf['port']}" + (f":{proxy_conf['username']}:{proxy_conf['password']}" if proxy_conf['username'] else ""))
        else:
            bad_proxies += 1
            bad_list.append(f"{proxy_conf['host']}:{proxy_conf['port']}" + (f":{proxy_conf['username']}:{proxy_conf['password']}" if proxy_conf['username'] else ""))

        total_proxies += 1

        # Проверка на дубли
        if proxy_exists(proxy_conf["host"], proxy_conf["port"], proxy_conf["username"], proxy_conf["password"]):
            duplicate_proxies += 1
            duplicate_list.append(f"{proxy_conf['host']}:{proxy_conf['port']}" + (f":{proxy_conf['username']}:{proxy_conf['password']}" if proxy_conf['username'] else ""))
            continue

        
    # --- Создаём лог-файл ---
    log_text = []
    log_text.append(f"✅ Импорт прокси завершён!\n")
    log_text.append(f"Всего отправлено: {total_proxies}")
    log_text.append(f"Рабочих новых прокси: {working_proxies}")
    log_text.append(f"Дубликатов: {duplicate_proxies}")
    log_text.append(f"Нерабочих: {bad_proxies}")
    log_text.append("\n--- Рабочие прокси ---\n")
    log_text.extend(working_list if working_list else ["(нет)"])
    log_text.append("\n--- Дубликаты прокси ---\n")
    log_text.extend(duplicate_list if duplicate_list else ["(нет)"])
    log_text.append("\n--- Нерабочие прокси ---\n")
    log_text.extend(bad_list if bad_list else ["(нет)"])

    log_content = "\n".join(log_text)

    log_path = f"/tmp/proxy_import_log.txt"

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_content)

    # Отправляем лог-файл
    await message.answer_document(FSInputFile(log_path), caption="📝 Лог импорта прокси")

    try:
        os.remove(log_path)
    except Exception as e:
        print(f"[⚠️] Ошибка удаления лог-файла: {e}")

    # Вывод финального результата
    if working_proxies > 0:
        await message.answer(
            "✅ Импорт успешно завершён. Выберите действие:",
            reply_markup=back_to_proxies_menu_keyboard()
        )
    else:
        await message.answer(
            "❌ Все прокси оказались нерабочими или дубликатами. Попробуйте снова.",
            reply_markup=back_to_proxies_menu_keyboard()
        )

    await state.clear()

@router.callback_query(F.data == "view_proxies")
@admin_only
async def view_proxies(callback: types.CallbackQuery):
    accounts = get_all_accounts()

    # Синхронизация прокси из аккаунтов
    for account in accounts:
        host = account.get("proxy_host")
        port = account.get("proxy_port")
        username = account.get("proxy_username")
        password = account.get("proxy_password")

        if host and port:
            if not proxy_exists(host, port, username, password):
                save_proxy(host, port, username, password)

    proxies = get_all_proxies()

    if not proxies:
        await callback.message.edit_text(
            "⚠️ Прокси отсутствуют.",
            reply_markup=back_to_proxies_menu_keyboard()
        )
        return

    await callback.message.edit_text(
        "🌐 Список прокси:\n\nВыберите действие:",
        reply_markup=proxy_list_keyboard(proxies)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_proxy_"))
@admin_only
async def check_single_proxy(callback: types.CallbackQuery):
    proxy_id = int(callback.data.split("_")[2])
    proxy = get_proxy_by_id(proxy_id)

    if not proxy:
        await callback.answer("⚠️ Прокси не найден.", show_alert=True)
        return

    proxy_conf = {
        "type": "socks5",
        "host": proxy["host"],
        "port": proxy["port"],
        "username": proxy.get("username"),
        "password": proxy.get("password")
    }

    is_ok = await is_proxy_working(proxy_conf)

    if is_ok:
        update_proxy_status_by_id(proxy_id, "working")
        await callback.answer("✅ Прокси рабочий!", show_alert=True)
    else:
        update_proxy_status_by_id(proxy_id, "bad")
        await callback.answer("❌ Прокси не работает!", show_alert=True)

    await view_proxies(callback)

@router.callback_query(F.data.startswith("delete_proxy_"))
@admin_only
async def delete_proxy(callback: types.CallbackQuery):
    proxy_id = int(callback.data.split("_")[2])
    delete_proxy_by_id(proxy_id)
    await callback.answer("🗑 Прокси удалён.", show_alert=True)
    await view_proxies(callback)

@router.callback_query(F.data == "delete_bad_proxies")
@admin_only
async def delete_all_bad(callback: types.CallbackQuery):
    delete_bad_proxies()
    await callback.answer("🗑 Все нерабочие прокси удалены.", show_alert=True)
    await view_proxies(callback)

from aiogram.types import FSInputFile
import os

@router.callback_query(F.data == "check_all_proxies")
@admin_only
async def check_all_proxies(callback: types.CallbackQuery):
    # Шаг 1: Меняем текст сообщения на "Идёт проверка"
    await callback.message.edit_text(
        "🔄 Идёт проверка всех прокси...\n\nПожалуйста, подождите...",
        reply_markup=None
    )

    proxies = get_all_proxies()

    log_lines = []
    checked = 0
    working = 0
    bad = 0

    for proxy in proxies:
        proxy_conf = {
            "type": "socks5",
            "host": proxy["host"],
            "port": proxy["port"],
            "username": proxy.get("username"),
            "password": proxy.get("password")
        }

        is_ok = await is_proxy_working(proxy_conf)

        if is_ok:
            update_proxy_status_by_id(proxy["id"], "working")
            working += 1
            status_emoji = "✅"
            status_text = "Рабочий"
        else:
            update_proxy_status_by_id(proxy["id"], "bad")
            bad += 1
            status_emoji = "❌"
            status_text = "Нерабочий"

        checked += 1

        proxy_label = f"{proxy['host']}:{proxy['port']}"
        log_lines.append(f"{status_emoji} {proxy_label} - {status_text}")

    # Добавляем итог в лог
    log_lines.append("")
    log_lines.append(f"Итог:\n✅ Рабочих: {working}\n❌ Плохих: {bad}\nВсего проверено: {checked}")

    log_text = "\n".join(log_lines)

    # Сохраняем лог в файл
    log_file_path = f"/tmp/proxies_check_log_{callback.from_user.id}.txt"
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write(log_text)

    # Шаг 2: Удаляем сообщение "Идёт проверка..."
    try:
        await callback.message.delete()
    except Exception as e:
        print(f"[WARNING] Не удалось удалить сообщение проверки: {e}")

    # Шаг 3: Отправляем новое меню прокси
    await callback.bot.send_message(
        chat_id=callback.from_user.id,
        text="🌐 Список прокси:\n\nВыберите действие:",
        reply_markup=proxy_list_keyboard(get_all_proxies())
    )

    # Создаём кнопки
    delete_log_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ ОК", callback_data="delete_log_message")]
        ]
    )

    # Отправляем лог с кнопкой
    await callback.bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile(log_file_path),
        caption="📄 Лог проверки всех прокси",
        reply_markup=delete_log_keyboard
    )

    # Удаляем лог-файл
    if os.path.exists(log_file_path):
        os.remove(log_file_path)


@router.callback_query(F.data.startswith("confirm_delete_proxy_"))
@admin_only
async def confirm_delete_proxy(callback: types.CallbackQuery):
    proxy_id = int(callback.data.split("_")[3])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_proxy_{proxy_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="view_proxies")
            ]
        ]
    )

    await callback.message.edit_text(
        "Вы уверены, что хотите удалить этот прокси?",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_bad_proxies")
@admin_only
async def confirm_delete_all_bad(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить плохие", callback_data="delete_bad_proxies"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="view_proxies")
            ]
        ]
    )

    await callback.message.edit_text(
        "Вы уверены, что хотите удалить все плохие прокси?",
        reply_markup=keyboard
    )
    await callback.answer()

from app.db import update_proxy_status

@router.callback_query(F.data.startswith("check_proxylist_"))
@admin_only
async def check_single_proxy(callback: types.CallbackQuery):

    proxy_id = int(callback.data.split("_")[2])
    proxy = get_proxy_by_id(proxy_id)

    if not proxy:
        await callback.answer("⚠️ Прокси не найден.", show_alert=True)
        return

    proxy_conf = {
        "type": "socks5",
        "host": proxy["host"],
        "port": proxy["port"],
        "username": proxy.get("username"),
        "password": proxy.get("password"),
    }

    is_working = await is_proxy_working(proxy_conf)

    # 👉 Здесь обновляем статус в базе!
    if is_working:
        update_proxy_status_by_id(proxy_id, "working")
        await callback.answer("✅ Прокси работает!", show_alert=True)
    else:
        update_proxy_status_by_id(proxy_id, "bad")
        await callback.answer("❌ Прокси не работает!", show_alert=True)

@router.callback_query(F.data == "delete_log_message")
@admin_only
async def delete_log_message(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
        await callback.answer("✅ Лог удалён!", show_alert=False)
    except Exception as e:
        print(f"❗ Ошибка удаления сообщения: {e}")
        await callback.answer("⚠️ Не удалось удалить сообщение.", show_alert=True)
