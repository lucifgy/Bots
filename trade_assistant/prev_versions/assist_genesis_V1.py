from telethon import TelegramClient, events
import json
from binance import Client
import pandas as pd
from os import environ

tel_api_id = 123
tel_api_hash = "api_hash"

bi_api = "api_key"
bi_secret = "api_secret"

tel_chat = "Username/ChatId"


tel_client = TelegramClient('anon', tel_api_id, tel_api_hash, device_model="Windows 10", system_version="4.16.30-CUSTOM")

bi_client = Client(bi_api, bi_secret)

def getOpenPositions_Future(client):
    positions = client.futures_account()['positions']
    positions = pd.DataFrame.from_dict(positions)
    positions = positions.loc[positions['maintMargin']!='0']
    return positions[['symbol', 'unrealizedProfit', 'entryPrice', 'positionAmt', 'notional']]

info = bi_client.futures_exchange_info()
    
def get_precision(symbol):
   for x in info['symbols']:
    if x['symbol'] == symbol:
        return int(x['quantityPrecision'])

def get_last_price(symbol):
    return float(bi_client.futures_mark_price(symbol=symbol)['indexPrice'])

def order_quantity(input, symbol):
    return round(input / get_last_price(symbol), get_precision(symbol))

def long(coin, amount):
    return bi_client.futures_create_order(
    symbol=coin + 'USDT',
    type='MARKET',
    side='BUY',
    quantity=order_quantity(amount, coin + 'USDT')
    )

def short(coin, amount):
    return bi_client.futures_create_order(
    symbol=coin + 'USDT',
    type='MARKET',
    side='SELL',
    quantity=order_quantity(amount, coin + 'USDT')
    )

def close_pos(coin):
    posses = getOpenPositions_Future(bi_client).set_index('symbol').T.to_dict()
    pos_Amt = float(posses[coin + 'USDT']['positionAmt'])
    if pos_Amt > 0:
        return bi_client.futures_create_order(
        symbol=coin + 'USDT',
        type='MARKET',
        side='SELL',
        quantity=abs(pos_Amt)
        )
    elif pos_Amt < 0:
        return bi_client.futures_create_order(
        symbol=coin + 'USDT',
        type='MARKET',
        side='BUY',
        quantity=abs(pos_Amt)
        )
    else:
        return "Pos was 0"

def list():
    posses = getOpenPositions_Future(bi_client).reset_index(drop=True).T.to_dict()

    string = ""
    for i in range(0, len(posses)):
        string += posses[i]['symbol'] + '\n'
        string += "Entry: " + posses[i]['entryPrice'] + '\n'
        string += "Size: " + posses[i]['notional'] + '\n'
        string += "PnL: " + posses[i]['unrealizedProfit'] + '\n'
        if i < len(posses) - 1:
            string += "\n\n"

    return string

tel_client.disconnect()
tel_client.start()

print("Ctrl + C to exit")

@tel_client.on(events.NewMessage(chats=tel_chat))
async def nm_handler(event):
    msgs = await tel_client.get_messages(tel_chat)
    last_msg = msgs[0].message
    if last_msg[0] == "/":
        split_last_msg = last_msg.split(" ")
        if split_last_msg[0] == "/short":
            try:
                short(split_last_msg[1].upper(), int(split_last_msg[2]))
                await tel_client.send_message(tel_chat, "Done")
            except Exception:
                await tel_client.send_message(tel_chat, "Failed")

        elif split_last_msg[0] == "/long":
            try:
                long(split_last_msg[1].upper(), int(split_last_msg[2]))
                await tel_client.send_message(tel_chat, "Done")
            except Exception:
                await tel_client.send_message(tel_chat, "Failed")

        elif split_last_msg[0] == "/close":
            try:
                close_pos(split_last_msg[1].upper())
                await tel_client.send_message(tel_chat, "Done")
            except Exception:
                await tel_client.send_message(tel_chat, "Failed")
            
        elif split_last_msg[0] == "/list":
            await tel_client.send_message(tel_chat, list())
    else:
        pass

with tel_client:
    tel_client.run_until_disconnected()
