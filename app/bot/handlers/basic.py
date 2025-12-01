from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command(commands=["start"]))
async def handle_start(message: Message):
    await message.answer(
        "<b>Привет! Я — ваш личный помощник для создания задач в Weeek.</b>\n\n"
        "Просто отправьте мне описание задачи в виде текста или голосового сообщения, и я сделаю все остальное.\n\n"
        "Например:\n"
        "<i>«Создай задачу: подготовить отчет по задачам за ноябрь. Дедлайн: завтра в 18:00. Ответственный: Иван»</i>"
    )


@router.message(Command(commands=["help"]))
async def handle_help(message: Message):
    await message.answer(
        "<b>Как пользоваться ботом:</b>\n\n"
        "1. <b>Текстовое сообщение:</b> Просто напишите, что нужно сделать. Постарайтесь указать название задачи, дедлайн и ответственного.\n\n"
        "2. <b>Голосовое сообщение:</b> Надиктуйте вашу задачу. Я транскрибирую ее и создам задачу.\n\n"
        "Я постараюсь сам извлечь все детали, но чем точнее вы сформулируете запрос, тем лучше будет результат."
    )
