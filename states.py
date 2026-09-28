from aiogram.fsm.state import State, StatesGroup
class AccountFlow(StatesGroup):
    phone=State(); code=State(); password=State(); title=State()
class DestFlow(StatesGroup):
    account=State(); chat=State()
class PostFlow(StatesGroup):
    content=State(); account=State(); destinations=State(); when=State(); repeat=State()
