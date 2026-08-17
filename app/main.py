import asyncio
import os
import threading

import uvicorn

from .config import settings
from .db import init_db
from .api import app
from .bot import run_bot, setup_webhooks

# پیش‌فرض روی لوکال‌هاست است تا API مدیریتی ناخواسته روی اینترنت باز نشود.
# در داکر با API_HOST=0.0.0.0 (تعریف‌شده در docker-compose) اجرا می‌شود.
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))


def run_api():
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


async def main():
    init_db()
    if settings.use_webhook:
        # وب‌هوک: آپدیت‌ها از طریق همان سرور FastAPI می‌آیند، پس polling لازم نیست.
        config = uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info")
        server = uvicorn.Server(config)
        await setup_webhooks()
        await server.serve()
        return
    threading.Thread(target=run_api, daemon=True).start()
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
