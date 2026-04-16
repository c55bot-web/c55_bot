from aiogram.fsm.state import State, StatesGroup

class EditUser(StatesGroup):
    waiting_for_text = State()

class AdminPanel(StatesGroup):
    waiting_for_custom_poll = State()

class CustomPoll(StatesGroup):
    waiting_for_poll_data = State()

class OptionsPanel(StatesGroup):
    waiting_for_subject_text = State()

class CustomRequest(StatesGroup):
    waiting_for_request_text = State()


class ZvRelease(StatesGroup):
    waiting_custom_time_from = State()
    waiting_custom_time_to = State()
    waiting_address_text = State()
    waiting_reason_text = State()

class CustomRequestReply(StatesGroup):
    waiting_for_reply = State()

class CustomRequestResponse(StatesGroup):
    waiting_for_manual_text = State()
    waiting_for_question_text = State()


class SNEPanel(StatesGroup):
    """Окреме меню /sne — стягнення/заохочення."""
    pass  # Все через callback, стани не потрібні