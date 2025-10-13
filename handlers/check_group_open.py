from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.check_access import admin_only
from utils.check_groups import check_groups_members_filter

router = Router()

class CheckGroupsStates(StatesGroup):
    waiting_for_links = State()
    waiting_for_filter = State()

@router.message(Command("checkgroups"))
@admin_only
async def cmd_checkgroups(message: types.Message, state: FSMContext):
    await message.answer("📋 Пришли список групп (по одной ссылке t.me/... в строке) или .txt файл.")
    await state.set_state(CheckGroupsStates.waiting_for_links)

@router.message(CheckGroupsStates.waiting_for_links)
@admin_only
async def handle_group_links(message: types.Message, state: FSMContext):
    links = []
    if message.document:
        file = await message.document.download()
        with open(file.path, "r", encoding="utf-8") as f:
            links = [line.strip() for line in f if line.strip()]
    else:
        links = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not links:
        await message.answer("⚠️ Не найдено ни одной ссылки.")
        return
    await state.update_data(links=links)
    await message.answer("✏️ Введи минимальное число участников (например, 20000):")
    await state.set_state(CheckGroupsStates.waiting_for_filter)

@router.message(CheckGroupsStates.waiting_for_filter)
@admin_only
async def handle_min_members(message: types.Message, state: FSMContext):
    try:
        min_members = int(message.text.strip())
        if min_members <= 0:
            raise ValueError
    except Exception:
        await message.answer("❗ Введи корректное число участников (например, 20000):")
        return
    data = await state.get_data()
    links = data["links"]
    await state.clear()
    good, small, bad, errors = await check_groups_members_filter(links, message, min_members=min_members, accounts=accounts, task_id=task_id)
    await message.answer(f"✅ Групп >= {min_members}: {len(good)}\n❌ Групп меньше: {len(small)}\n🚫 Не найдены/в бане: {len(bad)}")

    if good:
        await message.answer_document(types.BufferedInputFile(
            bytes("\n".join(good), "utf-8"),
            filename="big_groups.txt"
        ))
    if small:
        await message.answer_document(types.BufferedInputFile(
            bytes("\n".join(small), "utf-8"),
            filename="small_groups.txt"
        ))
    if bad:
        await message.answer_document(types.BufferedInputFile(
            bytes("\n".join(bad), "utf-8"),
            filename="bad_groups.txt"
        ))
    if errors:
        await message.answer_document(types.BufferedInputFile(
            bytes("\n".join(errors), "utf-8"),
            filename="errors.txt"
        ))
