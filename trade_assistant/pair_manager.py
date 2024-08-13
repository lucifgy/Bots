import os
from dotenv import load_dotenv
from telethon import TelegramClient
from binance import AsyncClient
import asyncio

load_dotenv()

TEL_API_ID = int(os.getenv("TEL_API_ID"))
TEL_API_HASH = os.getenv("TEL_API_HASH")
BI_API_KEY = os.getenv("BI_API_KEY")
BI_API_SECRET = os.getenv("BI_API_SECRET")
TEL_CHAT = os.getenv("TEL_CHAT")

PRICE_THRESHOLD_LOW = 0.0001293
PRICE_THRESHOLD_HIGH = 0.0001326
CHECK_INTERVAL = 300
SYMBOL = 'SHIBDOGE'

tel_client = TelegramClient('anon', TEL_API_ID, TEL_API_HASH, device_model="Linux", system_version="4.16.30-CUSTOM")
bi_client = AsyncClient(BI_API_KEY, BI_API_SECRET)

async def check_price():
    ticker = await bi_client.get_symbol_ticker(symbol=SYMBOL)
    current_price = float(ticker['price'])
    if current_price <= PRICE_THRESHOLD_LOW or current_price >= PRICE_THRESHOLD_HIGH:
        await tel_client.send_message(TEL_CHAT, "/close 1000shib")
        await tel_client.send_message(TEL_CHAT, "/close doge")
        await shutdown()

async def price_monitor():
    while True:
        await check_price()
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    await tel_client.start()
    await price_monitor()

async def shutdown():
    await tel_client.disconnect()
    await bi_client.close_connection()

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        loop.run_until_complete(shutdown())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
