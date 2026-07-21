import os, time, threading, asyncio, ccxt, json
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
            ticker = exchange.fetch_ticker(symbol)
            change = ticker['percentage']
            volume = ticker['quoteVolume']
            price = ticker['last']

            if volume < MIN_VOLUME: scam_count +=1; continue
            if price > 5 and change is not None and change > 0.5: # Added "is not None"
                score = change + (volume / 1000000)
                scored_coins.append({'symbol': symbol, 'price': price, 'change': change, 'score': score})
        except: pass

    if not scored_coins:
        await application.bot.send_message(CHAT_ID, "📊 BRIAN REPORT\nNo safe coins found this scan.")
        return

    scored_coins.sort(key=lambda x: x['score'], reverse=True)
    best = scored_coins[0]
    avg_change = sum(d['change'] for d in scored_coins) / len(scored_coins)

    # MARKET STRATEGY
    if avg_change > 2: verdict = "BULLISH 🔥"; strategy = "Trend-following. Take quick profits."
    elif avg_change < -2: verdict = "BEARISH 🐻"; strategy = "Use tight SL. Only high conviction."
    else: verdict = "SIDEWAYS 😐"; strategy = "Buy dips, Sell rips."

    # AUTO BUY IF BULLISH
    trade_msg = ""
    if avg_change > 1 and best['change'] > 3 and best['symbol'] not in positions:
        try:
            amount_coin = TRADE_AMOUNT / best['price']
            exchange.create_market_buy_order(best['symbol'], amount_coin)
            positions[best['symbol']] = {'entry': best['price'], 'amount': amount_coin}
            save_positions(positions)
            trade_msg = f"\n🚨 AUTO BUY EXECUTED!\n{best['symbol']} @ ${best['price']:.4f}\nSL: -5% | TP: +10%"
        except Exception as e: trade_msg = f"\n❌ Buy failed: {e}"

    top3 = "\n".join([f"{i+1}. {d['symbol']} +{d['change']:.2f}%" for i,d in enumerate(scored_coins[:3])])
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

def main():
    global application
    application = Application.builder().token(TOKEN).build()
    # Startup message
    asyncio.run(application.bot.send_message(CHAT_ID, "🤖 BRIAN IS ONLINE\n24/7 Auto Trading Started"))
    threading.Thread(target=lambda: asyncio.run(run_every(900, research_and_trade)), daemon=True).start() # 15min
    threading.Thread(target=lambda: asyncio.run(trade_watcher()), daemon=True).start() # 1min
    application.run_polling()

async def run_every(seconds, func):
    while True: await func(); await asyncio.sleep(seconds)

if __name__ == "__main__": main()
