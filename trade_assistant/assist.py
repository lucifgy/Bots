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

async def place_order(side, symbol, amount, order_type='MARKET', price=None):
    quantity = await order_quantity(amount, symbol)
    order_params = {
        'symbol': symbol,
        'type': order_type,
        'side': side,
        'quantity': quantity
    }
    if order_type == 'LIMIT':
        order_params.update({'price': price, 'timeInForce': 'GTC'})
    try:
        order = await bi_client.futures_create_order(**order_params)
        return order
    except Exception as e:
        logging.error(f"Failed to place order: {e}")
        return {}

async def close_position(coin):
    positions = await get_open_positions()
    posses = positions.set_index('symbol').T.to_dict()
    if coin + 'USDT' in posses:
        pos_Amt = float(posses[coin + 'USDT']['positionAmt'])
        side = 'SELL' if pos_Amt > 0 else 'BUY'
        return await bi_client.futures_create_order(
            symbol=coin + 'USDT',
            type='MARKET',
            side=side,
            quantity=abs(pos_Amt)
        )
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

async def cancel_all_orders(symbol):
    try:
        result = await bi_client.futures_cancel_all_open_orders(symbol=symbol)
        return result
    except Exception as e:
        logging.error(f"Failed to cancel orders: {e}")
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
        unrealized_pnl = float(account_info['totalCrossUnPnl'])
        return margin_balance, margin_ratio, unrealized_pnl
    except Exception as e:
        logging.error(f"Error fetching balance: {e}")
        return None, None, None

async def set_stop_order(symbol, stop_price, order_type):
    positions = await get_open_positions()
    posses = positions.set_index('symbol').T.to_dict()
    if symbol in posses:
        pos_Amt = float(posses[symbol]['positionAmt'])
        side = 'SELL' if pos_Amt > 0 else 'BUY'
        try:
            stop_order = await bi_client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                stopPrice=stop_price,
                closePosition='true'
            )
            return stop_order
        except Exception as e:
            logging.error(f"Error setting {order_type}: {e}")
            return {}
    else:
        return "No open position for this symbol."

async def handle_long(msg):
    if len(msg) < 3:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        amount = float(msg[2])
        if amount <= 0:
            return "Failed"
    except ValueError:
        return "Failed"
    result = await place_order('BUY', symbol, amount)
    return "Done" if "orderId" in result else "Failed"

async def handle_short(msg):
    if len(msg) < 3:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        amount = float(msg[2])
        if amount <= 0:
            return "Failed"
    except ValueError:
        return "Failed"
    result = await place_order('SELL', symbol, amount)
    return "Done" if "orderId" in result else "Failed"

async def handle_list(_):
    return await list_positions()

async def handle_close(msg):
    if len(msg) < 2:
        return "Failed"
    symbol = msg[1].upper()
    result = await close_position(symbol)
    return "Done" if "orderId" in result else "Failed"

async def handle_closeall(_):
    results = await close_all_positions()
    return "Done" if all("orderId" in result for result in results) else "Failed"

async def handle_balance(_):
    margin_balance, margin_ratio, unrealized_pnl = await get_balance()
    if margin_balance is not None and margin_ratio is not None and unrealized_pnl is not None:
        return f"Margin Balance: {margin_balance:.2f}\nMargin Ratio: {margin_ratio:.2%}\nPnL: {unrealized_pnl:.2f}"
    else:
        return "Failed to fetch balance."

async def handle_tp(msg):
    if len(msg) < 3:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        target_price = float(msg[2])
        result = await set_stop_order(symbol, target_price, 'TAKE_PROFIT_MARKET')
        return "Done" if "orderId" in result else "Failed"
    except ValueError:
        return "Failed"

async def handle_stop(msg):
    if len(msg) < 3:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        stop_price = float(msg[2])
        result = await set_stop_order(symbol, stop_price, 'STOP_MARKET')
        return "Done" if "orderId" in result else "Failed"
    except ValueError:
        return "Failed"

async def handle_limitbuy(msg):
    if len(msg) < 4:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        usdt_amount = float(msg[2])
        price = float(msg[3])
        result = await place_order('BUY', symbol, usdt_amount, 'LIMIT', price)
        return "Done" if "orderId" in result else "Failed"
    except ValueError:
        return "Failed"

async def handle_limitsell(msg):
    if len(msg) < 4:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    try:
        usdt_amount = float(msg[2])
        price = float(msg[3])
        result = await place_order('SELL', symbol, usdt_amount, 'LIMIT', price)
        return "Done" if "orderId" in result else "Failed"
    except ValueError:
        return "Failed"

async def handle_cancelall(msg):
    if len(msg) < 2:
        return "Failed"
    symbol = msg[1].upper() + 'USDT'
    result = await cancel_all_orders(symbol)
    return "Done" if "code" in result and result['code'] == 200 else "Failed"

COMMAND_HANDLERS = {
    'long': handle_long,
    'short': handle_short,
    'list': handle_list,
    'close': handle_close,
    'closeall': handle_closeall,
    'balance': handle_balance,
    'tp': handle_tp,
    'stop': handle_stop,
    'limitbuy': handle_limitbuy,
    'limitsell': handle_limitsell,
    'cancelall': handle_cancelall
}

@tel_client.on(events.NewMessage(chats=TEL_CHAT))
async def handle_commands(event):
    if not event.message.text.startswith('/'):
        return  # Ignore any message that doesn't start with '/'

    msg = event.message.text.split()
    command = msg[0][1:].lower()

    handler = COMMAND_HANDLERS.get(command)
    if handler:
        response = await handler(msg)
        await tel_client.send_message(TEL_CHAT, response)
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
