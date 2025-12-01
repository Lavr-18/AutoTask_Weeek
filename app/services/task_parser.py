import json
from datetime import datetime
from openai import OpenAI
from app.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

async def parse_task_text(text: str) -> dict:
    """
    Анализирует текст задачи с помощью OpenAI и извлекает структурированные данные.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
    Проанализируй следующий текст задачи и извлеки из него следующую информацию, учитывая, что сегодня {current_date}:
    1. title: Краткое и емкое название задачи.
    2. deadline: Дата и время дедлайна, если указано. Приведи к формату YYYY-MM-DD HH:MM:SS.
    3. assignee: Имя или username ответственного, если указан.

    Текст задачи: "{text}"

    Ответ верни в формате JSON. Если какая-то информация отсутствует, оставь для нее значение null.
    Пример ответа:
    {{
      "title": "Написать отчет по продажам",
      "deadline": "2023-12-31 18:00:00",
      "assignee": "Иван"
    }}
    """

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Ты — ассистент, который помогает парсить текст задачи и возвращает результат в JSON."},
            {"role": "user", "content": prompt}
        ],
    )

    try:
        parsed_data = json.loads(response.choices[0].message.content)
        return parsed_data
    except (json.JSONDecodeError, IndexError):
        return {"title": text, "deadline": None, "assignee": None}
