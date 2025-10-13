# handlers/start.py

from aiogram import Router, types, F
from aiogram.filters import Command
from keyboards.main_menu import start_menu_keyboard
from utils.check_access import admin_only
from keyboards.back_menu import back_to_main_menu_keyboard
from keyboards.accounts_menu import accounts_menu_keyboard
from keyboards.proxy_menu import proxy_menu_keyboard
from keyboards.tasks_view_keyboards import tasks_type_keyboard
from keyboards.create_task_keyboards import create_task_type_keyboard
from handlers.delete_old_channels import delete_old_channels_handler
from handlers.channel_creation import create_channels, ChannelCreation
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram import Bot






router = Router()


@router.message(Command("start"))
@admin_only
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в панель управления!\n\nВыберите раздел:",
        reply_markup=start_menu_keyboard()
    )



# Аккаунты
@router.callback_query(F.data == "menu_accounts")
@admin_only
async def open_accounts(callback: types.CallbackQuery):
    
    await callback.message.edit_text(
        "👤 <b>Раздел аккаунтов:</b>\n\nВыберите действие ниже ⬇️",
        reply_markup=accounts_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# Прокси
@router.callback_query(F.data == "menu_proxies")
@admin_only
async def open_proxies(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🌐 Раздел прокси:\n\nПроверка и управление прокси серверами.",
        reply_markup=proxy_menu_keyboard()
    )
    await callback.answer()

# Задачи
@router.callback_query(F.data == "menu_tasks")
@admin_only
async def open_create_task(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "➕ <b>Создание новой задачи:</b>\n\nВыберите тип задачи для создания:",
        reply_markup=create_task_type_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# Статистика
@router.callback_query(F.data == "menu_stats")
@admin_only
async def open_stats(callback: types.CallbackQuery):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    def stats_menu_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Ключи API", callback_data="show_api_keys")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ])
    await callback.message.edit_text(
        "📈 Статистика:\n\nВыберите раздел:",
        reply_markup=stats_menu_keyboard()
    )


# Настройки
@router.callback_query(F.data == "menu_settings")
@admin_only
async def open_settings(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⚙️ Настройки системы:\n\nКонфигурация и параметры работы.",
        reply_markup=back_to_main_menu_keyboard()
    )
    await callback.answer()

# Поддержка
@router.callback_query(F.data == "menu_support")
@admin_only
async def open_support(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🛟 Поддержка:\n\nЕсли у вас есть вопросы или нужна помощь — обратитесь в поддержку.",
        reply_markup=back_to_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "menu_main")
@admin_only
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer(cache_time=1)
    await callback.message.edit_text(
        "👋 Добро пожаловать в панель управления!\n\nВыберите раздел:",
        reply_markup=start_menu_keyboard()
    )
    

@router.callback_query(F.data == "menu_accounts")
@admin_only
async def open_accounts(callback: types.CallbackQuery):
    print(f"Callback data: {callback.data}")
    await callback.message.answer("Ты нажал Аккаунты!")
    await callback.answer()
    await callback.message.edit_text(
        "👤 <b>Раздел аккаунтов:</b>\n\nВыберите действие ниже ⬇️",
        reply_markup=accounts_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "accounts_list")
@admin_only
async def show_accounts_list(callback: types.CallbackQuery):
    from app.db import get_all_accounts  # функция получения всех аккаунтов
    from keyboards.accounts_list import accounts_list_keyboard

    accounts = get_all_accounts()

    if not accounts:
        await callback.message.edit_text(
            "⚠️ Нет доступных аккаунтов.",
            reply_markup=accounts_menu_keyboard()
        )
        await callback.answer()
        return

    text = "📋 Список аккаунтов:\n\n"
    text += f"Всего аккаунтов: {len(accounts)}\n\n"
    text += "Нажмите на аккаунт для подробностей."

    await callback.message.edit_text(
        text,
        reply_markup=accounts_list_keyboard(accounts)
    )
    await callback.answer()

@router.callback_query(F.data == "menu_task_execution")
@admin_only
async def open_task_execution(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📋 <b>Выполнение задач:</b>\n\nВыберите тип задач для просмотра:",
        reply_markup=tasks_type_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# Запуск FSM задачи создания каналов
@router.callback_query(F.data == "task_create_personal_channel")
@admin_only
async def handle_task_create_personal_channel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.set_state(ChannelCreation.waiting_for_titles)
    await callback.message.answer("📥 Пришлите названия каналов (текст или .txt)")
