import logging

async def create_task(title: str, deadline: str | None = None, assignee: str | None = None):
    """
    Эта функция будет отправлять запрос к Weeek API для создания задачи.
    Пока что она просто логирует данные.
    """
    logging.info(f"Создание задачи в Weeek:")
    logging.info(f"  Название: {title}")
    if deadline:
        logging.info(f"  Дедлайн: {deadline}")
    if assignee:
        logging.info(f"  Ответственный: {assignee}")
    
    # TODO: Реализовать реальную отправку запроса к Weeek API
    # response = await client.post(...)
    
    logging.info("Задача (не) создана, так как это пока заглушка.")
    return {"status": "success", "task_id": "dummy_id_123"}
