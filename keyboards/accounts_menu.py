# keyboards/accounts_menu.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def accounts_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="accounts_list"),
            InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data="accounts_import"),
        ],
        [
            InlineKeyboardButton(text="🚫 Удалить аккаунт", callback_data="accounts_delete_menu"),
            InlineKeyboardButton(text="🛠️ Группы аккаунтов", callback_data="grantes_menu"),
        ],
#        [
#            InlineKeyboardButton(text="🔍 Поиск аккаунта", callback_data="accounts_search"),
#        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="menu_main"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
