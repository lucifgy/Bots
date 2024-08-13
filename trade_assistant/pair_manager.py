import os
import time
from dotenv import load_dotenv
from telethon import TelegramClient
from binance.client import Client

load_dotenv()

TEL_API_ID = int(os.getenv("TEL_API_ID"))
TEL_API_HASH = os.getenv("TEL_API_HASH")
BI_API_KEY = os.getenv("BI_API_KEY")
BI_API_SECRET = os.getenv("BI_API_SECRET")
TEL_CHAT = os.getenv("TEL_CHAT")

PRICE_THRESHOLD_LOW = 0.0001293
PRICE_THRESHOLD_HIGH = 0.0001315
CHECK_INTERVAL = 300 
SYMBOL = 'SHIBDOGE'

tel_client = TelegramClient('anon', TEL_API_ID, TEL_API_HASH)
bi_client = Client(BI_API_KEY, BI_API_SECRET)

def check_price():
    ticker = bi_client.get_symbol_ticker(symbol=SYMBOL)
    current_price = float(ticker['price'])
    if current_price <= PRICE_THRESHOLD_LOW or current_price >= PRICE_THRESHOLD_HIGH:
        send_alert()

def send_alert():
    with tel_client:
        tel_client.loop.run_until_complete(tel_client.send_message(TEL_CHAT, "/close 1000shib"))
        tel_client.loop.run_until_complete(tel_client.send_message(TEL_CHAT, "/close doge"))

def main():
    with tel_client:
        while True:
            check_price()
            time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
