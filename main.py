from flask import Flask
import threading, time, requests, os
import ccxt, json, pandas as pd, datetime
import ta
import nest_asyncio 
nest_asyncio.apply() 
from telegram.ext import Application

app = Flask('') 

# ====== SETTINGS ======
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TRADE_AMOUNT = 10 # $10 per trade
MIN_VOLUME = 10000000 # $10M 24h volume
SL_PERCENT = 5 # Stop Loss 5%
TP_PERCENT = 15 # Take Profit 15%
SCAN_INTERVAL = 600 # 10 minutes
POS_FILE = "positions.json"
# ======================

exchange = ccxt.bitget({
    'apiKey': os.getenv("BITGET_API_KEY"),
    'secret': os.getenv("BITGET_SECRET"),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True,
})

def load_positions():
    try: 
        with open(POS_FILE, 'r') as f:
            return json.load(f)
    except: 
        return {}

def save_positions(pos): 
    with open(POS_FILE, 'w') as f:
        json.dump(pos, f)

positions = load_positions()
application = None

async def send_alert(msg):
    try:
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')
    except Exception as e:
        print(f"Telegram Error: {e}")

def analyze_coin(df):
    last = df.iloc[-1]
    reason = []
    
    if last['close'] > last['ma200']: reason.append("Above MA200")
    if last['ma20'] > last['ma50']: reason.append("Golden Cross")
    if 45 < last['rsi'] < 70: reason.append(f"RSI:{last['rsi']:.0f}")
    if last['volume'] > last['avg_vol'] * 1.5: reason.append("Vol Spike")
    
    change_1h = ((last['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
    if change_1h > 2: reason.append(f"1h:+{change_1h:.1f}%")
    
    signal = "BUY" if len(reason) >= 3 else "HOLD"
    return signal, " | ".join(reason)

async def check_positions():
    global positions
    for symbol in list(positions.keys()):
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            entry = positions[symbol]['entry']
            amount = positions[symbol]['amount']
            pnl = ((current_price - entry) / entry) * 100
            
            if pnl <= -SL_PERCENT:
                exchange.create_market_sell_order(symbol, amount)
                await send_alert(f"🚨 <b>STOP LOSS</b> 🚨\n{symbol}\nEntry:${entry:.5f} Exit:${current_price:.5f}\nP&L:{pnl:.2f}%")
                del positions[symbol]
                
            elif pnl >= TP_PERCENT:
                exchange.create_market_sell_order(symbol, amount)
                await send_alert(f"🎯 <b>TAKE PROFIT</b> 🎯\n{symbol}\nEntry:${entry:.5f} Exit:${current_price:.5f}\nP&L:+{pnl:.2f}%")
                del positions[symbol]
            save_positions(positions)
        except: pass

async def research_and_trade():
    try:
        # 1. CHECK BTC DIRECTION
        btc_ohlcv = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=200)
        btc_df = pd.DataFrame(btc_ohlcv, columns=['t','o','h','l','c','v'])
        btc_df['ma200'] = ta.trend.SMAIndicator(btc_df['c'], 200).sma_indicator()
        market = "BULLISH 🟢" if btc_df.iloc[-1]['c'] > btc_df.iloc[-1]['ma200'] else "BEARISH 🔴"
        
        await send_alert(f"🧠 <b>BRIAN SCAN START</b>\n<b>Market:</b> {market}\n<b>Time:</b> {datetime.datetime.now().strftime('%H:%M')}")
        
        markets = exchange.load_markets()
        coins = [s for s in markets if '/USDT' in s and markets[s]['active']][:100]
        
        best_coin = None
        best_reason = ""

        for symbol in coins:
            if symbol in positions: continue
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=200)
                df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
                df['ma20'] = ta.trend.SMAIndicator(df['c'], 20).sma_indicator()
                df['ma50'] = ta.trend.SMAIndicator(df['c'], 50).sma_indicator()
                df['ma200'] = ta.trend.SMAIndicator(df['c'], 200).sma_indicator()
                df['avg_vol'] = df['v'].rolling(20).mean()
                
                ticker = exchange.fetch_ticker(symbol)
                if ticker['quoteVolume'] < MIN_VOLUME: continue
                
                signal, reason = analyze_coin(df)
                
                if signal == "BUY" and market == "BULLISH 🟢":
                    best_coin = symbol
                    best_reason = reason
                    break # Take first good signal
            except: pass
            await asyncio.sleep(0.1)

        # 2. AUTO BUY
        if best_coin:
            ticker = exchange.fetch_ticker(best_coin)
            price = ticker['last']
            amount = TRADE_AMOUNT / price
            exchange.create_market_buy_order(best_coin, amount)
            positions[best_coin] = {'entry': price, 'amount': amount}
            save_positions(positions)
            await send_alert(f"""🚨 <b>NEW TRADE EXECUTED</b> 🚨

<b>Pair:</b> {best_coin}
<b>Action:</b> BUY ${TRADE_AMOUNT}
<b>Price:</b> ${price:.5f}

<b>WHY BRIAN BOUGHT:</b>
{best_reason}

<b>RISK:</b> SL:-{SL_PERCENT}% | TP:+{TP_PERCENT}%""")
        else:
            await send_alert(f"📊 <b>SCAN DONE</b>\nNo BUY signal found.\n<b>Market:</b> {market}")

    except Exception as e:
        await send_alert(f"🚨 ERROR: {str(e)}")

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
    app.run(host='0.0.0.0', port=10000)

@app.route('/')
def home():
    return "Brian V11 is alive"

async def main():
    global application
    application = Application.builder().token(TOKEN).build()
    await send_alert(f"🤖 <b>BRIAN V11 ONLINE</b>\nAuto Trading: ON\nScan: Every 10min")
    asyncio.create_task(run_every(SCAN_INTERVAL, research_and_trade))
    asyncio.create_task(run_every(60, check_positions))
    asyncio.create_task(keep_alive())
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
