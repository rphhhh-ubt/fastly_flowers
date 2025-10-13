# handlers/accounts.py
from telethon.tl.custom import Button
from telethon.tl.types import KeyboardButtonCallback  # Тип inline-кнопки
import inspect
from datetime import datetime
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram import Router, types, F, Bot
from config import BOT_TOKEN
from utils.check_access import admin_only
from states.import_accounts import ImportStates
#from utils.import_accounts import import_accounts_from_zip
from app.utils.import_accounts import import_accounts_from_zip
from app.telegram_client import create_client_from_session, verify_account_status, get_client
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from keyboards.account_actions import account_actions_keyboard
from utils.account_helpers import build_account_card
from app.db import (
    get_available_api_key,
    check_spamblock_status,
    get_all_accounts,
    get_account_by_id,
    update_account_info,
    update_spamblock_check,
    update_account_status_to_banned,
    update_account_status_to_active,
    update_account_status_to_needs_login,
    update_account_status_to_proxy_error,
    update_account_status_to_unknown,
    update_spamblock_check_full,
    get_all_proxies,
    count_accounts_using_proxy,
    get_proxy_by_id,
    update_account_proxy,
    log_spambot_message,
    has_spambot_log, 
    get_spambot_log,
    get_spambot_logs_for_account,
    update_account_status_to_frozen,
    get_connection,
    delete_account_by_id,
)
import os, zipfile, asyncio, traceback, socks, re, dateparser, pytz, tempfile, uuid
from keyboards.accounts_list import accounts_list_keyboard
from keyboards.back_menu import back_to_accounts_menu
from keyboards.accounts_menu import accounts_menu_keyboard
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from telethon.errors import RPCError
from telethon.tl.functions.account import UpdateUsernameRequest, UpdateProfileRequest
from keyboards.delete_accounts_keyboard import delete_accounts_keyboard
from keyboards.bulk_profile_update_keyboards import select_accounts_keyboard
from aiogram.filters.state import StateFilter
from utils.freeze_checker import is_profile_frozen



router = Router()
TEMP_FOLDER = "/tmp/uploads/"

def ok_delete_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❎ ОК (удалить сообщение)", callback_data="delete_code_msg")]
    ])



@router.callback_query(F.data.startswith("accpg:"))
async def switch_accounts_page(callback: types.CallbackQuery):
    # Парсим номер страницы из callback_data
    try:
        _, page_str = callback.data.split(":")
        page = int(page_str)
    except Exception:
        await callback.answer("Некорректная страница", show_alert=False)
        return

    # Получаем список аккаунтов (или тут можно сделать DB limit/offset)
    accounts = get_all_accounts()  # вернёт list[dict]

    # Перерисовываем клавиатуру для нужной страницы
    kb = accounts_list_keyboard(accounts, page=page)

    try:
        # Обновляем только разметку (быстрее и чище)
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        # если сообщение уже не редактируемое, то можно отправить новое
        # но чаще всего edit_reply_markup достаточно
        await callback.message.answer("Не удалось обновить список, отправляю заново…")
        await callback.message.answer("Выбери аккаунт:", reply_markup=kb)

    await callback.answer()


@router.message(Command("accounts"))
@admin_only
async def cmd_accounts(message: types.Message):
    accounts = get_all_accounts()

    if not accounts:
        await message.answer("⚠️ Нет доступных аккаунтов.")
        return

    await message.answer(
        "📋 Выберите аккаунт:",
        reply_markup=accounts_keyboard(accounts)
    )

@router.callback_query(F.data.startswith("account_"))
@admin_only
async def account_details(callback: types.CallbackQuery):
    
    # ---- Безопасно извлекаем ID ----
    parts = callback.data.split("_")
    if len(parts) < 2 or not parts[1].isdigit():
        # Это не кнопка аккаунта — выходим
        return
    account_id = int(parts[1])
    # --------------------------------

    bot = Bot(token=BOT_TOKEN)
    account = get_account_by_id(account_id)

    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        await bot.session.close()
        return

    text = build_account_card(account)

    try:
        await callback.message.delete()  # Удаляем старое сообщение
    except Exception as e:
        print(f"[WARNING] Ошибка удаления старого сообщения: {e}")

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=text,
        reply_markup=account_actions_keyboard(account_id),
        parse_mode="HTML"
    )

    await callback.answer()
    await bot.session.close()



# аналогично все остальные функции callback_query:
@router.callback_query(F.data == "back_to_accounts")
@admin_only
async def back_to_accounts(callback: types.CallbackQuery):
    accounts = get_all_accounts()

    if not accounts:
        await callback.message.edit_text("⚠️ Нет доступных аккаунтов.")
        return

    await callback.message.edit_text(
        "📋 Выберите аккаунт:",
        reply_markup=accounts_keyboard(accounts)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_spamblock_"))
@admin_only
async def check_spamblock(callback: types.CallbackQuery):


    account_id = int(callback.data.split("_")[2])
    account = get_account_by_id(account_id)

    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    proxy = None
    if account.get("proxy_host"):
        proxy = {
            "proxy_host": account.get("proxy_host"),
            "proxy_port": account.get("proxy_port"),
            "proxy_username": account.get("proxy_username"),
            "proxy_password": account.get("proxy_password"),
        }

    client = None
    try:
        client = await get_client(account["session_string"], proxy)
        await client.connect()

        # Удаляем переписку с SpamBot
        try:
            await client.delete_dialog('SpamBot')
        except Exception:
            pass

        await asyncio.sleep(1)
        await client.send_message("SpamBot", "/start")

        result = None

        for _ in range(15):
            await asyncio.sleep(1.0)
            msgs = await client.get_messages("SpamBot", limit=1)
            if msgs and "/start" not in msgs[0].message:
                msg_text = msgs[0].message
                lowered = msg_text.lower()

                blocked_keywords = ["unfortunately", "ограничен", "заблокирован", "limited", "лимит"]
                is_blocked = any(k in lowered for k in blocked_keywords)

                until = None
                match = re.search(r"(until|до)\s+([A-Za-zА-Яа-я0-9,\.\s:]+UTC)", msg_text, re.IGNORECASE)
                if match:
                    try:
                        date_str = match.group(2)
                        until = dateparser.parse(date_str, languages=["en", "ru"])
                        print(f"📆 Найдена дата разблокировки: {until}")
                    except Exception as e:
                        print(f"❌ Ошибка парсинга даты разблокировки: {e}")

                result = {
                    "spam_blocked": is_blocked,
                    "until": until,
                    "reason": msg_text
                }
                break

        if not result:
            result = {
                "spam_blocked": False,
                "until": None,
                "reason": "❗ Ошибка проверки: SpamBot не ответил"
            }

        # Обновляем БД
        update_spamblock_check_full(
            account_id,
            is_blocked=result["spam_blocked"],
            block_until=result.get("until"),
            reason=result.get("reason")
        )

        # Показываем итоговый alert
        moscow_tz = pytz.timezone("Europe/Moscow")

        if result["spam_blocked"]:
            if result.get("until"):
                until_moscow = result["until"].astimezone(moscow_tz)
                block_until_str = until_moscow.strftime("%d.%m.%Y %H:%M")
                await callback.answer(f"🚫 Аккаунт в спамблоке до {block_until_str}!", show_alert=True)
            else:
                await callback.answer("🚫 Аккаунт в спамблоке!", show_alert=True)
        else:
            await callback.answer("✅ Спамблока нет!", show_alert=True)

    except Exception as e:
        print(f"❗ Ошибка проверки спамблока: {e}")
        error_text = str(e).lower()

        if any(word in error_text for word in ["proxy", "timeout", "connection refused", "network unreachable"]):
            error_reason = "❗ Ошибка проверки: прокси недоступен"
        else:
            error_reason = "❗ Ошибка проверки: неизвестная ошибка"

        update_spamblock_check_full(
            account_id,
            is_blocked=False,
            block_until=None,
            reason=error_reason
        )

        await callback.answer(error_reason, show_alert=True)

    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

        # Отправляем обновлённую карточку аккаунта
        updated_account = get_account_by_id(account_id)
        card_text = build_account_card(updated_account)

        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=card_text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )




@router.callback_query(F.data.startswith("check_proxy_"))
@admin_only
async def check_proxy(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = get_account_by_id(account_id)

    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    proxy = None
    if account.get("proxy_host"):
        proxy = {
            "type": account.get("proxy_type"),
            "host": account.get("proxy_host"),
            "port": account.get("proxy_port"),
            "username": account.get("proxy_username"),
            "password": account.get("proxy_password"),
        }

    if not proxy:
        await callback.answer("❌ Прокси не найден для этого аккаунта.", show_alert=True)
        return

    from app.utils.proxy_checker import is_proxy_working
    from app.db import update_proxy_status  # <<< добавил импорт!

    is_working = await is_proxy_working(proxy)

    if is_working:
        update_proxy_status(account_id, "working")
        await callback.answer("🛡️ Прокси работает!", show_alert=True)
    else:
        update_proxy_status(account_id, "bad")
        await callback.answer("❗ Прокси не отвечает!", show_alert=True)
        

@router.callback_query(F.data.startswith("update_profile_"))
@admin_only
async def update_profile(callback: types.CallbackQuery):

    bot = Bot(token=BOT_TOKEN)

    account_id = int(callback.data.split("_")[2])
    account = get_account_by_id(account_id)

    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    message = await bot.send_message(
        chat_id=callback.from_user.id,
        text="🔄 Проверка аккаунта...",
        parse_mode="HTML"
    )

    await asyncio.sleep(1)

    proxy = None
    if account.get("proxy_host"):
        proxy = {
            "proxy_host": account.get("proxy_host"),
            "proxy_port": account.get("proxy_port"),
            "proxy_username": account.get("proxy_username"),
            "proxy_password": account.get("proxy_password"),
        }

    status = await verify_account_status(account["session_string"], account["phone"], proxy)

    if status == "OK":
        update_account_status_to_active(account_id)

        try:

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

            me = await client.get_me()

            # Получаем BIO
            full = await client(GetFullUserRequest(me))
            about = full.full_user.about or "-"  # <-- ВАЖНО!
            print(f"full.full_user.about → {about}")

            
            # 👉 Добавляем отладочные принты
            print(f"📝 Полученные данные профиля:")
            print(f"Username: {me.username}")
            print(f"First Name: {me.first_name}")
            print(f"Last Name: {me.last_name}")
            print(f"About (BIO): {about}")

            # Обновляем данные аккаунта в базе
            update_account_info(
                account_id,
                username=me.username or None,
                first_name=me.first_name or "-",
                last_name=me.last_name or "-",
                about=about
            )

        except Exception as e:
            print(f"❗ Ошибка при обновлении данных профиля: {e}")

        finally:
            try:
                await client.disconnect()
            except Exception as e:
                print(f"⚠️ Ошибка при закрытии клиента: {e}")

        # После обновления данных — показываем сообщение
        await message.edit_text("✅ Аккаунт активный.")  # показываем сообщение
        await asyncio.sleep(2)  # даём пользователю увидеть сообщение
        await message.delete()  # удаляем сообщение

        # Загружаем обновлённые данные аккаунта
        account = get_account_by_id(account_id)
        text = build_account_card(account)

        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if status == "NEEDS_ATTENTION":
        update_account_status_to_needs_login(account_id)
        await message.edit_text("❗ Аккаунт требует повторной авторизации.")
        await asyncio.sleep(2)  # даём пользователю увидеть сообщение
        await message.delete()  # удаляем сообщение "Аккаунт активный"
    
        account = get_account_by_id(account_id)
        text = build_account_card(account)
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if status == "BANNED":
        update_account_status_to_banned(account_id)
        await message.edit_text("🚫 Аккаунт заблокирован.")
        await asyncio.sleep(2)
        await message.delete()

        account = get_account_by_id(account_id)
        text = build_account_card(account)
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    
    if status == "PROXY_ERROR":
        update_account_status_to_proxy_error(account_id)
        await message.edit_text("🛡️ Ошибка подключения к прокси. Проверьте настройки.")
        await asyncio.sleep(2)  # даём пользователю увидеть сообщение
        await message.delete()  # удаляем сообщение "Аккаунт активный"
    
        account = get_account_by_id(account_id)
        text = build_account_card(account)
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if status == "UNKNOWN":
        update_account_status_to_unknown(account_id)
        await message.edit_text("⚠️ Ошибка обновления, проверьте прокси")
        await asyncio.sleep(2)  # даём пользователю увидеть сообщение
        await message.delete()  # удаляем сообщение "Аккаунт активный"
    
        account = get_account_by_id(account_id)
        text = build_account_card(account)
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=account_actions_keyboard(account_id),
            parse_mode="HTML"
        )
        await callback.answer()
        return

@router.callback_query(F.data.startswith("confirm_delete_account_"))
@admin_only
async def confirm_delete_account(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    account = get_account_by_id(account_id)
    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    username = account.get("username") or f"ID {account_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_account_{account_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"account_{account_id}")
            ]
        ]
    )

    await callback.message.edit_text(
        f"⚠️ Вы уверены, что хотите безвозвратно удалить аккаунт <b>{username}</b>?",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("delete_account_"))
@admin_only
async def delete_account(callback: types.CallbackQuery):
    from app.db import delete_account_by_id, account_has_active_tasks
    account_id = int(callback.data.split("_")[2])

    if account_has_active_tasks(account_id):
        await callback.answer(
            "❌ Невозможно удалить аккаунт: он связан с активной задачей.",
            show_alert=True
        )
        return

    delete_account_by_id(account_id)

    await callback.message.edit_text(
        f"✅ Аккаунт ID {account_id} успешно удалён!",
        reply_markup=accounts_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "accounts_list")
@admin_only
async def show_accounts_list(callback: types.CallbackQuery):
    accounts = get_all_accounts()

    if not accounts:
        await callback.message.edit_text(
            "⚠️ Нет доступных аккаунтов.",
            reply_markup=None
        )
        await callback.answer()
        return

    text = "📋 <b>Список аккаунтов:</b>\n\n"
    text += f"Всего аккаунтов: {len(accounts)}\n\n"

    for account in accounts:
        status = "🟢" if not account.get("banned") else "🔴"
        text += f"{status} {account.get('username') or account.get('phone')}\n"

    await callback.message.edit_text(
        text,
        reply_markup=accounts_list_keyboard(accounts),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "accounts_import")
@admin_only
async def start_import_accounts(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ImportStates.waiting_for_zip)
    await callback.message.edit_text(
        "📦 Отправьте ZIP архив с сессиями и proxies.txt",
        reply_markup=back_to_accounts_menu()
    )
    await callback.answer()

@router.message(ImportStates.waiting_for_zip, F.document)
async def handle_zip_upload(message: types.Message, state: FSMContext):
    processing_message = None

    try:
        file = message.document
        if not file.file_name.endswith(".zip"):
            await message.answer("❌ Пожалуйста, отправьте архив .zip.")
            return

        # Отправляем сообщение о начале импорта
        processing_message = await message.answer("⏳ Идёт импорт аккаунтов...\nПожалуйста, подождите...")

        temp_dir = f"/tmp/uploads/{message.from_user.id}/"
        os.makedirs(temp_dir, exist_ok=True)

        file_path = os.path.join(temp_dir, file.file_name)
        await message.bot.download(file, destination=file_path)

        # Импортируем аккаунты
        await import_accounts_from_zip(message, file_path, temp_dir)

        await state.clear()

        # После лога кнопка "Назад"
        back_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="accounts_list")]
            ]
        )
        await message.answer("Выберите дальнейшее действие:", reply_markup=back_keyboard)

    except Exception as e:
        print(f"❌ Ошибка в handle_zip_upload: {e}")
        import traceback
        traceback.print_exc()
        await message.answer("❌ Произошла ошибка при обработке архива.")

    finally:
        if processing_message:
            try:
                await processing_message.delete()
            except Exception:
                pass  # если вдруг сообщение уже удалено

        try:
            await message.delete()  # Удаляем исходное сообщение с файлом
        except Exception:
            pass

@router.callback_query(F.data.startswith("rebind_proxy_"))
@admin_only
async def rebind_proxy_menu(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[2])

    proxies = get_all_proxies()
    if not proxies:
        await callback.answer("⚠️ Нет доступных прокси для выбора.", show_alert=True)
        return

    keyboard = []

    for proxy in proxies:
        # Скрываем плохие прокси
        if proxy.get("status") == "bad":
            continue  # Пропускаем этот прокси и идём дальше

        accounts_count = count_accounts_using_proxy(
            proxy["host"],
            proxy["port"],
            proxy.get("username"),
            proxy.get("password")
        )

        # Статус прокси для кнопки
        if proxy.get("status") == "working":
            status_emoji = "✅"
        else:
            status_emoji = "❔"  # unknown или нет статуса

        button_text = f"{status_emoji} {proxy['host']}:{proxy['port']} ({accounts_count} акк.)"

        keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_proxy_{account_id}_{proxy['id']}"
            )
        ])

    # Если не осталось ни одного доступного прокси
    if not keyboard:
        await callback.message.edit_text(
            "⚠️ Нет доступных рабочих прокси для перепривязки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к аккаунту", callback_data=f"back_to_account_{account_id}")]
            ])
        )
        return

    # Кнопка "Назад к аккаунту"
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад к аккаунту",
            callback_data=f"back_to_account_{account_id}"
        )
    ])

    await callback.message.edit_text(
        "🌐 Выберите новый прокси для аккаунта:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("select_proxy_"))
@admin_only
async def select_proxy_for_account(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    proxy_id = int(parts[3])

    proxy = get_proxy_by_id(proxy_id)
    if not proxy:
        await callback.answer("⚠️ Прокси не найден.", show_alert=True)
        return

    account = get_account_by_id(account_id)
    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    # Проверяем — не тот ли уже прокси привязан
    if (
        account.get("proxy_host") == proxy["host"]
        and account.get("proxy_port") == proxy["port"]
        and account.get("proxy_username") == proxy.get("username")
        and account.get("proxy_password") == proxy.get("password")
    ):
        await callback.answer("⚠️ Этот прокси уже привязан к аккаунту.", show_alert=True)
        return

    # Обновляем прокси у аккаунта
    update_account_proxy(
        account_id,
        proxy["host"],
        proxy["port"],
        proxy.get("username"),
        proxy.get("password")
    )

    await callback.answer("✅ Прокси успешно перепривязан!", show_alert=True)

    # Возвращаем пользователя в карточку аккаунта
    updated_account = get_account_by_id(account_id)
    text = build_account_card(updated_account)
    await callback.message.edit_text(
        text=text,
        reply_markup=account_actions_keyboard(account_id),
        parse_mode="HTML"
    )
@router.callback_query(F.data.startswith("back_to_account_"))
@admin_only
async def back_to_account(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    account = get_account_by_id(account_id)
    if not account:
        await callback.answer("⚠️ Аккаунт не найден.", show_alert=True)
        return

    text = build_account_card(account)
    await callback.message.edit_text(
        text=text,
        reply_markup=account_actions_keyboard(account_id),
        parse_mode="HTML"
    )

from telethon.tl.types import PeerUser

@router.callback_query(F.data.startswith("get_code_"))
async def get_last_code(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[-1])
    
    account = get_account_by_id(account_id)
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return

    session_string = account.get("session_string")
    proxy = {
        "proxy_host": account.get("proxy_host"),
        "proxy_port": account.get("proxy_port"),
        "proxy_username": account.get("proxy_username"),
        "proxy_password": account.get("proxy_password"),
    } if account.get("proxy_host") else None

    from app.telegram_client import get_client
    client = await get_client(session_string, proxy)
    await client.start()
    # Получаем последнее сообщение от официального бота Telegram (user_id=777000)
    async for msg in client.iter_messages(PeerUser(777000), limit=1):
        text = msg.text or "<без текста>"
        date = msg.date.strftime('%d.%m.%Y %H:%M')
        await callback.answer()  # убрать крутилку
        await callback.message.answer(
            f"<b>Последнее служебное сообщение:</b>\n\n"
            f"<b>Дата:</b> {date}\n"
            f"<b>Текст:</b> <code>{text}</code>",
            parse_mode="HTML",
            reply_markup=ok_delete_keyboard()
        )
        break
    else:
        await callback.answer("Нет сообщений от Telegram (777000)", show_alert=True)
    await client.disconnect()

@router.callback_query(F.data == "delete_code_msg")
async def delete_code_msg(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()

# 1. Старт работы со спамботом

# --- FSM State ---
class SpamBotDialog(StatesGroup):
    waiting_for_message = State()

# --- Клавиатура генератор ---
def spambot_action_keyboard(account_id, button_texts):
    keyboard = [
        [InlineKeyboardButton(text=btn, callback_data=f"spambot_sendtext_{account_id}_{i}")]
        for i, btn in enumerate(button_texts)
    ]
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"spambot_refresh_{account_id}")])
    keyboard.append([InlineKeyboardButton(text="❌ Завершить", callback_data="spambot_close")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- Главное меню (старт работы) ---
@router.callback_query(F.data.startswith("spambot_menu_"))
async def spambot_menu(callback: types.CallbackQuery, state: FSMContext):
    print("[DEBUG] Сработал spambot_menu")
    account_id = int(callback.data.split("_")[-1])
    account = get_account_by_id(account_id)
    if not account or not account.get("session_string"):
        await callback.answer("Сессия не найдена!", show_alert=True)
        return

    # Сразу ставим state и account_id в FSM, чтобы любое следующее сообщение ловилось!
    await state.update_data(account_id=account_id)
    await state.set_state(SpamBotDialog.waiting_for_message)

    session_string = account.get("session_string")
    proxy = {
        "proxy_host": account.get("proxy_host"),
        "proxy_port": account.get("proxy_port"),
        "proxy_username": account.get("proxy_username"),
        "proxy_password": account.get("proxy_password"),
    } if account.get("proxy_host") else None

    client = await get_client(session_string, proxy)
    await client.start()
    try:
        # Очищаем диалог (если возможно)
        try:
            await client.delete_dialog("spambot")
        except Exception:
            pass

        # Стартуем заново
        await client.send_message("spambot", "/start")
        await asyncio.sleep(1.5)  # Дать боту ответить

        # Получаем новый ответ
        spambot = await client.get_entity("spambot")
        msg = (await client.get_messages(spambot, limit=1))[0]
        text = msg.message
        log_spambot_message(account_id, 'bot', text)

        # Собираем все кнопки
        button_texts = []
        if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, "text"):
                        button_texts.append(btn.text)

        markup = spambot_action_keyboard(account_id, button_texts)

        await callback.message.answer(f"📬 Сообщение от @spambot:\n\n{text}", reply_markup=markup)
    finally:
        await client.disconnect()
    await callback.answer()



# --- Клик по кнопке (эмулируем отправку текста) ---
@router.callback_query(F.data.startswith("spambot_sendtext_"))
async def spambot_sendtext(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    btn_index = int(parts[3])
    account = get_account_by_id(account_id)
    if not account or not account.get("session_string"):
        await callback.answer("Сессия не найдена!", show_alert=True)
        return
    session_string = account.get("session_string")
    proxy = {
        "proxy_host": account.get("proxy_host"),
        "proxy_port": account.get("proxy_port"),
        "proxy_username": account.get("proxy_username"),
        "proxy_password": account.get("proxy_password"),
    } if account.get("proxy_host") else None

    client = await get_client(session_string, proxy)
    await client.start()
    try:
        spambot = await client.get_entity("spambot")
        msg = (await client.get_messages(spambot, limit=1))[0]
        button_texts = []
        if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, "text"):
                        button_texts.append(btn.text)

        if btn_index < len(button_texts):
            text_to_send = button_texts[btn_index]
            await client.send_message("spambot", text_to_send)
            await asyncio.sleep(1.5)
            # Получаем новое сообщение!
            new_msg = (await client.get_messages(spambot, limit=1))[0]
            new_text = new_msg.message
            new_button_texts = []
            log_spambot_message(account_id, 'bot', new_text)
            if new_msg.reply_markup and hasattr(new_msg.reply_markup, "rows"):
                for row in new_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, "text"):
                            new_button_texts.append(btn.text)
            markup = spambot_action_keyboard(account_id, new_button_texts)
            await callback.message.answer(f"📬 Сообщение от @spambot:\n\n{new_text}", reply_markup=markup)
        else:
            await callback.answer("Кнопка не найдена!", show_alert=True)
    finally:
        await client.disconnect()


# --- Обновить диалог с ботом ---
@router.callback_query(F.data.startswith("spambot_refresh_"))
async def spambot_refresh(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[-1])
    account = get_account_by_id(account_id)
    if not account or not account.get("session_string"):
        await callback.answer("Сессия не найдена!", show_alert=True)
        return
    session_string = account.get("session_string")
    proxy = {
        "proxy_host": account.get("proxy_host"),
        "proxy_port": account.get("proxy_port"),
        "proxy_username": account.get("proxy_username"),
        "proxy_password": account.get("proxy_password"),
    } if account.get("proxy_host") else None

    client = await get_client(session_string, proxy)
    await client.start()
    try:
        spambot = await client.get_entity("spambot")
        msg = (await client.get_messages(spambot, limit=1))[0]
        text = msg.message
        button_texts = []
        if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, "text"):
                        button_texts.append(btn.text)
        markup = spambot_action_keyboard(account_id, button_texts)
        await callback.message.answer(f"📬 Сообщение от @spambot:\n\n{text}", reply_markup=markup)
    finally:
        await client.disconnect()
    await callback.answer()


# --- Ручной ввод сообщения пользователем ---
@router.message(SpamBotDialog.waiting_for_message, F.text)
async def send_text_to_spambot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    user_text = message.text
    print(f"[DEBUG] Пользователь пытается отправить текст спамботу: {user_text!r} для account_id={account_id}")
    if not account_id:
        print("[DEBUG] Нет account_id в state")
        await message.answer("❗ Не выбран аккаунт для работы со спамботом.")
        return
        
    log_spambot_message(account_id, 'user', user_text)  # ← ЛОГ
    
    account = get_account_by_id(account_id)
    if not account or not account.get("session_string"):
        print("[DEBUG] Нет сессии у аккаунта")
        await message.answer("❗ Не найдена сессия для аккаунта.")
        return
    session_string = account.get("session_string")
    proxy = {
        "proxy_host": account.get("proxy_host"),
        "proxy_port": account.get("proxy_port"),
        "proxy_username": account.get("proxy_username"),
        "proxy_password": account.get("proxy_password"),
    } if account.get("proxy_host") else None

    from app.telegram_client import get_client
    import asyncio
    client = await get_client(session_string, proxy)
    await client.start()
    try:
        print(f"[DEBUG] Клиент запущен, отправляем текст: {user_text!r} в @spambot")
        # Отправляем текст
        sent = await client.send_message("spambot", user_text)
        print(f"[DEBUG] Результат отправки: {sent}")
        await message.answer(f"✅ Сообщение отправлено в @spambot:\n<code>{user_text}</code>", parse_mode="HTML")
        # Ждём нового сообщения от спамбота
        await asyncio.sleep(2)
        spambot = await client.get_entity("spambot")
        msgs = await client.get_messages(spambot, limit=2)
        print(f"[DEBUG] Получено сообщений после отправки: {len(msgs)}")
        for idx, m in enumerate(msgs):
            print(f"[DEBUG] [#{idx}] msg.date={m.date} msg.id={m.id} msg.text={m.text!r}")
        # Блок: определяем, какое сообщение последнее (ищем первое, не совпадающее с отправленным текстом)
        new_msg = None
        for m in msgs:
            # Проверяем что это не наш echo, а реальный ответ спамбота (может быть то же самое сообщение)
            if m.text.strip() != user_text.strip():
                new_msg = m
                log_spambot_message(account_id, 'bot', new_msg.text)   # ← ЛОГ
                break
        if not new_msg:
            print("[DEBUG] Нет нового сообщения от спамбота (видимо echo или задержка)")
            new_msg = msgs[0]
            log_spambot_message(account_id, 'bot', new_msg.text)   # ← ЛОГ
        new_text = new_msg.text
        print(f"[DEBUG] Ответ спамбота: {new_text!r}")
        button_texts = []
        if getattr(new_msg, "reply_markup", None) and hasattr(new_msg.reply_markup, "rows"):
            for row in new_msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, "text"):
                        button_texts.append(btn.text)
                        print(f"[DEBUG] reply-кнопка: {btn.text!r}")
        markup = spambot_action_keyboard(account_id, button_texts)
        await message.answer(f"📬 Сообщение от @spambot:\n\n{new_text}", reply_markup=markup)
    except Exception as ex:
        import traceback
        print(f"[ERROR] Ошибка при отправке сообщения спамботу: {ex}")
        traceback.print_exc()
        await message.answer(f"❗ Ошибка при отправке: {ex}")
    finally:
        await client.disconnect()


def ok_delete_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❎ ОК (удалить сообщение)", callback_data="delete_log_msg")]
        ]
    )

@router.callback_query(F.data.startswith("spambot_log_"))
async def show_spambot_log(callback: types.CallbackQuery):
    account_id = int(callback.data.split("_")[-1])
    logs = get_spambot_logs_for_account(account_id)
    if not logs:
        await callback.answer("Лог пуст.", show_alert=True)
        return

    text = "<b>Лог общения со спамботом:</b>\n"
    start = logs[0]['timestamp'].strftime("%d.%m.%Y %H:%M")
    text += f"📅 Диалог начат: <b>{start}</b>\n\n"
    for entry in logs:
        ts = entry['timestamp'].strftime("%H:%M")
        author = "👤Вы" if entry['from_who'] == "user" else "🤖Спамбобот"
        msg = entry['message'].replace("<", "&lt;").replace(">", "&gt;")
        text += f"<b>{ts} {author}:</b> {msg}\n"

    # Если длинно — отправляем как файл с кнопкой
    if len(text) > 4000:
        import tempfile
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write(text)
            file_path = f.name
        await callback.message.answer_document(
            FSInputFile(file_path),
            caption="Полный лог общения",
            reply_markup=ok_delete_keyboard()
        )
    else:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=ok_delete_keyboard()
        )
    await callback.answer()

# Хендлер для удаления сообщения по кнопке "ОК"
@router.callback_query(F.data == "delete_log_msg")
async def delete_log_msg(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# --- Завершить работу ---
@router.callback_query(F.data == "spambot_close")
async def spambot_close(callback: types.CallbackQuery):
    await callback.message.edit_text("✅ Сеанс работы со спамботом завершён.")
    await callback.answer()




FROZEN_MARKERS = ("FROZEN_", "FROZEN_METHOD_INVALID")


# ===== helpers =====

from telethon.errors import RPCError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.account import UpdateUsernameRequest

FROZEN_MARKERS = ("FROZEN_", "FROZEN_METHOD_INVALID")

async def _safe_wait(coro, timeout: float, label: str, dbg: list | None = None):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception as e:
        msg = f"{e.__class__.__name__}: {e}"
        if dbg is not None:
            dbg.append(f"[{label}] {msg}")
        raise

async def _is_profile_frozen_without_full(client, me) -> tuple[bool, str]:
    """
    Детект 'заморозки' без GetFullUserRequest:
      1) Если me.deleted или 'Deleted Account' -> frozen.
      2) Если есть username: UpdateUsernameRequest(me.username) (no-op) — FROZEN_* => frozen.
      3) Всегда: UpdateProfileRequest(first_name=me.first_name or '', last_name=me.last_name or '') — FROZEN_* => frozen.
    Иначе считаем не frozen.
    """
    if getattr(me, "deleted", False) or (me.first_name == "Deleted Account"):
        return True, "deleted_profile"

    # 2) ping username (если есть)
    if getattr(me, "username", None):
        try:
            # no-op: просим установить тот же username
            await client(UpdateUsernameRequest(me.username))
        except RPCError as e:
            s = f"{e.__class__.__name__}: {e}"
            if any(tok in s for tok in FROZEN_MARKERS):
                return True, s
            # USERNAME_NOT_MODIFIED и пр. — не фриз, игнорируем

    # 3) ping profile (no-op)
    try:
        await client(UpdateProfileRequest(
            first_name=me.first_name or "",
            last_name=me.last_name or ""
        ))
    except RPCError as e:
        s = f"{e.__class__.__name__}: {e}"
        if any(tok in s for tok in FROZEN_MARKERS):
            return True, s
        # прочие ошибки не считаем фризом

    return False, "profile_writable"



# ===== ROUTE =====

@router.callback_query(F.data == "update_all_profiles")
@admin_only
async def check_all_accounts(callback: CallbackQuery):
    print("🚀 Начало проверки всех аккаунтов")
    bot = Bot(token=BOT_TOKEN)

    accounts = get_all_accounts()
    print(f"🔍 Найдено аккаунтов: {len(accounts)}")

    if not accounts:
        await callback.answer("⚠️ Аккаунты не найдены.", show_alert=True)
        return

    await callback.answer("Проверка запущена. Ожидайте отчёт!")

    try:
        await callback.message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение: {e}")

    progress_message = await bot.send_message(
        chat_id=callback.from_user.id,
        text="⏳ Задача выполняется...\n📄 По завершению вам будет отправлен лог.",
        parse_mode="HTML",
    )

    await asyncio.sleep(1)
    await bot.send_message(
        chat_id=callback.from_user.id,
        text="📋 Пока вы ожидаете, можете просмотреть список аккаунтов:",
        reply_markup=accounts_menu_keyboard(),
        parse_mode="HTML",
    )

    stats = {k: 0 for k in ["OK", "FROZEN", "NEEDS_ATTENTION", "UNKNOWN", "BANNED", "PROXY_ERROR", "ERROR"]}
    per_account_lines = []  # подробный лог

    async def process_account(account):
        acc_id = account["id"]
        phone = account.get("phone")
        session_string = account.get("session_string") or ""
        dbg = []

        proxy = None
        if account.get("proxy_host"):
            proxy = {
                "proxy_host": account.get("proxy_host"),
                "proxy_port": account.get("proxy_port"),
                "proxy_username": account.get("proxy_username"),
                "proxy_password": account.get("proxy_password"),
            }

        status = "UNKNOWN"
        detail = ""

        try:
            client = await get_client(session_string, proxy)

            # connect + auth
            await _safe_wait(client.connect(), 12, "connect", dbg)
            authed = await _safe_wait(client.is_user_authorized(), 8, "is_user_authorized", dbg)
            if not authed:
                update_account_status_to_needs_login(acc_id)
                status, detail = "NEEDS_ATTENTION", "not_authorized"
                return status, detail

            # только get_me(), НИКАКОГО GetFullUserRequest
            me = await _safe_wait(client.get_me(), 10, "get_me", dbg)

            # детект freeze без FullUser
            frozen, reason = await _is_profile_frozen_without_full(client, me)

            # инфо в БД (about ставим "-" — можно сохранить прежнее, если тянешь его из БД)
            update_account_info(
                acc_id,
                username=me.username or None,
                first_name=me.first_name or "-",
                last_name=me.last_name or "-",
                about="-"
            )

            if frozen:
                update_account_status_to_frozen(acc_id)
                status, detail = "FROZEN", reason
            else:
                update_account_status_to_active(acc_id)
                status, detail = "OK", "active"

            return status, detail

        except Exception as e:
            update_account_status_to_unknown(acc_id)
            status, detail = "UNKNOWN", f"{e.__class__.__name__}: {e}"
            return status, detail

        finally:
            try:
                if "client" in locals():
                    await _safe_wait(client.disconnect(), 5, "disconnect", dbg)
            except Exception:
                pass
            dbg_tail = (" | " + " ; ".join(dbg)) if dbg else ""
            per_account_lines.append(f"{acc_id}/{phone}: {status} ({detail}){dbg_tail}")


    # ограничим параллелизм
    sem = asyncio.Semaphore(6)

    async def wrapped(acc):
        async with sem:
            s, d = await asyncio.wait_for(process_account(acc), timeout=120)
            stats[s] += 1
            return s, d

    results = await asyncio.gather(*[wrapped(a) for a in accounts], return_exceptions=True)

    # формируем отчёт
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_text = f"📅 Отчёт ({ts})\n\n"
    log_text += "📊 Статистика:\n"
    for k, label in {
        "OK": "🟢 Активно",
        "FROZEN": "❄️ Заморожено",
        "NEEDS_ATTENTION": "🟡 Требует входа",
        "UNKNOWN": "⚠️ Неизвестно",
        "BANNED": "🔴 Забанено",
        "PROXY_ERROR": "🛡️ Прокси-ошибки",
        "ERROR": "❗ Ошибки",
    }.items():
        log_text += f"{label}: {stats[k]}\n"

    # подробный перечень по каждому аккаунту
    log_text += "\n📄 Подробности по аккаунтам:\n" + "\n".join(per_account_lines)

    os.makedirs("logs", exist_ok=True)
    filename = f"logs/telegram_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(log_text)

    await bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile(path=filename),
        caption="📄 Лог проверки аккаунтов",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ ОК (удалить)", callback_data="delete_log_msg")]]
        ),
    )

    try:
        await progress_message.edit_text("✅ Проверка завершена.")
        await asyncio.sleep(2)
        await progress_message.delete()
    except Exception:
        pass




@router.callback_query(F.data == "delete_log_msg")
async def delete_log_message(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# Меню удаления аккаунтов
@router.callback_query(F.data == "accounts_delete_menu")
@admin_only
async def delete_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⚠️ Выберите способ удаления аккаунтов:",
        reply_markup=delete_accounts_keyboard()
    )

# Удаление невалидных аккаунтов
@router.callback_query(F.data == "delete_invalid_accounts")
@admin_only
async def delete_invalid_accounts(callback: types.CallbackQuery):
    accounts = get_all_accounts()
    log = []

    for acc in accounts:
        if acc["status"] in ["freeze", "banned"]:
            delete_account_by_id(acc["id"])
            log.append(f"🚫 Удалён аккаунт: {acc['username'] or acc['phone']}")

    if not log:
        log.append("✅ Нет невалидных аккаунтов для удаления.")

    # Создаем временный txt-файл
    log_filename = f"/tmp/deleted_accounts_{uuid.uuid4().hex}.txt"
    with open(log_filename, "w", encoding="utf-8") as file:
        file.write("\n".join(log))

    # Кнопка "OK" для удаления сообщения
    ok_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ OK", callback_data="delete_log_msg")]
    ])

    # Отправляем лог в виде файла
    await callback.message.answer_document(
        FSInputFile(log_filename),
        caption="📝 Лог удалённых аккаунтов",
        reply_markup=ok_button
    )

    # Удаляем временный файл
    os.remove(log_filename)

    await callback.answer("Удаление завершено.", show_alert=True)


# Выбор аккаунтов для удаления
@router.callback_query(F.data == "select_accounts_to_delete")
@admin_only
async def select_accounts_to_delete(callback: types.CallbackQuery, state):
    accounts = get_all_accounts()
    await state.set_state("selecting_accounts_to_delete")
    await state.update_data(selected_accounts=[])
    await callback.message.edit_text(
        "🗑️ Выберите аккаунты для удаления:",
        reply_markup=select_accounts_keyboard(accounts)
    )

# Переключение выбора аккаунтов
@router.callback_query(StateFilter("selecting_accounts_to_delete"), F.data.startswith("toggle_account_"))
@admin_only
async def toggle_account_to_delete(callback: types.CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])

    if account_id in selected_ids:
        selected_ids.remove(account_id)
    else:
        selected_ids.append(account_id)

    await state.update_data(selected_accounts=selected_ids)

    accounts = get_all_accounts()

    await callback.message.edit_text(
        "🗑️ Выберите аккаунты для удаления:",
        reply_markup=select_accounts_keyboard(accounts, selected_ids)
    )

# Подтверждение удаления выбранных аккаунтов
@router.callback_query(StateFilter("selecting_accounts_to_delete"), F.data == "proceed_after_selecting_accounts")
@admin_only
async def proceed_delete_selected_accounts(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])

    if not selected_ids:
        await callback.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return

    log = []
    for acc_id in selected_ids:
        acc = get_account_by_id(acc_id)
        delete_account_by_id(acc_id)
        log.append(f"🚫 Удалён аккаунт: {acc['username'] or acc['phone']}")

    log_message = "\n".join(log)
    await callback.message.answer(log_message)
    await state.clear()
    await callback.answer("Аккаунты удалены.", show_alert=True)
