# keyboards/main_menu.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def start_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="👤 Аккаунты", callback_data="menu_accounts"),
            InlineKeyboardButton(text="🌐 Прокси", callback_data="menu_proxies"),
        ],
        [
            InlineKeyboardButton(text="➕ Создать задачу", callback_data="menu_tasks"),
            InlineKeyboardButton(text="📋 Выполнение задач", callback_data="menu_task_execution"),
        ],
        [
            #InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
            InlineKeyboardButton(text="🔑 Ключи Api", callback_data="menu_stats"),
        ],
#        [
#           InlineKeyboardButton(text="🛟 Поддержка", callback_data="menu_support"),
#        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
