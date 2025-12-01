import logging
import os
from aiogram import Router, F, Bot
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.services import task_parser, weeek_service
from app.services.task_parser import client

router = Router()


# Определяем состояния для нашего агента
class TaskCreation(StatesGroup):
    AwaitingDeadline = State()
    AwaitingAssignee = State()


async def create_task_from_state(message: Message, state: FSMContext):
    """Собирает все данные из состояния и создает задачу."""
    data = await state.get_data()
    await state.clear()

    title = data.get("title")
    deadline = data.get("deadline")
    assignee = data.get("assignee")

    await message.answer(
        f"Отлично, все данные собраны:\n"
        f"<b>Название:</b> {title}\n"
        f"<b>Дедлайн:</b> {deadline or 'не указан'}\n"
        f"<b>Ответственный:</b> {assignee or 'не указан'}\n\n"
        f"Создаю задачу в Weeek..."
    )

    try:
        result = await weeek_service.create_task(title=title, deadline=deadline, assignee=assignee)
        if result.get("status") == "success":
            await message.answer(f"✅ Задача «{title}» успешно создана!")
        else:
            await message.answer("❌ Произошла ошибка при создании задачи в Weeek.")
    except Exception as e:
        logging.error(f"Ошибка в create_task_from_state: {e}")
        await message.answer("Упс, что-то пошло не так. Попробуйте еще раз.")


async def process_task_text(text: str, message: Message, bot: Bot, state: FSMContext):
    """Анализирует текст, начинает диалог, если нужно, или сразу создает задачу."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    
    try:
        parsed_data = await task_parser.parse_task_text(text)
        title = parsed_data.get("title")

        if not title:
            await message.answer("Не удалось определить название задачи. Попробуйте сформулировать по-другому.")
            return

        # Сохраняем все, что удалось распарсить
        await state.update_data(
            title=title,
            deadline=parsed_data.get("deadline"),
            assignee=parsed_data.get("assignee")
        )

        # Проверяем, чего не хватает, и задаем вопросы
        if not parsed_data.get("deadline"):
            await message.answer("Уточните, пожалуйста, дедлайн для задачи. (например, 'завтра в 18:00')")
            await state.set_state(TaskCreation.AwaitingDeadline)
        elif not parsed_data.get("assignee"):
            await message.answer("А кто ответственный за эту задачу?")
            await state.set_state(TaskCreation.AwaitingAssignee)
        else:
            await create_task_from_state(message, state)

    except Exception as e:
        logging.error(f"Ошибка в process_task_text: {e}")
        await message.answer("🤷‍♂️ Упс, что-то пошло не так при анализе задачи. Попробуйте еще раз.")


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "отмена")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    """Отменяет текущий диалог."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активных действий для отмены.")
        return

    logging.info(f"Cancelling state {current_state} for user {message.from_user.id}")
    await state.clear()
    await message.answer("Действие отменено. Чем еще могу помочь?")


@router.message(TaskCreation.AwaitingDeadline)
async def handle_deadline(message: Message, state: FSMContext):
    """Обрабатывает ответ пользователя про дедлайн."""
    await state.update_data(deadline=message.text)
    data = await state.get_data()

    if not data.get("assignee"):
        await message.answer("Отлично. А кто ответственный?")
        await state.set_state(TaskCreation.AwaitingAssignee)
    else:
        await create_task_from_state(message, state)


@router.message(TaskCreation.AwaitingAssignee)
async def handle_assignee(message: Message, state: FSMContext):
    """Обрабатывает ответ пользователя про ответственного."""
    await state.update_data(assignee=message.text)
    await create_task_from_state(message, state)


@router.message(F.text)
async def handle_text_message(message: Message, bot: Bot, state: FSMContext):
    """Обработчик для текстовых сообщений (точка входа)."""
    await process_task_text(message.text, message, bot, state)


@router.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot, state: FSMContext):
    """Обработчик для голосовых сообщений (точка входа)."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)
    ogg_filename = f"{message.voice.file_id}.ogg"
    try:
        await bot.download(message.voice, destination=ogg_filename)
        with open(ogg_filename, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        
        text = transcript.text.strip()
        if not text:
            await message.answer("Не смог распознать речь. Попробуйте записать еще раз.")
            return
        
        await message.answer(f"Транскрибация завершена:\n\n«{text}»")
        await process_task_text(text, message, bot, state)
    except Exception as e:
        logging.error(f"Ошибка в handle_voice_message: {e}")
        await message.answer("🤷‍♂️ Упс, что-то пошло не так при обработке голоса.")
    finally:
        if os.path.exists(ogg_filename):
            os.remove(ogg_filename)
