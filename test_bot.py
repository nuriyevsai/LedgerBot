import asyncio
from telegram import Bot
from config import BOT_TOKEN

async def main():
    bot = Bot(token=BOT_TOKEN)
    info = await bot.get_me()
    print(info)

asyncio.run(main())
