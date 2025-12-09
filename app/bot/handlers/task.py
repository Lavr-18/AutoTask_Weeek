import logging
import os
from aiogram import Router, F, Bot
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from typing import List, Dict, Any, Optional

from app.services import task_parser
from app.services.weeek_service import create_weeek_task, _weeek_client
from app.services.task_parser import client as openai_client

router = Router()


# Определяем состояния для нашего агента
class TaskCreation(StatesGroup):
    AwaitingDeadline = State()
    AwaitingAssignee = State()
    AwaitingProjectSelection = State()
    AwaitingBoardSelection = State()
    AwaitingAssigneeSelection = State()


async def find_assignee_by_name(assignee_name_input: str, members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ищет членов команды по имени, учитывая частичные совпадения в firstName и lastName.
    Возвращает список подходящих членов.
    """
    # Убедимся, что assignee_name_input является строкой, прежде чем вызывать .lower()
    if not isinstance(assignee_name_input, str):
        logging.warning(f"find_assignee_by_name received non-string input: {assignee_name_input} (type: {type(assignee_name_input)})")
        return []

    assignee_name_input_lower = assignee_name_input.lower()
    found_members = []

    for member in members:
        # Добавлен отладочный лог для проверки каждого члена
        logging.debug(f"find_assignee_by_name: Processing member: {member}")
        
        if not isinstance(member, dict):
            logging.warning(f"find_assignee_by_name: Encountered non-dict member: {member} (type: {type(member)})")
            continue # Пропускаем невалидные элементы

        # Исправлено: используем (value or '') для обработки None, если get возвращает None
        # Это должно было быть исправлено ранее, но убедимся, что оно здесь
        first_name = (member.get('firstName') or '').lower()
        last_name = (member.get('lastName') or '').lower()
        email = (member.get('email') or '').lower()
        
        # Проверяем на полное совпадение имени или фамилии
        if assignee_name_input_lower == first_name or \
           assignee_name_input_lower == last_name:
            found_members.append(member)
            continue

        # Проверяем на частичное совпадение в имени или фамилии
        if assignee_name_input_lower in first_name or \
           assignee_name_input_lower in last_name:
            found_members.append(member)
            continue
        
        # Проверяем на полное совпадение полного имени (firstName lastName или lastName firstName)
        full_name_f_l = f"{first_name} {last_name}".strip()
        full_name_l_f = f"{last_name} {first_name}".strip()
        if assignee_name_input_lower == full_name_f_l or \
           assignee_name_input_lower == full_name_l_f:
            found_members.append(member)
            continue

        # Проверяем на частичное совпадение в полном имени
        if assignee_name_input_lower in full_name_f_l or \
           assignee_name_input_lower in full_name_l_f:
            found_members.append(member)
            continue

        # Проверяем на совпадение с email
        if assignee_name_input_lower == email:
            found_members.append(member)
            continue

    # Удаляем дубликаты, если один и тот же член попал по разным критериям
    unique_members = []
    seen_ids = set()
    for member in found_members:
        if member["id"] not in seen_ids:
            unique_members.append(member)
            seen_ids.add(member["id"])
            
    return unique_members


async def create_task_from_state(message: Message, state: FSMContext):
    """Собирает все данные из состояния и создает задачу."""
    data = await state.get_data()
    await state.clear()

    title = data.get("title")
    deadline = data.get("deadline")
    assignee_id = data.get("assignee_id")
    project_id = data.get("project_id")
    board_id = data.get("board_id")
    
    if project_id is None or board_id is None:
        await message.answer("Не удалось определить проект или доску для задачи. Пожалуйста, попробуйте еще раз.")
        return

    await message.answer(
        f"Отлично, все данные собраны:\n"
        f"<b>Название:</b> {title}\n"
        f"<b>Дедлайн:</b> {deadline or 'не указан'}\n"
        f"<b>Ответственный ID:</b> {assignee_id or 'не указан'}\n"
        f"<b>Проект ID:</b> {project_id}\n"
        f"<b>Доска ID:</b> {board_id}\n\n"
        f"Создаю задачу в Weeek..."
    )

    try:
        result = await create_weeek_task(
            title=title,
            description=None,
            deadline=deadline,
            assignee_id=assignee_id,
            project_id=project_id,
            board_id=board_id
        )
        if result.get("status") == "success":
            await message.answer(f"✅ Задача «{title}» успешно создана!")
        else:
            await message.answer(f"❌ Произошла ошибка при создании задачи в Weeek: {result.get('message', 'Неизвестная ошибка')}")
    except Exception as e:
        logging.error(f"Ошибка в create_task_from_state: {e}", exc_info=True)
        await message.answer("Упс, что-то пошло не так. Попробуйте еще раз.")


async def process_task_text(text: str, message: Message, bot: Bot, state: FSMContext):
    """Анализирует текст, начинает диалог, если нужно, или сразу создает задачу."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    
    try:
        logging.debug(f"process_task_text: Input text: {text}")
        parsed_data = await task_parser.parse_task_text(text)
        logging.debug(f"process_task_text: Parsed data from task_parser: {parsed_data}")

        title = parsed_data.get("title")
        if not title:
            await message.answer("Не удалось определить название задачи. Попробуйте сформулировать по-другому.")
            return

        # Sanitize parsed data to ensure they are strings or None
        assignee_name_input = None
        if parsed_data.get("assignee") is not None:
            try:
                assignee_name_input = str(parsed_data["assignee"])
            except Exception as e:
                logging.error(f"Error converting assignee to string: {parsed_data['assignee']} - {e}", exc_info=True)

        project_name_input = None
        if parsed_data.get("project_name") is not None:
            try:
                project_name_input = str(parsed_data["project_name"])
            except Exception as e:
                logging.error(f"Error converting project_name to string: {parsed_data['project_name']} - {e}", exc_info=True)

        board_name_input = None
        if parsed_data.get("board_name") is not None:
            try:
                board_name_input = str(parsed_data["board_name"])
            except Exception as e:
                logging.error(f"Error converting board_name to string: {parsed_data['board_name']} - {e}", exc_info=True)

        await state.update_data(
            title=title,
            deadline=parsed_data.get("deadline"), # Deadline can be None or string, no .lower() on it
            assignee_name_input=assignee_name_input,
            project_name=project_name_input,
            board_name=board_name_input
        )
        logging.debug("process_task_text: State updated. Calling check_and_ask_for_missing_info.")
        await check_and_ask_for_missing_info(message, state)

    except Exception as e:
        logging.error(f"Ошибка в process_task_text: {e}", exc_info=True) # Add exc_info=True for full traceback
        await message.answer("🤷‍♂️ Упс, что-то пошло не так при анализе задачи.")


async def check_and_ask_for_missing_info(message: Message, state: FSMContext):
    """Проверяет, какие данные отсутствуют, и запрашивает их у пользователя."""
    data = await state.get_data()
    
    # 1. Проверяем дедлайн
    if not data.get("deadline"):
        await message.answer("Уточните, пожалуйста, дедлайн для задачи. (например, 'завтра в 18:00')")
        await state.set_state(TaskCreation.AwaitingDeadline)
        return

    # 2. Проверяем ответственного
    if not data.get("assignee_id"): # Если ID ответственного еще нет
        members_response = await _weeek_client.get_workspace_members()
        members = members_response.get("members", [])
        
        if not members:
            await message.answer("Не удалось получить список членов команды из Weeek. Не могу назначить ответственного.")
            await state.update_data(assignee_id=None) # Устанавливаем None, чтобы пройти проверку
        else:
            assignee_name_input = data.get("assignee_name_input")
            if assignee_name_input:
                found_assignees = await find_assignee_by_name(assignee_name_input, members)
                
                if len(found_assignees) == 1:
                    await state.update_data(assignee_id=found_assignees[0]["id"])
                    logging.info(f"Resolved assignee '{assignee_name_input}' to ID: {found_assignees[0]['id']}")
                elif len(found_assignees) > 1:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(), callback_data=f"select_assignee_{m['id']}")] for m in found_assignees
                    ])
                    await message.answer(f"Найдено несколько пользователей по запросу '{assignee_name_input}'. Пожалуйста, уточните:", reply_markup=keyboard)
                    await state.set_state(TaskCreation.AwaitingAssigneeSelection)
                    return
                else:
                    await message.answer(f"Не удалось найти ответственного '{assignee_name_input}'. Пожалуйста, выберите из списка или введите имя/email вручную:")
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(), callback_data=f"select_assignee_{m['id']}")] for m in members
                    ])
                    await message.answer("Все члены команды:", reply_markup=keyboard)
                    await state.set_state(TaskCreation.AwaitingAssigneeSelection)
                    return
            else: # Если имя ответственного не было распарсено
                await message.answer("А кто ответственный за эту задачу? Пожалуйста, выберите из списка или введите имя/email вручную:")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(), callback_data=f"select_assignee_{m['id']}")] for m in members
                ])
                await message.answer("Все члены команды:", reply_markup=keyboard)
                await state.set_state(TaskCreation.AwaitingAssigneeSelection)
                return
    
    # 3. Проверяем проект
    if not data.get("project_id"):
        projects_response = await _weeek_client.get_projects()
        projects = projects_response.get("projects", [])
        
        if not projects:
            await message.answer("Не удалось получить список проектов из Weeek. Пожалуйста, попробуйте позже.")
            await state.clear()
            return
        
        selected_project = None
        project_name_from_state = data.get("project_name")
        # Добавляем явную проверку типа перед вызовом .lower()
        if isinstance(project_name_from_state, str):
            for project in projects:
                if project.get("title", "").lower() == project_name_from_state.lower():
                    selected_project = project
                    break
            if selected_project:
                await state.update_data(project_id=selected_project["id"])
                logging.info(f"Resolved project '{project_name_from_state}' to ID: {selected_project['id']}")
            else:
                await message.answer(f"Проект '{project_name_from_state}' не найден. Пожалуйста, выберите проект из списка:")
        else: # Если project_name_from_state не строка (т.е. None)
            await message.answer("Пожалуйста, выберите проект для задачи:")
        
        if not selected_project:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=p["title"], callback_data=f"select_project_{p['id']}")] for p in projects
            ])
            await message.answer("Выберите проект:", reply_markup=keyboard)
            await state.set_state(TaskCreation.AwaitingProjectSelection)
            return

    # 4. Проверяем доску
    if not data.get("board_id"):
        projects_response = await _weeek_client.get_projects() # Получаем проекты снова, чтобы найти название проекта по ID
        projects = projects_response.get("projects", [])
        current_project_name = "Неизвестный проект"
        for p in projects:
            if p["id"] == data["project_id"]:
                current_project_name = p["title"]
                break

        boards_response = await _weeek_client.get_boards(project_id=data["project_id"])
        boards = boards_response.get("boards", [])

        if not boards:
            await message.answer(f"Не удалось получить список досок для проекта '{current_project_name}'. Пожалуйста, попробуйте позже.")
            await state.clear()
            return

        selected_board = None
        board_name_from_state = data.get("board_name")
        # Добавляем явную проверку типа перед вызовом .lower()
        if isinstance(board_name_from_state, str):
            for board in boards:
                if board.get("name", "").lower() == board_name_from_state.lower():
                    selected_board = board
                    break
            if selected_board:
                await state.update_data(board_id=selected_board["id"])
                logging.info(f"Resolved board '{board_name_from_state}' to ID: {selected_board['id']}")
            else:
                await message.answer(f"Доска '{board_name_from_state}' не найдена в проекте '{current_project_name}'. Пожалуйста, выберите доску из списка:")
        else: # Если board_name_from_state не строка (т.е. None)
            await message.answer(f"Пожалуйста, выберите доску для задачи в проекте '{current_project_name}':")
        
        if not selected_board:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=b["name"], callback_data=f"select_board_{b['id']}")] for b in boards
            ])
            await message.answer("Выберите доску:", reply_markup=keyboard)
            await state.set_state(TaskCreation.AwaitingBoardSelection)
            return
    
    # Если все данные собраны, создаем задачу
    await create_task_from_state(message, state)


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
    await check_and_ask_for_missing_info(message, state)


@router.message(TaskCreation.AwaitingAssignee)
async def handle_assignee_text(message: Message, state: FSMContext):
    """Обрабатывает текстовый ответ пользователя про ответственного."""
    assignee_name_input = message.text
    members_response = await _weeek_client.get_workspace_members()
    members = members_response.get("members", [])
    
    if not members:
        await message.answer("Не удалось получить список членов команды из Weeek. Не могу назначить ответственного.")
        await state.update_data(assignee_id=None) # Продолжаем без ответственного
        await check_and_ask_for_missing_info(message, state)
        return

    found_assignees = await find_assignee_by_name(assignee_name_input, members)
    
    if len(found_assignees) == 1:
        await state.update_data(assignee_id=found_assignees[0]["id"])
        logging.info(f"Resolved assignee '{assignee_name_input}' to ID: {found_assignees[0]['id']}")
        await check_and_ask_for_missing_info(message, state)
    elif len(found_assignees) > 1:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(), callback_data=f"select_assignee_{m['id']}")] for m in found_assignees
        ])
        await message.answer(f"Найдено несколько пользователей по запросу '{assignee_name_input}'. Пожалуйста, уточните:", reply_markup=keyboard)
        await state.set_state(TaskCreation.AwaitingAssigneeSelection)
    else:
        await message.answer(f"Ответственный '{assignee_name_input}' не найден. Пожалуйста, попробуйте еще раз или выберите из списка:")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(), callback_data=f"select_assignee_{m['id']}")] for m in members
        ])
        await message.answer("Все члены команды:", reply_markup=keyboard)
        await state.set_state(TaskCreation.AwaitingAssigneeSelection)


@router.callback_query(F.data.startswith("select_project_"), TaskCreation.AwaitingProjectSelection)
async def handle_project_selection(callback_query: CallbackQuery, state: FSMContext):
    project_id = int(callback_query.data.split("_")[2])
    await state.update_data(project_id=project_id)
    
    # Получаем название проекта для отображения
    projects_response = await _weeek_client.get_projects()
    projects = projects_response.get("projects", [])
    selected_project_name = "Неизвестный проект"
    for p in projects:
        if p["id"] == project_id:
            selected_project_name = p["title"]
            break

    # Получаем доски для выбранного проекта
    boards_response = await _weeek_client.get_boards(project_id=project_id)
    boards = boards_response.get("boards", [])

    if not boards:
        await callback_query.message.edit_text(f"Выбран проект '{selected_project_name}'. Но для него не найдено досок. Пожалуйста, попробуйте другой проект.")
        await callback_query.answer()
        await state.set_state(TaskCreation.AwaitingProjectSelection) # Возвращаемся к выбору проекта
        return

    # Формируем кнопки для досок
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["name"], callback_data=f"select_board_{b['id']}")] for b in boards
    ])
    
    # Редактируем сообщение, чтобы показать выбранный проект и предложить выбрать доску
    await callback_query.message.edit_text(
        f"Выбран проект: <b>{selected_project_name}</b>.\n"
        f"Теперь, пожалуйста, выберите доску для задачи:",
        reply_markup=keyboard
    )
    await callback_query.answer()
    await state.set_state(TaskCreation.AwaitingBoardSelection)


@router.callback_query(F.data.startswith("select_board_"), TaskCreation.AwaitingBoardSelection)
async def handle_board_selection(callback_query: CallbackQuery, state: FSMContext):
    board_id = int(callback_query.data.split("_")[2])
    await state.update_data(board_id=board_id)

    # Получаем название доски для отображения
    data = await state.get_data()
    project_id = data.get("project_id")
    selected_board_name = "Неизвестная доска"
    if project_id:
        boards_response = await _weeek_client.get_boards(project_id=project_id)
        boards = boards_response.get("boards", [])
        for b in boards:
            if b["id"] == board_id:
                selected_board_name = b["name"]
                break

    # Редактируем сообщение, чтобы показать выбранную доску и убрать кнопки
    await callback_query.message.edit_text(f"Выбрана доска: <b>{selected_board_name}</b>.")
    await callback_query.answer()
    await check_and_ask_for_missing_info(callback_query.message, state)


@router.callback_query(F.data.startswith("select_assignee_"), TaskCreation.AwaitingAssigneeSelection)
async def handle_assignee_selection(callback_query: CallbackQuery, state: FSMContext):
    assignee_id = callback_query.data.split("_")[2]
    await state.update_data(assignee_id=assignee_id)
    
    # Получаем имя выбранного ответственного для отображения
    members_response = await _weeek_client.get_workspace_members()
    members = members_response.get("members", [])
    selected_member_name = "Неизвестный"
    for member in members:
        if member["id"] == assignee_id:
            selected_member_name = f"{member.get('firstName', '')} {member.get('lastName', '')}".strip()
            break

    await callback_query.message.edit_text(f"Выбран ответственный: <b>{selected_member_name}</b> (ID: {assignee_id})")
    await callback_query.answer()
    await check_and_ask_for_missing_info(callback_query.message, state)


@router.message(F.text)
async def handle_text_message(message: Message, bot: Bot, state: FSMContext):
    """Обработчик для текстовых сообщений (точка входа)."""
    current_state = await state.get_state()
    if current_state == TaskCreation.AwaitingDeadline:
        await handle_deadline(message, state)
    elif current_state == TaskCreation.AwaitingAssignee:
        await handle_assignee_text(message, state)
    elif current_state == TaskCreation.AwaitingAssigneeSelection: # Если пользователь ввел текст во время выбора ответственного
        await handle_assignee_text(message, state) # Повторно обрабатываем как текстовый ввод
    else:
        await process_task_text(message.text, message, bot, state)


@router.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot, state: FSMContext):
    """Обработчик для голосовых сообщений (точка входа)."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)
    ogg_filename = f"{message.voice.file_id}.ogg"
    try:
        await bot.download(message.voice, destination=ogg_filename)
        with open(ogg_filename, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        
        text = transcript.text.strip()
        if not text:
            await message.answer("Не смог распознать речь. Попробуйте записать еще раз.")
            return
        
        await message.answer(f"Транскрибация завершена:\n\n«{text}»")
        await process_task_text(text, message, bot, state)
    except Exception as e:
        logging.error(f"Ошибка в handle_voice_message: {e}", exc_info=True)
        await message.answer("🤷‍♂️ Упс, что-то пошло не так при обработке голоса.")
    finally:
        if os.path.exists(ogg_filename):
            os.remove(ogg_filename)
