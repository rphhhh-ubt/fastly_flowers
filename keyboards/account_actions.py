# keyboards/account_actions.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.db import has_spambot_log


def account_actions_keyboard(account_id: int):
    

    keyboard = [
        [
            InlineKeyboardButton(
                text="🔄 Обновить профиль",
                callback_data=f"update_profile_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🛡 Проверить спамблок",
                callback_data=f"check_spamblock_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="📩 Получить код",
                callback_data=f"get_code_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🤖 Работа со спамботом",
                callback_data=f"spambot_menu_{account_id}"
            )
        ],
    ]
    # <--- ВСТАВКА КНОПКИ ЛОГА СО СПАМБОТОМ
    if has_spambot_log(account_id):
        keyboard.append([
            InlineKeyboardButton(
                text="📝 Лог общения со спамботом",
                callback_data=f"spambot_log_{account_id}"
            )
        ])
    keyboard += [
        [
            InlineKeyboardButton(
                text="⚙️ Перепривязать прокси", 
                callback_data=f"rebind_proxy_{account_id}"
            )
        ],        
        [
            InlineKeyboardButton(
                text="🌐 Проверить прокси",
                callback_data=f"check_proxy_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🗑 Удалить аккаунт",
                callback_data=f"confirm_delete_account_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад к списку аккаунтов",
                callback_data="accounts_list"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
