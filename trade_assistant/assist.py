import os
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from binance import AsyncClient
import pandas as pd
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('telethon').setLevel(logging.WARNING)  # Suppress Telethon INFO messages

# Load environment variables from .env file
load_dotenv()

# Load environment variables
TEL_API_ID = int(os.getenv("TEL_API_ID"))
TEL_API_HASH = os.getenv("TEL_API_HASH")
BI_API_KEY = os.getenv("BI_API_KEY")
BI_API_SECRET = os.getenv("BI_API_SECRET")
TEL_CHAT = os.getenv("TEL_CHAT")  # This should be the ID or username of the private chat

# Initialize Telegram and Binance clients asynchronously with device info
tel_client = TelegramClient(
    'anon',
    TEL_API_ID,
    TEL_API_HASH,
    device_model="Linux",
    system_version="4.16.30-CUSTOM"
)
bi_client = AsyncClient(BI_API_KEY, BI_API_SECRET)

async def get_open_positions():
    try:
        positions = await bi_client.futures_account()
        df = pd.DataFrame(positions['positions'])
        df = df[df['maintMargin'] != '0']
        return df[['symbol', 'unrealizedProfit', 'entryPrice', 'positionAmt', 'notional']]
    except Exception as e:
        logging.error(f"Error fetching open positions: {e}")
        return pd.DataFrame()

async def get_precision(symbol):
    info = await bi_client.futures_exchange_info()
    for x in info['symbols']:
        if x['symbol'] == symbol:
            return int(x['quantityPrecision'])

async def get_last_price(symbol):
    price = await bi_client.futures_mark_price(symbol=symbol)
    return float(price['indexPrice'])

async def order_quantity(amount, symbol):
    price = await get_last_price(symbol)
    precision = await get_precision(symbol)
    return round(amount / price, precision)

async def place_order(side, symbol, amount):
    quantity = await order_quantity(amount, symbol)
    try:
        order = await bi_client.futures_create_order(
            symbol=symbol, type='MARKET', side=side, quantity=quantity
        )
        return order
    except Exception as e:
        logging.error(f"Failed to place order: {e}")
        return {}

async def close_position(coin):
    positions = await get_open_positions()
    posses = positions.set_index('symbol').T.to_dict()
    if coin + 'USDT' in posses:
        pos_Amt = float(posses[coin + 'USDT']['positionAmt'])
        if pos_Amt > 0:
            return await bi_client.futures_create_order(
                symbol=coin + 'USDT',
                type='MARKET',
                side='SELL',
                quantity=abs(pos_Amt)
            )
        elif pos_Amt < 0:
            return await bi_client.futures_create_order(
                symbol=coin + 'USDT',
                type='MARKET',
                side='BUY',
                quantity=abs(pos_Amt)
            )
        else:
            return "Pos was 0"
    return {}

async def close_all_positions():
    positions = await get_open_positions()
    if positions.empty:
        return "No open positions to close."
    results = []
    for index, row in positions.iterrows():
        symbol = row['symbol']
        result = await close_position(symbol.replace('USDT', ''))
        results.append(result)
    return results

async def list_positions():
    positions = await get_open_positions()
    if positions.empty:
        return "No open positions."
    result = ''
    for index, row in positions.iterrows():
        result += (f"{row['symbol']}:\n"
                   f"  Entry: {row['entryPrice']}\n"
                   f"  Size: {round(float(row['notional']), 2)}\n"
                   f"  PnL: {round(float(row['unrealizedProfit']), 2)}\n\n")
    return result.strip()

async def get_balance():
    try:
        account_info = await bi_client.futures_account()
        margin_balance = float(account_info['totalMarginBalance'])
        margin_ratio = float(account_info['totalMaintMargin']) / float(account_info['totalMarginBalance'])
        return margin_balance, margin_ratio
    except Exception as e:
        logging.error(f"Error fetching balance: {e}")
        return None, None

@tel_client.on(events.NewMessage(chats=TEL_CHAT))
async def handle_commands(event):
    if not event.message.text.startswith('/'):
        return  # Ignore any message that doesn't start with '/'

    msg = event.message.text.split()
    command = msg[0][1:].lower()

    if command in ['long', 'short']:
        if len(msg) < 3:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        symbol = msg[1].upper() + 'USDT'
        try:
            amount = float(msg[2])
            if amount <= 0:
                await tel_client.send_message(TEL_CHAT, "Failed")
                return
        except ValueError:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        result = await place_order('BUY' if command == 'long' else 'SELL', symbol, amount)
        if "orderId" in result:
            await tel_client.send_message(TEL_CHAT, "Done")
        else:
            await tel_client.send_message(TEL_CHAT, "Failed")

    elif command == 'list':
        result = await list_positions()
        await tel_client.send_message(TEL_CHAT, result if result else "No open positions.")

    elif command == 'close':
        if len(msg) < 2:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        symbol = msg[1].upper()
        result = await close_position(symbol)
        if "orderId" in result:
            await tel_client.send_message(TEL_CHAT, "Done")
        else:
            await tel_client.send_message(TEL_CHAT, "Failed")

    elif command == 'closeall':
        results = await close_all_positions()
        if all("orderId" in result for result in results):
            await tel_client.send_message(TEL_CHAT, "All positions closed.")
        else:
            await tel_client.send_message(TEL_CHAT, "Failed to close some positions.")

    elif command == 'balance':
        margin_balance, margin_ratio = await get_balance()
        if margin_balance is not None and margin_ratio is not None:
            await tel_client.send_message(
                TEL_CHAT, 
                f"Margin Balance: {margin_balance:.2f}\nMargin Ratio: {margin_ratio:.2%}"
            )
        else:
            await tel_client.send_message(TEL_CHAT, "Failed to fetch balance.")

    else:
        await tel_client.send_message(TEL_CHAT, "Unsupported command")

async def main():
    await tel_client.start()
    logging.info("Bot started and listening...")
    await tel_client.run_until_disconnected()

async def shutdown(loop):
    logging.info("Shutting down...")
    await tel_client.disconnect()
    await bi_client.close_connection()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logging.error(f"Exception during shutdown: {result}")

    loop.stop()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        loop.run_until_complete(shutdown(loop))
    finally:
        loop.close()
