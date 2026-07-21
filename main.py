from flask import Flask
import threading
import time
import requests
import os, asyncio, ccxt, json, pandas as pd
import ta
from telegram.ext import Application

app = Flask('') # Keep Render alive

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TRADE_AMOUNT = 10
MIN_VOLUME = 5000000
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

async def send_alert(msg):
    await application.bot.send_message(chat_id=CHAT_ID, text=msg)

async def research_and_trade():
    coins = get_top_100_coins()
    scored_coins = []
    scam_count = 0
    bullish_count = 0
    bearish_count = 0

    for symbol in coins:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=200)
            if len(ohlcv) < 50: continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            df['ma20'] = ta.trend.SMAIndicator(df['close'], window=20).sma_indicator()
            df['ma50'] = ta.trend.SMAIndicator(df['close'], window=50).sma_indicator()
            df['ma200'] = ta.trend.SMAIndicator(df['close'], window=200).sma_indicator()
            df['avg_vol'] = df['volume'].rolling(window=20).mean()
            last = df.iloc[-1]; prev = df.iloc[-2]
            change = ((last['close'] - prev['close']) / prev['close']) * 100
            volume = last['volume']; price = last['close']
            if volume < MIN_VOLUME: scam_count +=1; continue
            if change > 0: bullish_count += 1
            else: bearish_count += 1
            is_uptrend = last['ma20'] > last['ma50']
            is_not_overbought = last['rsi'] < 70 and last['rsi'] > 50
            is_high_volume = volume > (last['avg_vol'] * 1.5)
            is_strong_move = change > 2.0
            if is_uptrend and is_not_overbought and is_high_volume and is_strong_move:
                score = change + (volume / 1000000) + last['rsi']
                scored_coins.append({'symbol': symbol, 'price': price, 'change': change, 'rsi': last['rsi'], 'ma20': last['ma20'], 'ma50': last['ma50'], 'score': score, 'volume': volume, 'above_ma200': last['close'] > last['ma200']})
        except: pass

    if not scored_coins:
        await send_alert(f"📊 BRIAN SCAN\n⏰ {time.strftime('%H:%M')}\nNo coins passed check.\nMarket is dead.")
        return

    scored_coins.sort(key=lambda x: x['score'], reverse=True)
    best = scored_coins[0]
    avg_change = sum(d['change'] for d in scored_coins) / len(scored_coins)
    total_scanned = len(scored_coins) + scam_count
    bull_ratio = (bullish_count / total_scanned) * 100
    if avg_change > 4: verdict = "BULLISH STRONG 🔥🔥"; strategy = "Ride trend. Take quick 10% profits."
    elif avg_change > 2: verdict = "BULLISH 🔥"; strategy = "Trend-following. Scale in."
    elif avg_change < -2: verdict = "BEARISH 🐻"; strategy = "Use tight SL. Only scalp."
    else: verdict = "SIDEWAYS 😐"; strategy = "Buy dips, Sell rips. No FOMO."

    if avg_change > 1 and best['change'] > 3 and best['symbol'] not in positions:
        try:
            amount_coin = TRADE_AMOUNT / best['price']
            sl_price = best['price'] * 0.95
            tp_price = best['price'] * 1.10
            order = exchange.create_market_buy_order(best['symbol'], amount_coin)
            positions[best['symbol']] = {'entry': best['price'], 'amount': amount_coin, 'time': time.strftime('%H:%M')}
            save_positions(positions)
            alert_msg = f"""🚨 NEW TRADE ALERT 🚨
Coin: {best['symbol']}
Entry: ${best['price']:.6f} | Amount: ${TRADE_AMOUNT}
SL: ${sl_price:.6f} (-5%) | TP: ${tp_price:.6f} (+10%)
Market: {verdict}"""
            await send_alert(alert_msg)
        except Exception as e:
            await send_alert(f"❌ Buy failed: {best['symbol']} Error: {e}")

    top5 = "\n".join([f"{i+1}. {d['symbol']} +{d['change']:.2f}%" for i,d in enumerate(scored_coins[:5])])
    market_opinion = f"Best play: {best['symbol']}" if len(scored_coins) >= 1 else "Market is trash. Sitting in cash."
    holdings = "\n💼 Active Positions:\n" + "\n".join([f"- {k} @ ${v['entry']:.4f}" for k,v in positions.items()]) if positions else "\n💼 Active Positions: None."
    full_report = f"""📊 BRIAN MARKET ANALYSIS
⏰ {time.strftime('%H:%M')} | Scan: {total_scanned} coins
🧠 SENTIMENT: {verdict}
📈 Bullish: {bullish_count} | Bearish: {bearish_count}
🎯 STRATEGY: {strategy}
👑 TOP 5:
{top5}
🔍 TAKE: {market_opinion}{holdings}"""
    await send_alert(full_report)

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
                    profit = ((current-entry)/entry)*100
                    await send_alert(f"🛑 SL SELL\n{symbol}\nP&L: {profit:.2f}%")
                    del positions[symbol]; save_positions(positions)
                elif current >= entry * 1.10:
                    exchange.create_market_sell_order(symbol, amount)
                    profit = ((current-entry)/entry)*100
                    await send_alert(f"🎯 TP SELL\n{symbol}\nP&L: +{profit:.2f}%")
                    del positions[symbol]; save_positions(positions)
            except: pass

def get_top_100_coins():
    markets = exchange.load_markets()
    return [s for s in markets if '/USDT' in s and markets[s]['active']][:100]

async def run_every(seconds, func):
    while True:
        await func()
        await asyncio.sleep(seconds)

# KEEP ALIVE FUNCTION
async def keep_alive():
    while True:
        try: requests.get("https://bitget-bot-sg5v.onrender.com")
        except: pass
        await asyncio.sleep(240)

def run_flask():
    app.run(host='0.0.0.0', port=10000, use_reloader=False) # FIX: no reloader

@app.route('/')
def home():
    return "Brian is alive"

async def main():
    global application
    application = Application.builder().token(TOKEN).build()
    await send_alert("🤖 BRIAN V4 ONLINE\nKeep Alive + 15min Analysis Active")
    asyncio.create_task(run_every(900, research_and_trade))
    asyncio.create_task(trade_watcher())
    asyncio.create_task(keep_alive())
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start() # FIX: daemon thread
    asyncio.run(main())
