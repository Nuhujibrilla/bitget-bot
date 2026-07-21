from flask import Flask
import threading
app = Flask('') # Keep Render alive

import os, time, asyncio, ccxt, json, pandas as pd
import ta # Technical analysis
from telegram import Update
from telegram.ext import Application

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TRADE_AMOUNT = 10
MIN_VOLUME = 5000000 # Anti-scam filter
POS_FILE = "positions.json"

exchange = ccxt.bitget({
    'apiKey': os.getenv("BITGET_API_KEY"),
    'secret': os.getenv("BITGET_SECRET"),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True,
})

def load_positions():
    try: return json.load(open(POS_FILE))
    except: return {}
def save_positions(pos): json.dump(pos, open(POS_FILE, 'w'))

positions = load_positions()
application = None

async def research_and_trade():
    coins = get_top_100_coins()
    scored_coins = []
    scam_count = 0

    for symbol in coins:
        try:
            # 1. GET 15MIN CANDLES FOR INDICATORS
            ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=200)
            if len(ohlcv) < 50: continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # 2. CALCULATE INDICATORS
            df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            df['ma20'] = ta.trend.SMAIndicator(df['close'], window=20).sma_indicator()
            df['ma50'] = ta.trend.SMAIndicator(df['close'], window=50).sma_indicator()
            df['ma200'] = ta.trend.SMAIndicator(df['close'], window=200).sma_indicator()
            df['avg_vol'] = df['volume'].rolling(window=20).mean()
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            change = ((last['close'] - prev['close']) / prev['close']) * 100
            volume = last['volume']
            price = last['close']

            # 3. ANTI-SCAM FILTER
            if volume < MIN_VOLUME: scam_count +=1; continue

            # 4. HUMAN TRADER FILTERS - ALL MUST PASS
            is_uptrend = last['ma20'] > last['ma50'] # Trend is up
            is_not_overbought = last['rsi'] < 70 and last['rsi'] > 50 # Not too hot, not dead
            is_high_volume = volume > (last['avg_vol'] * 1.5) # Volume spike
            is_strong_move = change > 2.0 # 2% move in 15min
            
            if is_uptrend and is_not_overbought and is_high_volume and is_strong_move:
                score = change + (volume / 1000000) + last['rsi'] # Score with RSI
                scored_coins.append({
                    'symbol': symbol, 
                    'price': price, 
                    'change': change, 
                    'rsi': last['rsi'],
                    'ma20': last['ma20'],
                    'score': score
                })
                
        except Exception as e: pass

    if not scored_coins:
        await application.bot.send_message(CHAT_ID, "📊 BRIAN REPORT\n⏰ " + time.strftime('%H:%M') + "\nNo coins passed RSI + MA + Volume check.")
        return

    scored_coins.sort(key=lambda x: x['score'], reverse=True)
    best = scored_coins[0]
    avg_change = sum(d['change'] for d in scored_coins) / len(scored_coins)

    # MARKET STRATEGY
    if avg_change > 4: verdict = "BULLISH STRONG 🔥🔥"; strategy = "Ride trend. Quick TP."
    elif avg_change > 2: verdict = "BULLISH 🔥"; strategy = "Trend-following. Take profits."
    elif avg_change < -2: verdict = "BEARISH 🐻"; strategy = "Tight SL. Stay safe."
    else: verdict = "SIDEWAYS 😐"; strategy = "Buy dips, Sell rips."

    # AUTO BUY IF BULLISH
    trade_msg = ""
    if avg_change > 1 and best['change'] > 3 and best['symbol'] not in positions:
        try:
            amount_coin = TRADE_AMOUNT / best['price']
            exchange.create_market_buy_order(best['symbol'], amount_coin)
            positions[best['symbol']] = {'entry': best['price'], 'amount': amount_coin}
            save_positions(positions)
            trade_msg = f"\n🚨 AUTO BUY EXECUTED!\n{best['symbol']} @ ${best['price']:.4f}\nRSI: {best['rsi']:.1f} | MA20: ${best['ma20']:.4f}\nSL: -5% | TP: +10%"
        except Exception as e: trade_msg = f"\n❌ Buy failed: {e}"

    top3 = "\n".join([f"{i+1}. {d['symbol']} +{d['change']:.2f}% RSI:{d['rsi']:.0f}" for i,d in enumerate(scored_coins[:3])
    message = f"📊 BRIAN REPORT\n⏰ {time.strftime('%H:%M')}\n🧠 {verdict} | Avg: {avg_change:.2f}%\n🎯 {strategy}\n👑 Top3:\n{top3}\n🔒 Filtered: {scam_count}\n💼 Active: {len(positions)}{trade_msg}"
    await application.bot.send_message(chat_id=CHAT_ID, text=message)

async def trade_watcher():
    while True:
        await asyncio.sleep(60)
        global positions; positions = load_positions()
        for symbol, pos in list(positions.items()):
            try:
                current = exchange.fetch_ticker(symbol)['last']
                entry = pos['entry']; amount = pos['amount']
                if current <= entry * 0.95:
                    exchange.create_market_sell_order(symbol, amount)
                    await application.bot.send_message(CHAT_ID, f"🛑 AUTO SELL SL: {symbol} ${current:.4f}")
                    del positions[symbol]; save_positions(positions)
                elif current >= entry * 1.10:
                    exchange.create_market_sell_order(symbol, amount)
                    await application.bot.send_message(CHAT_ID, f"🎯 AUTO SELL TP: {symbol} ${current:.4f}")
                    del positions[symbol]; save_positions(positions)
            except: pass

def get_top_100_coins():
    markets = exchange.load_markets()
    return [s for s in markets if '/USDT' in s and markets[s]['active']][:100]

async def run_every(seconds, func):
    while True: 
        await func()
        await asyncio.sleep(seconds)

# FIXED MAIN - 1 EVENT LOOP ONLY
async def main_async():
    global application
    application = Application.builder().token(TOKEN).build()
    
    # Startup message
    await application.bot.send_message(CHAT_ID, "🤖 BRIAN V2 ONLINE\n24/7 Auto Trading + RSI + MA Analysis\nScanning: 100 coins\nEvery: 15min")
    
    # Start background tasks
    asyncio.create_task(run_every(900, research_and_trade)) # 15min scan
    asyncio.create_task(trade_watcher()) # 1min watcher
    
    await application.run_polling()


# KEEP RENDER ALIVE
def run_flask():
    app.run(host='0.0.0.0', port=10000)

@app.route('/')
def home():
    return "Brian is alive"

if __name__ == "__main__":
    threading.Thread(target=run_flask).start() # Keep Render awake
    asyncio.run(main_async())
