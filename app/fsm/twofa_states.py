from aiogram.fsm.state import StatesGroup, State

class TwoFAStates(StatesGroup):
    SELECT_ACCOUNTS = State()
    CHOOSE_MODE     = State()  # new | replace
    ASK_OLD         = State()
    ASK_NEW         = State()
    ASK_KILL        = State()  # yes | no
    CONFIRM         = State()
    RUNNING         = State()
    RUNNING         = State()