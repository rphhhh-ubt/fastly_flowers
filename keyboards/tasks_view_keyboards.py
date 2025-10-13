# keyboards/tasks_view_keyboards.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def tasks_type_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Массовое обновление профиля", callback_data="tasktype_bulk_profile_update"),
        ],
        
        [
            InlineKeyboardButton(text="🧹 Удаление всех каналов", callback_data="tasktype_delete_channels"),
        ],
        
        [
            InlineKeyboardButton(text="🆕 Создание и установка каналов", callback_data="tasktype_create_and_set_channel"),
        ],
        [
            InlineKeyboardButton(text="📋 Переавторизация — задачи", callback_data="task_reauth_list:1")
        ],
        [
            InlineKeyboardButton(text="🔐 2FA — список задач", callback_data="menu_twofa_tasks"),
        ],
        [
            InlineKeyboardButton(text="❤️ Лайкинг постов", callback_data="menu_like_tasks"),
        ],
        [
           InlineKeyboardButton(text="💬 Проверка комментариев", callback_data="tasktype_check_comments"),
        ],
        [
            InlineKeyboardButton(text="🔎Массовый парсинг групп", callback_data="tasktype_mass_search"),
        ],
        [
            InlineKeyboardButton(text="👥 Проверка групп (карточки)", callback_data="tasktype_check_groups"),
        ],
        

        [   
            InlineKeyboardButton(text="🚀 Вступить в группы", callback_data="menu_join_groups_tasks"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="menu_main"),
        ]
        
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
