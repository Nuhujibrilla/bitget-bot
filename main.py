import ccxt
import time
import os
import telegram
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask
import threading
import asyncio

# ===== BRIAN SETTINGS =====
BITGET_API_KEY = os.getenv('BITGET_API_KEY')
BITGET_SECRET = os.getenv('BITGET_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

TRADE_AMOUNT = 2 # $2 per trade
MIN_COIN_PRICE = 5.0 # Skip coins under $5
# ==========================

exchange = ccxt.bitget({
    'apiKey': BITGET_API_KEY,
    'secret': BITGET_SECRET,
    'enableRateLimit': True,
})
bot = telegram.Bot(token=TELEGRAM_TOKEN)

async def send_msg(text):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode='Markdown')
    except Exception as e:
        print("Telegram Error:", e)

def get_top_100_coins():
    try:
        markets = exchange.load_markets()
        usdt_pairs = [s for s in markets if s.endswith('/USDT')]
        tickers = exchange.fetch_tickers(usdt_pairs)
        sorted_pairs = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True)
        return [pair for pair, data in sorted_pairs[:100]]
    except:
        return []

def scan():
    while True:
        try:
            coins = get_top_100_coins()
            print(f"{datetime.now()} | Scanning {len(coins)} coins > ${MIN_COIN_PRICE}...")
            signals = 0

          for symbol in coins:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    change = ticker['percentage'] or 0

                    if price < MIN_COIN_PRICE: # Skip cheap coins
                        continue

                    if change > 4.0: # Signal: +4% pump
                        signals += 1
                        entry = price
                        amount = TRADE_AMOUNT / entry
                        sl = entry * 0.97
                        tp = entry * 1.06

                        asyncio.run(send_msg(f"🚨 *SIGNAL* 🚨\n*Coin*: {symbol}\n*Price*: ${price:.4f}\n*24h*: +{change:.2f}%\n*Buying*: ${TRADE_AMOUNT}"))

                        order = exchange.create_market_buy_order(symbol, amount)
                        exchange.create_order(symbol, 'stop', 'sell', order['amount'], sl)
                        exchange.create_order(symbol, 'limit', 'sell', order['amount'], tp)

                        profit_usdt = (tp - entry) * order['amount']
                        asyncio.run(send_msg(f"✅ *BOUGHT*\n*Entry*: ${entry:.4f}\n*SL*: ${sl:.4f}\n*TP*: ${tp:.4f}\n*Est Profit*: ${profit_usdt:.2f}"))
                        time.sleep(3)

                except Exception as e:
                    continue

            print(f"Scan done. Signals: {signals}")

        except Exception as e:
            print("Scan Error:", e)

        time.sleep(900) # 15 min

# KEEPALIVE
app = Flask('')
@app.route('/')
def home():
    return "BRIAN BOT ALIVE 24/7"

def run_web():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_web, daemon=True).start()
threading.Thread(target=scan, daemon=True).start()

# TELEGRAM
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ BRIAN ONLINE 24/7\nScanning: 100 coins >${MIN_COIN_PRICE}\nTrade: ${TRADE_AMOUNT}\nEvery: 15min")

app_telegram = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app_telegram.add_handler(CommandHandler("status", status))
print("BRIAN STARTED")
app_telegram.run_polling()
