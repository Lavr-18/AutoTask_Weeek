import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEEEK_API_TOKEN = os.getenv("WEEEK_API_TOKEN")
WEEEK_API_BASE_URL = os.getenv("WEEEK_API_BASE_URL", "https://api.weeek.net/public/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
