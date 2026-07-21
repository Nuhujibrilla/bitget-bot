from flask import Flask
import threading
import time
import requests
import os, asyncio, ccxt, json, pandas as pd
import ta
import nest_asyncio 
nest_asyncio.apply() 
from telegram.ext import Application
import traceback # ADDED

app = Flask('') 

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TRADE_AMOUNT = 10
MIN_VOLUME = 5000000
POS_FILE = "positions.json"

application = None

async def send_alert(msg):
    try:
        await application.bot.send_message(chat_id=int(CHAT_ID), text=msg)
    except Exception as e:
        print(f"TELEGRAM SEND ERROR: {e}")

def check_setup():
    errors = []
    if not TOKEN: errors.append("❌ TELEGRAM_TOKEN missing in Render Env")
    if not CHAT_ID: errors.append("❌ TELEGRAM_CHAT_ID missing in Render Env")
    if not os.getenv("BITGET_API_KEY"): errors.append("❌ BITGET_API_KEY missing in Render Env")
    if not os.getenv("BITGET_SECRET"): errors.append("❌ BITGET_SECRET missing in Render Env")
    try: int(CHAT_ID)
    except: errors.append("❌ TELEGRAM_CHAT_ID must be numbers only. Get it from @userinfobot")
    return errors

async def research_and_trade():
    #... same code as before...
    await send_alert("SCAN COMPLETE - No trade") # shortened for space

async def trade_watcher():
    #... same code as before...
    pass

def get_top_100_coins():
    markets = exchange.load_markets()
    return [s for s in markets if '/USDT' in s and markets[s]['active']][:100]

async def run_every(seconds, func):
    while True:
        await func()
        await asyncio.sleep(seconds)

async def keep_alive():
    while True:
        try: requests.get("https://bitget-bot-sg5v.onrender.com")
        except: pass
        await asyncio.sleep(240)

def run_flask():
    app.run(host='0.0.0.0', port=10000, use_reloader=False)

@app.route('/')
def home():
    return "Brian is alive"

async def main():
    global application, exchange, positions
    application = Application.builder().token(TOKEN).build()
    
    # SELF DIAGNOSIS START
    setup_errors = check_setup()
    if setup_errors:
        error_msg = "🚨 BRIAN STARTUP FAILED 🚨\n" + "\n".join(setup_errors)
        print(error_msg)
        # try send even if chat_id is wrong
        if CHAT_ID:
            try: await application.bot.send_message(chat_id=int(CHAT_ID), text=error_msg)
            except: pass
        return # stop here
    
    try:
        exchange = ccxt.bitget({
            'apiKey': os.getenv("BITGET_API_KEY"),
            'secret': os.getenv("BITGET_SECRET"),
            'options': {'defaultType': 'spot'},
            'enableRateLimit': True,
        })
        exchange.load_markets() # test connection
    except Exception as e:
        await send_alert(f"🚨 BITGET API ERROR 🚨\n{e}\n\nCheck your API Key/Secret on Render")
        return
    # SELF DIAGNOSIS END
    
    positions = load_positions()
    await send_alert("🤖 BRIAN V5 ONLINE\nSelf-Diagnosis: PASSED\nStarting 15min Analysis + Keep Alive")
    asyncio.create_task(run_every(900, research_and_trade))
    asyncio.create_task(trade_watcher())
    asyncio.create_task(keep_alive())
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
