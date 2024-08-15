import os
import time
import sys
from dotenv import load_dotenv
from telethon import TelegramClient
from binance.client import Client
import argparse

load_dotenv()

parser = argparse.ArgumentParser(description="Monitor cryptocurrency prices and send alerts via Telegram.")
parser.add_argument("symbol", type=str, help="The symbol of the cryptocurrency pair to monitor (e.g., SHIBDOGE).")
parser.add_argument("low", type=float, help="The lower price threshold.")
parser.add_argument("high", type=float, help="The higher price threshold.")
parser.add_argument("mainsymbol", type=str, help="The main symbol.")
parser.add_argument("secsymbol", type=str, help="The secondary pair.")
args = parser.parse_args()

TEL_API_ID = int(os.getenv("TEL_API_ID"))
TEL_API_HASH = os.getenv("TEL_API_HASH")
BI_API_KEY = os.getenv("BI_API_KEY")
BI_API_SECRET = os.getenv("BI_API_SECRET")
TEL_CHAT = os.getenv("TEL_CHAT")

PRICE_THRESHOLD_LOW = args.low
PRICE_THRESHOLD_HIGH = args.high
SYMBOL = args.symbol
MAIN_SYMBOL = args.mainsymbol
SEC_SYMBOL = args.secsymbol
CHECK_INTERVAL = 300

tel_client = tel_client = TelegramClient(
    'pair',
    TEL_API_ID,
    TEL_API_HASH,
    device_model="Ubuntu",
    system_version="4.16.31-CUSTOM"
)
bi_client = Client(BI_API_KEY, BI_API_SECRET)

def check_price():
    ticker = bi_client.get_symbol_ticker(symbol=SYMBOL)
    current_price = float(ticker['price'])
    if current_price <= PRICE_THRESHOLD_LOW or current_price >= PRICE_THRESHOLD_HIGH:
        send_alert()
        sys.exit()

def send_alert():
    with tel_client:
        tel_client.loop.run_until_complete(tel_client.send_message(TEL_CHAT, "/close " + MAIN_SYMBOL))
        tel_client.loop.run_until_complete(tel_client.send_message(TEL_CHAT, "/close " + SEC_SYMBOL))

def main():
    with tel_client:
        while True:
            check_price()
            time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
