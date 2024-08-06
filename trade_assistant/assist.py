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

# Initialize Telegram client with device info
tel_client = TelegramClient(
    'anon',
    TEL_API_ID,
    TEL_API_HASH,
    device_model="Linux",
    system_version="4.16.30-CUSTOM"
)

# Initialize Binance client asynchronously
async def init_binance_client():
    return await AsyncClient.create(BI_API_KEY, BI_API_SECRET)

bi_client = asyncio.run(init_binance_client())

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
    try:
        info = await bi_client.futures_exchange_info()
        for x in info['symbols']:
            if x['symbol'] == symbol:
                return int(x['quantityPrecision'])
    except Exception as e:
        logging.error(f"Error fetching precision for {symbol}: {e}")

async def get_last_price(symbol):
    try:
        price = await bi_client.futures_mark_price(symbol=symbol)
        return float(price['indexPrice'])
    except Exception as e:
        logging.error(f"Error fetching last price for {symbol}: {e}")

async def order_quantity(amount, symbol):
    try:
        price = await get_last_price(symbol)
        precision = await get_precision(symbol)
        return round(amount / price, precision)
    except Exception as e:
        logging.error(f"Error calculating order quantity for {symbol}: {e}")

async def create_order(order_type, symbol, side, quantity, price=None):
    try:
        params = {
            'symbol': symbol,
            'type': order_type,
            'side': side,
            'quantity': quantity
        }
        if price:
            params['price'] = price
            params['timeInForce'] = 'GTC'
        order = await bi_client.futures_create_order(**params)
        return order
    except Exception as e:
        logging.error(f"Failed to place {order_type} order for {symbol}: {e}")
        return {}

async def place_market_order(side, symbol, amount):
    quantity = await order_quantity(amount, symbol)
    return await create_order('MARKET', symbol, side, quantity)

async def place_limit_order(side, symbol, usdt_amount, price):
    quantity = await order_quantity(usdt_amount, symbol)
    return await create_order('LIMIT', symbol, side, quantity, price)

async def place_conditional_order(order_type, symbol, price):
    positions = await get_open_positions()
    posses = positions.set_index('symbol').T.to_dict()
    if symbol in posses:
        pos_amt = float(posses[symbol]['positionAmt'])
        side = 'SELL' if pos_amt > 0 else 'BUY'
        return await create_order(order_type, symbol, side, abs(pos_amt), price)
    else:
        return "No open position for this symbol."

async def close_position(coin):
    return await place_conditional_order('MARKET', coin + 'USDT', None)

async def close_all_positions():
    positions = await get_open_positions()
    if positions.empty:
        return "No open positions to close."
    results = [await close_position(row['symbol'].replace('USDT', '')) for index, row in positions.iterrows()]
    return results

async def cancel_all_orders(symbol):
    try:
        result = await bi_client.futures_cancel_all_open_orders(symbol=symbol)
        return result
    except Exception as e:
        logging.error(f"Failed to cancel orders for {symbol}: {e}")
        return {}

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

async def handle_commands(event):
    if not event.message.text.startswith('/'):
        return  # Ignore any message that doesn't start with '/'

    msg = event.message.text.split()
    command = msg[0][1:].lower()

    command_mapping = {
        'long': place_market_order,
        'short': place_market_order,
        'limitbuy': place_limit_order,
        'limitsell': place_limit_order,
        'close': close_position,
        'closeall': close_all_positions,
        'balance': get_balance,
        'tp': lambda symbol, price: place_conditional_order('TAKE_PROFIT_MARKET', symbol, price),
        'stop': lambda symbol, price: place_conditional_order('STOP_MARKET', symbol, price),
        'cancelall': cancel_all_orders
    }

    async def send_result(result):
        await tel_client.send_message(TEL_CHAT, "Done" if "orderId" in result else "Failed")

    if command in ['long', 'short', 'limitbuy', 'limitsell']:
        if len(msg) < 4:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        symbol = msg[1].upper() + 'USDT'
        try:
            usdt_amount = float(msg[2])
            price = float(msg[3]) if command in ['limitbuy', 'limitsell'] else None
            if usdt_amount <= 0:
                await tel_client.send_message(TEL_CHAT, "Failed")
                return
        except ValueError:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        result = await command_mapping[command](command, symbol, usdt_amount, price)
        await send_result(result)

    elif command in ['close', 'cancelall']:
        if len(msg) < 2:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        symbol = msg[1].upper() + 'USDT'
        result = await command_mapping[command](symbol)
        await send_result(result)

    elif command == 'closeall':
        results = await close_all_positions()
        if all("orderId" in result for result in results):
            await tel_client.send_message(TEL_CHAT, "Done")
        else:
            await tel_client.send_message(TEL_CHAT, "Failed")

    elif command == 'balance':
        margin_balance, margin_ratio = await get_balance()
        if margin_balance is not None and margin_ratio is not None:
            await tel_client.send_message(
                TEL_CHAT,
                f"Margin Balance: {margin_balance:.2f}\nMargin Ratio: {margin_ratio:.2%}"
            )
        else:
            await tel_client.send_message(TEL_CHAT, "Failed to fetch balance.")

    elif command == 'list':
        result = await list_positions()
        await tel_client.send_message(TEL_CHAT, result if result else "No open positions.")

    elif command in ['tp', 'stop']:
        if len(msg) < 3:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        symbol = msg[1].upper() + 'USDT'
        try:
            price = float(msg[2])
        except ValueError:
            await tel_client.send_message(TEL_CHAT, "Failed")
            return

        result = await command_mapping[command](symbol, price)
        await send_result(result)

    else:
        await tel_client.send_message(TEL_CHAT, "Unsupported command")

@tel_client.on(events.NewMessage(chats=TEL_CHAT))
async def handle_commands_wrapper(event):
    await handle_commands(event)

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
