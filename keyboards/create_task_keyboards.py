from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def create_task_type_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🎀 Массовое обновление профиля", callback_data="start_bulk_profile_update"),
        ],
        [
            InlineKeyboardButton(text="🧹 Удалить все каналы", callback_data="task_delete_channels_del"),
        ],
        [
            InlineKeyboardButton(text="📡 Создать и установить канал", callback_data="task_create_channels"),
        ],

        [
            InlineKeyboardButton(text="🔑 Переавторизация аккаунтов", callback_data="task_reauth_start")
        ],
        [
            InlineKeyboardButton(text="🔐 2FA (установить/сменить)", callback_data="tasktype_twofa"),
        ],
        
        [
            InlineKeyboardButton(text="❤️ Реакции в комментариях", callback_data="start_like_comments_task")
        ],
        [
            InlineKeyboardButton(text="🚀 Старт проверки комментариев", callback_data="menu_check_comments"),
        ],
        [
             InlineKeyboardButton(text="🔎 Массовый парсинг групп", callback_data="mass_search"),
        ],
        [
            InlineKeyboardButton(text="⛱ Проверка групп", callback_data="start_check_groups_task"),
        ],

        [
            InlineKeyboardButton(text="🚀 Вступить в группы", callback_data="start_join_groups_task"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="menu_main"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
