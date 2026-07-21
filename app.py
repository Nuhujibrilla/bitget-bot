from flask import Flask
import threading, time, requests, os, asyncio
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
    await send_alert(f"🧠 <b>BRIAN FULL MARKET SCAN</b>\n⏰ {datetime.datetime.now().strftime('%H:%M')} WAT")
    try:
        markets = exchange.load_markets()
        coins = [s for s in markets if '/USDT' in s and markets[s]['active']][:100]
        
        scanned = []
        btc_price = exchange.fetch_ticker('BTC/USDT')['last']
        eth_price = exchange.fetch_ticker('ETH/USDT')['last']

        for symbol in coins:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
                df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
                df['ma50'] = ta.trend.SMAIndicator(df['c'], 50).sma_indicator()
                df['ma200'] = ta.trend.SMAIndicator(df['c'], 200).sma_indicator()
                
                ticker = exchange.fetch_ticker(symbol)
                vol_24h = ticker['quoteVolume']
                if vol_24h < MIN_VOLUME: continue
                
                change_1h = ((df.iloc[-1]['c'] - df.iloc[-2]['c']) / df.iloc[-2]['c']) * 100
                change_24h = ticker['percentage']
                
                scanned.append({
                    'symbol': symbol,
                    'price': df.iloc[-1]['c'],
                    'change_1h': change_1h,
                    'change_24h': change_24h,
                    'vol': vol_24h,
                    'rsi': df.iloc[-1]['rsi'],
                    'above_ma50': df.iloc[-1]['c'] > df.iloc[-1]['ma50']
                })
            except: pass
            await asyncio.sleep(0.1)

        scanned.sort(key=lambda x: x['change_24h'], reverse=True)
        total = len(scanned)
        bullish = sum(1 for d in scanned if d['above_ma50'])
        avg_24h = sum(d['change_24h'] for d in scanned) / total if total > 0 else 0
        top3 = scanned[:3]

        report = f"""📌 <b>BRIAN MARKET REPORT</b>
⚠️ <b>Top 100 Scan Complete</b>

<b>Time:</b> {datetime.datetime.now().strftime('%H:%M')} WAT
<b>Scanned:</b> {total}/100 Coins | <b>Min Vol:</b> $10M
<b>Exchange:</b> BITGET | <b>Type:</b> SPOT

💰 <b>BTC:</b> ${btc_price:,.2f} | <b>ETH:</b> ${eth_price:,.2f}
📊 <b>Market Breadth:</b> {bullish}/{total} above MA50
📈 <b>Avg 24h Move:</b> {avg_24h:.2f}%

━━━━━━━━━━━━
👑 <b>TOP 3 GAINERS</b>"""
        for i, coin in enumerate(top3, 1):
            report += f"""
{i}. <b>{coin['symbol']}</b>
   Price: ${coin['price']:.5f} | 1h: {coin['change_1h']:.2f}% | 24h: {coin['change_24h']:.2f}%
   Vol: ${coin['vol']/1000000:.1f}M | RSI: {coin['rsi']:.0f}"""
        
        report += "\n━━━━━━━━━━━━"
        
        best = top3[0] if top3 else None
        if best and best['change_1h'] > 3 and best['rsi'] < 70 and best['above_ma50']:
            if best['symbol'] not in positions:
                price = best['price']
                amount = TRADE_AMOUNT / price
                exchange.create_market_buy_order(best['symbol'], amount)
                positions[best['symbol']] = {'entry': price, 'amount': amount}
                save_positions(positions)
                report += f"""
🚨 <b>AUTO TRADE EXECUTED</b> 🚨
<b>Bought:</b> {best['symbol']} ${TRADE_AMOUNT}
<b>Reason:</b> Top gainer + Trend + RSI Healthy
<b>SL:</b> -{SL_PERCENT}% | <b>TP:</b> +{TP_PERCENT}%"""
        else:
            report += "\n🎯 <b>NO TRADE:</b> No strong signal found"
            
        report += "\n\nDYOR/NFA: Automated report."
        await send_alert(report)

    except Exception as e:
        await send_alert(f"🚨 ERROR: {str(e)}")

async def check_positions():
    global positions
    for symbol in list(positions.keys()):
        try:
            price = exchange.fetch_ticker(symbol)['last']
            entry = positions[symbol]['entry']
            pnl = ((price - entry) / entry) * 100
            if pnl <= -SL_PERCENT:
                exchange.create_market_sell_order(symbol, positions[symbol]['amount'])
                await send_alert(f"🚨 <b>STOP LOSS</b> {symbol} P&L: {pnl:.2f}%")
                del positions[symbol]
            elif pnl >= TP_PERCENT:
                exchange.create_market_sell_order(symbol, positions[symbol]['amount'])
                await send_alert(f"🎯 <b>TAKE PROFIT</b> {symbol} P&L: +{pnl:.2f}%")
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
    await send_alert("🤖 <b>BRIAN V12.1 ONLINE</b>\nFull Market Reports Every 10min")
    asyncio.create_task(run_every(SCAN_INTERVAL, research_and_trade))
    asyncio.create_task(run_every(60, check_positions))
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
