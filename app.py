from flask import Flask
import threading, time, requests, os
import ccxt, json, pandas as pd, datetime
import ta
import nest_asyncio 
nest_asyncio.apply() 
from telegram.ext import Application

app = Flask('') 

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TRADE_AMOUNT = 10
MIN_VOLUME = 10000000
SL_PERCENT = 5
TP_PERCENT = 15
SCAN_INTERVAL = 600
POS_FILE = "positions.json"

exchange = ccxt.bitget({
    'apiKey': os.getenv("BITGET_API_KEY"),
    'secret': os.getenv("BITGET_SECRET"),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True,
})

def load_positions():
    try: 
        with open(POS_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_positions(pos): 
    with open(POS_FILE, 'w') as f: json.dump(pos, f)

positions = load_positions()
application = None

async def send_alert(msg):
    await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')

async def research_and_trade():
    await send_alert(f"🧠 <b>BRIAN SCANNING...</b> {datetime.datetime.now().strftime('%H:%M')}")
    try:
        # Check BTC
        btc = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=200)
        btc_df = pd.DataFrame(btc, columns=['t','o','h','l','c','v'])
        btc_df['ma200'] = ta.trend.SMAIndicator(btc_df['c'], 200).sma_indicator()
        market = "BULLISH 🟢" if btc_df.iloc[-1]['c'] > btc_df.iloc[-1]['ma200'] else "BEARISH 🔴"
        
        coins = [s for s in exchange.load_markets() if '/USDT' in s][:100]
        for symbol in coins:
            if symbol in positions: continue
            try:
                data = exchange.fetch_ohlcv(symbol, '1h', limit=200)
                df = pd.DataFrame(data, columns=['t','o','h','l','c','v'])
                df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
                df['ma20'] = ta.trend.SMAIndicator(df['c'], 20).sma_indicator()
                df['ma50'] = ta.trend.SMAIndicator(df['c'], 50).sma_indicator()
                df['ma200'] = ta.trend.SMAIndicator(df['c'], 200).sma_indicator()
                df['avg_vol'] = df['v'].rolling(20).mean()
                last = df.iloc[-1]
                
                if last['volume'] < MIN_VOLUME: continue
                if last['close'] > last['ma200'] and last['ma20'] > last['ma50'] and last['rsi'] < 70 and market == "BULLISH 🟢":
                    price = last['c']
                    amount = TRADE_AMOUNT / price
                    exchange.create_market_buy_order(symbol, amount)
                    positions[symbol] = {'entry': price, 'amount': amount}
                    save_positions(positions)
                    await send_alert(f"🚨 <b>TRADE</b> 🚨\nBought {symbol}\nPrice: ${price:.5f}\nMarket: {market}")
                    break
            except: pass
        await send_alert(f"📊 <b>SCAN DONE</b>\nMarket: {market}")
    except Exception as e:
        await send_alert(f"ERROR: {e}")

async def check_positions():
    global positions
    for symbol in list(positions.keys()):
        try:
            price = exchange.fetch_ticker(symbol)['last']
            entry = positions[symbol]['entry']
            pnl = ((price - entry) / entry) * 100
            if pnl <= -SL_PERCENT or pnl >= TP_PERCENT:
                exchange.create_market_sell_order(symbol, positions[symbol]['amount'])
                await send_alert(f"💰 <b>CLOSED</b> {symbol}\nP&L: {pnl:.2f}%")
                del positions[symbol]
                save_positions(positions)
        except: pass

async def run_every(seconds, func):
    while True: await func(); await asyncio.sleep(seconds)

def run_flask(): app.run(host='0.0.0.0', port=10000)
@app.route('/')
def home(): return "Brian is alive"

async def main():
    global application
    application = Application.builder().token(TOKEN).build()
    await send_alert("🤖 <b>BRIAN ONLINE</b>")
    asyncio.create_task(run_every(SCAN_INTERVAL, research_and_trade))
    asyncio.create_task(run_every(60, check_positions))
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
