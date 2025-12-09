import logging
import aiohttp
from typing import Optional, List, Dict, Any

from app.config import WEEEK_API_TOKEN, WEEEK_API_BASE_URL

BACKLOG_COLUMN_NAME = "Backlog"

class WeeekAPIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.logger = logging.getLogger(__name__)

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        self.logger.debug(f"Making {method} request to {url} with data: {kwargs.get('json') or kwargs.get('params')}")
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.request(method, url, **kwargs) as response:
                    response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
                    return await response.json()
            except aiohttp.ClientResponseError as e:
                detailed_error_message = f"Weeek API request failed with status {e.status}: {e.message}"
                try:
                    error_json = await response.json()
                    detailed_error_message += f" - Details: {error_json}"
                except aiohttp.ContentTypeError:
                    error_text = await response.text()
                    detailed_error_message += f" - Response text: {error_text}"
                
                self.logger.error(detailed_error_message)
                # Re-raise the exception, but include the detailed message
                raise aiohttp.ClientResponseError(
                    request_info=e.request_info,
                    history=e.history,
                    status=e.status,
                    message=detailed_error_message, # Передаем подробное сообщение
                    headers=e.headers
                )
            except aiohttp.ClientError as e:
                self.logger.error(f"Weeek API request failed: {e}")
                raise

    async def get_workspace_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/ws")

    async def get_workspace_members(self) -> Dict[str, Any]:
        """
        Retrieves a list of workspace members.
        """
        return await self._request("GET", "/ws/members")

    async def get_projects(self) -> Dict[str, Any]:
        return await self._request("GET", "/tm/projects")

    async def get_boards(self, project_id: int) -> Dict[str, Any]:
        return await self._request("GET", "/tm/boards", params={"projectId": project_id})

    async def get_board_columns(self, board_id: int) -> Dict[str, Any]:
        return await self._request("GET", "/tm/board-columns", params={"boardId": board_id})

    async def create_task(self, title: str, description: Optional[str], locations: List[Dict[str, Any]],
                          day: Optional[str] = None, parent_id: Optional[int] = None,
                          user_id: Optional[str] = None, task_type: Optional[str] = None,
                          priority: Optional[int] = None, custom_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Creates a task in Weeek.
        """
        payload = {
            "title": title,
            "description": description,
            "locations": locations
        }
        if day:
            payload["day"] = day
        if parent_id:
            payload["parentId"] = parent_id
        if user_id:
            payload["userId"] = user_id
        if task_type:
            payload["type"] = task_type
        if priority is not None:
            payload["priority"] = priority
        if custom_fields:
            payload["customFields"] = custom_fields
            
        return await self._request("POST", "/tm/tasks", json=payload)

# Initialize client globally
_weeek_client = WeeekAPIClient(base_url=WEEEK_API_BASE_URL, token=WEEEK_API_TOKEN)


async def create_weeek_task(title: str, description: Optional[str] = None,
                            deadline: Optional[str] = None, assignee_id: Optional[str] = None,
                            project_id: int = None,
                            board_id: int = None) -> Dict[str, Any]:
    """
    Эта функция будет отправлять запрос к Weeek API для создания задачи.
    Принимает конкретные ID проекта и доски.
    """
    logging.info(f"Attempting to create task in Weeek:")
    logging.info(f"  Title: {title}")
    if description:
        logging.info(f"  Description: {description}")
    if deadline:
        logging.info(f"  Deadline: {deadline}")
    if assignee_id:
        logging.info(f"  Assignee ID: {assignee_id}")
    if project_id:
        logging.info(f"  Target Project ID: {project_id}")
    if board_id:
        logging.info(f"  Target Board ID: {board_id}")

    try:
        if project_id is None or board_id is None:
            return {"status": "error", "message": "Project ID and Board ID must be provided."}

        # 1. Get board columns for the selected board
        columns_response = await _weeek_client.get_board_columns(board_id=board_id)
        columns = columns_response.get("boardColumns", [])

        if not columns:
            logging.warning(f"No columns found for board ID {board_id}. Cannot create task.")
            return {"status": "error", "message": f"No columns found for board ID {board_id}."}

        # 2. Find the backlog column
        backlog_column_id = None
        for column in columns:
            if column.get("name") == BACKLOG_COLUMN_NAME:
                backlog_column_id = column["id"]
                break

        if backlog_column_id is None:
            logging.warning(f"Backlog column '{BACKLOG_COLUMN_NAME}' not found for board ID {board_id}. Cannot create task in backlog.")
            return {"status": "error", "message": f"Backlog column '{BACKLOG_COLUMN_NAME}' not found for board ID {board_id}."}
        
        logging.info(f"Found backlog column: '{BACKLOG_COLUMN_NAME}' (ID: {backlog_column_id})")

        # 3. Construct locations payload
        locations_payload = [
            {
                "projectId": project_id,
                "boardColumnId": backlog_column_id
            }
        ]

        # 4. Create the task
        response = await _weeek_client.create_task(
            title=title,
            description=description,
            locations=locations_payload,
            day=deadline,  # Раскомментировано
            user_id=assignee_id # Pass assignee ID as 'userId'
        )
        logging.info(f"Task creation response: {response}")
        return {"status": "success", "task_id": response.get("task", {}).get("id"), "response": response}
    except aiohttp.ClientResponseError as e:
        # Теперь e.message уже содержит подробную информацию
        error_message = f"Weeek API error: {e.message}"
        logging.error(error_message)
        return {"status": "error", "message": error_message}
    except Exception as e:
        logging.error(f"Failed to create task in Weeek: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
