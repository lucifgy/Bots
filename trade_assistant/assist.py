import os
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from binance import AsyncClient
import pandas as pd
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('telethon').setLevel(logging.WARNING)  # Suppress Telethon INFO messages

load_dotenv()

TEL_API_ID = int(os.getenv("TEL_API_ID"))
TEL_API_HASH = os.getenv("TEL_API_HASH")
BI_API_KEY = os.getenv("BI_API_KEY")
BI_API_SECRET = os.getenv("BI_API_SECRET")
TEL_CHAT = os.getenv("TEL_CHAT")
# Liq tracking update
LIQ_TEL_CHAT = int(os.getenv("LIQ_TEL_CHAT"))
LIQ_stop_ratio = 0.5
LIQ_tp_ratio = 0.5
LIQ_size = 75
LIQ_enabled = False
LIQ_short_enabled = True
LIQ_long_enabled = True

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
        
async def get_tick_size(symbol):
    info = await bi_client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    tick_size_str = f['tickSize'].rstrip('0')
                    return len(tick_size_str.split('.')[1]) if '.' in tick_size_str else 0
    return 0

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

async def set_liq_size(msg):
    global LIQ_size
    if len(msg) < 2:
        return "Failed"
    try:
        LIQ_size = int(msg[1])
        return "Done"
    except Exception:
        return "Failed"
    
async def set_liq_stop_ratio(msg):
    global  LIQ_stop_ratio
    if len(msg) < 2:
        return "Failed"
    try:
        LIQ_stop_ratio = float(msg[1])
        return "Done"
    except Exception:
        return "Failed"

async def set_liq_tp_ratio(msg):
    global  LIQ_tp_ratio
    if len(msg) < 2:
        return "Failed"
    try:
        LIQ_tp_ratio = float(msg[1])
        return "Done"
    except Exception:
        return "Failed"

async def set_liq_enable(msg):
    global LIQ_enabled
    global LIQ_short_enabled
    global LIQ_long_enabled
    if len(msg) < 2:
        LIQ_enabled = True
        return "Done"
    elif msg[1].upper() == "SHORT":
        LIQ_short_enabled = True
        return "Done"
    elif msg[1].upper() == "LONG":
        LIQ_long_enabled = True
        return "Done"

async def set_liq_disable(msg):
    global LIQ_enabled
    global LIQ_short_enabled
    global LIQ_long_enabled
    if len(msg) < 2:
        LIQ_enabled = False
        return "Done"
    elif msg[1].upper() == "SHORT":
        LIQ_short_enabled = False
        return "Done"
    elif msg[1].upper() == "LONG":
        LIQ_long_enabled = False
        return "Done"

async def liq_settings(_):
    return f"Size: {LIQ_size}\nTP: {LIQ_tp_ratio}\nStop: {LIQ_stop_ratio}\nEnabled: {LIQ_enabled}\nShort Enabled: {LIQ_short_enabled}\nLong Enabled: {LIQ_long_enabled}"

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
    'cancelall': handle_cancelall,
    'liqsize': set_liq_size,
    'liqstop': set_liq_stop_ratio,
    'liqtp': set_liq_tp_ratio,
    'liqenable': set_liq_enable,
    'liqdisable': set_liq_disable,
    'liqsettings': liq_settings
}

@tel_client.on(events.NewMessage(chats=TEL_CHAT))
async def handle_commands(event):
    if not event.message.text.startswith('/'):
        return

    msg = event.message.text.split()
    command = msg[0][1:].lower()

    handler = COMMAND_HANDLERS.get(command)
    if handler:
        response = await handler(msg)
        if response:
            await tel_client.send_message(TEL_CHAT, response)
        else:
            await tel_client.send_message(TEL_CHAT, "No response generated.")
    else:
        await tel_client.send_message(TEL_CHAT, "Unsupported command")

@tel_client.on(events.NewMessage(chats=LIQ_TEL_CHAT))
async def handle_liquidation_notifications(event):
    if not LIQ_enabled:
        return
        
    message_text = event.message.text
    
    if "#" not in message_text or not ("Long" in message_text or "Short" in message_text):
        return

    try:
        parts = message_text.split()
        ticker = parts[1][1:].upper()
        direction = "BUY" if "Long" in message_text else "SELL"
    except IndexError:
        await tel_client.send_message(TEL_CHAT, "Failed to parse liquidation message structure.")
        return
    
    if direction == "BUY" and not LIQ_long_enabled:
        return
    if direction == "SELL" and not LIQ_short_enabled:
        return

    symbol = f"{ticker}USDT"
    
    positions = await get_open_positions()
    existing_position = positions[positions['symbol'] == symbol]
    if not existing_position.empty and float(existing_position['positionAmt'].iloc[0]) != 0:
        return
    await cancel_all_orders(symbol)
    
    size = LIQ_size
    order = await place_order(direction, symbol, size)
    if "orderId" not in order:
        await tel_client.send_message(TEL_CHAT, f"Failed to open position for {ticker}.")
        return

    positions = await get_open_positions()
    entry_price = float(positions.loc[positions['symbol'] == symbol, 'entryPrice'].iloc[0])

    stop_adjustment = entry_price * (LIQ_stop_ratio / 100)
    tp_adjustment = entry_price * (LIQ_tp_ratio / 100)
    stop_price = round(entry_price - stop_adjustment if direction == "BUY" else entry_price + stop_adjustment, await get_tick_size(symbol))
    tp_price = round(entry_price + tp_adjustment if direction == "BUY" else entry_price - tp_adjustment, await get_tick_size(symbol))

    stop_order_result = await set_stop_order(symbol, stop_price, 'STOP_MARKET')
    tp_order_result = await set_stop_order(symbol, tp_price, 'TAKE_PROFIT_MARKET')

    notification = (
        f"Opened {ticker} {direction} position:\n"
        f"  - Entry Price: {entry_price}\n"
        f"  - Stop: {stop_price}\n"
        f"  - Take Profit: {tp_price}"
    )
    await tel_client.send_message(TEL_CHAT, notification)

    if 'orderId' not in stop_order_result:
        await tel_client.send_message(TEL_CHAT, f"Failed to set stop for {ticker}")

    if 'orderId' not in tp_order_result:
        await tel_client.send_message(TEL_CHAT, f"Failed to set tp for {ticker}")

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
