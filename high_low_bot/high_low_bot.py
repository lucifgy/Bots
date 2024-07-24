import os
import json
import time
import logging
import asyncio
import websockets
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from binance.client import Client
from config import TELEGRAM_TOKEN, CHAT_ID, BINANCE_API_KEY, BINANCE_API_SECRET

# Initialize clients
bot = Bot(token=TELEGRAM_TOKEN)
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

# Disable detailed HTTP request logs for Telegram API
logging.getLogger('telegram').setLevel(logging.CRITICAL)

# Constants
SYMBOLS_FILE = 'symbols.json'
KLINES_FILE = 'klines_data.json'
UPDATE_INTERVAL = 6 * 3600  # 6 hours in seconds
NOTIFICATION_DELAY = 60 * 60  # 1 hour in seconds
FRONTRUN_PERCENTAGE = 0.015  # 1.5%
MAX_CONCURRENT_CONNECTIONS = 50  # Limit the number of concurrent connections
MESSAGE_THROTTLE = 2  # Seconds to wait before retrying
MESSAGE_QUEUE_DELAY = 0.5  # Seconds between processing messages in the queue

# Function to fetch top 50 market cap symbols from Binance Futures based on trading volume
def fetch_top_50_symbols():
    all_symbols = client.futures_exchange_info()
    usdt_pairs = [s['symbol'] for s in all_symbols['symbols'] if s['quoteAsset'] == 'USDT']
    usdt_pairs = [pair for pair in usdt_pairs if pair != 'USDCUSDT']  # Skip USDCUSDT
    tickers = client.get_ticker()
    sorted_tickers = sorted(
        [ticker for ticker in tickers if ticker['symbol'] in usdt_pairs],
        key=lambda x: float(x['quoteVolume']),
        reverse=True
    )
    top_50_symbols = [ticker['symbol'] for ticker in sorted_tickers[:50]]
    return top_50_symbols

# Load or initialize symbols
def load_symbols():
    if os.path.exists(SYMBOLS_FILE):
        with open(SYMBOLS_FILE, 'r') as f:
            return json.load(f)
    else:
        symbols = fetch_top_50_symbols()
        with open(SYMBOLS_FILE, 'w') as f:
            json.dump(symbols, f)
        return symbols

# Update symbols file every 6 hours
def update_symbols():
    symbols = fetch_top_50_symbols()
    with open(SYMBOLS_FILE, 'w') as f:
        json.dump(symbols, f)
    return symbols

# Load or initialize klines data
def load_klines():
    if os.path.exists(KLINES_FILE):
        with open(KLINES_FILE, 'r') as f:
            return json.load(f)
    else:
        return {}

# Update klines data if needed
def update_klines(klines_data, symbols):
    now = time.time()
    if 'last_update' in klines_data and now - klines_data['last_update'] < UPDATE_INTERVAL:
        return klines_data

    for symbol in symbols:
        klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1DAY, limit=7)
        high = max(float(k[2]) for k in klines)
        low = min(float(k[3]) for k in klines)
        klines_data[symbol] = {'high': high, 'low': low}

    klines_data['last_update'] = now
    with open(KLINES_FILE, 'w') as f:
        json.dump(klines_data, f)
    return klines_data

# Send message to Telegram with retry logic
async def send_message(queue):
    while True:
        message, symbol, alert_type = await queue.get()
        while True:
            try:
                await bot.send_message(chat_id=CHAT_ID, text=message)
                logger.info(f"{symbol} sent {alert_type} alert. Success")
                break  # Exit loop if successful
            except RetryAfter as e:
                wait_time = e.retry_after
                logger.warning(f"Rate limited. Waiting for {wait_time} seconds before retrying.")
                await asyncio.sleep(wait_time)
            except TelegramError as e:
                logger.error(f"{symbol} sent {alert_type} alert. Fail")
                await asyncio.sleep(MESSAGE_THROTTLE)  # Wait before retrying on other errors
        queue.task_done()
        await asyncio.sleep(MESSAGE_QUEUE_DELAY)  # Delay between processing messages

# Update kline data in the file
def update_kline_file(symbol, new_data):
    if os.path.exists(KLINES_FILE):
        with open(KLINES_FILE, 'r') as f:
            klines_data = json.load(f)
    else:
        klines_data = {}

    klines_data[symbol] = new_data
    with open(KLINES_FILE, 'w') as f:
        json.dump(klines_data, f)

# Handle WebSocket messages
async def handle_message(symbol, uri, queue):
    async with websockets.connect(uri) as websocket:
        while True:
            msg = await websocket.recv()
            event = json.loads(msg)
            price = float(event['p'])
            now = time.time()

            if price + price * FRONTRUN_PERCENTAGE >= klines_data[symbol]['high']:
                if now - notifications[symbol]['high'] > NOTIFICATION_DELAY:
                    await queue.put((f"{symbol} High!", symbol, "high"))
                    notifications[symbol]['high'] = now
                    klines_data[symbol]['high'] = price  # Update with new high
                    update_kline_file(symbol, klines_data[symbol])
            elif price - price * FRONTRUN_PERCENTAGE <= klines_data[symbol]['low']:
                if now - notifications[symbol]['low'] > NOTIFICATION_DELAY:
                    await queue.put((f"{symbol} Low!", symbol, "low"))
                    notifications[symbol]['low'] = now
                    klines_data[symbol]['low'] = price  # Update with new low
                    update_kline_file(symbol, klines_data[symbol])

# Manage WebSocket connections in batches
async def manage_connections(symbols, queue):
    batches = [symbols[i:i + MAX_CONCURRENT_CONNECTIONS] for i in range(0, len(symbols), MAX_CONCURRENT_CONNECTIONS)]
    
    for batch in batches:
        tasks = []
        for symbol in batch:
            uri = f"wss://fstream.binance.com/ws/{symbol.lower()}@trade"
            tasks.append(handle_message(symbol, uri, queue))
        
        await asyncio.gather(*tasks)
        logger.info(f"Sleeping for 1 second before starting the next batch...")
        await asyncio.sleep(1)  # Give some time before starting the next batch

# Main function
async def main():
    symbols = load_symbols()
    global klines_data
    klines_data = load_klines()
    klines_data = update_klines(klines_data, symbols)

    global notifications
    notifications = {symbol: {'high': 0, 'low': 0} for symbol in symbols}

    queue = asyncio.Queue()
    message_sender = asyncio.create_task(send_message(queue))

    try:
        while True:
            symbols = update_symbols()  # Update symbols every 6 hours
            klines_data = update_klines(klines_data, symbols)
            await manage_connections(symbols, queue)
            logger.info(f"Sleeping for {UPDATE_INTERVAL} seconds before updating symbols again...")
            await asyncio.sleep(UPDATE_INTERVAL)
    finally:
        await queue.join()
        message_sender.cancel()
        await message_sender

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        try:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
