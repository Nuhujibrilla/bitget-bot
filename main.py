from flask import Flask
import threading, time, requests, os, asyncio, ccxt, json, pandas as pd, datetime
import ta, nest_asyncio 
nest_asyncio.apply() 
from telegram.ext import Application

app = Flask('') 

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TRADE_AMOUNT = 10 # $10 per trade
MIN_VOLUME = 10000000 # $10M 24h vol
SL_PERCENT = 5 # Stop Loss 5%
TP_PERCENT = 15 # Take Profit 15%
SCAN_INTERVAL = 600 # 10 minutes
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
    await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')

def analyze_market(df):
    last = df.iloc[-1]
    signal = "HOLD"
    reason = []
    
    # 1. TREND: Price above MA200 = Bullish
    if last['close'] > last['ma200']: reason.append("Above MA200 Trend")
    
    # 2. MOMENTUM: MA20 > MA50 = Golden Cross
    if last['ma20'] > last['ma50']: reason.append("Golden Cross")
    
    # 3. RSI: Not overbought
    if 45 < last['rsi'] < 70: reason.append(f"RSI Healthy: {last['rsi']:.0f}")
    
    # 4. VOLUME: 2x average
    if last['volume'] > last['avg_vol'] * 2: reason.append("Volume Spike 2x")
    
    # 5. PUMP: 1h > 3%
    change_1h = ((last['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
    if change_1h > 3: reason.append(f"1h Pump: +{change_1h:.1f}%")
    
    if len(reason) >= 3: signal = "BUY"
    return signal, " | ".join(reason), change_1h

async def check_positions():
    global positions
    for symbol, data in list(positions.items()):
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            entry = data['entry']
            pnl = ((current_price - entry) / entry) * 100
            
            # CHECK SL
            if pnl <= -SL_PERCENT:
                exchange.create_market_sell_order(symbol, data['amount'])
                await send_alert(f"🚨 <b>STOP LOSS HIT</b> 🚨\n<b>Pair:</b> {symbol}\n<b>Entry:</b> ${entry:.5f}\n<b>Exit:</b> ${current_price:.5f}\n<b>P&L:</b> {pnl:.2f}%\n<b>Reason:</b> -{SL_PERCENT}% SL")
                del positions[symbol]
                
            # CHECK TP
            elif pnl >= TP_PERCENT:
                exchange.create_market_sell_order(symbol, data['amount'])
                await send_alert(f"🎯 <b>TAKE PROFIT HIT</b> 🎯\n<b>Pair:</b> {symbol}\n<b>Entry:</b> ${entry:.5f}\n<b>Exit:</b> ${current_price:.5f}\n<b>P&L:</b> +{pnl:.2f}%\n<b>Reason:</b> +{TP_PERCENT}% TP")
                del positions[symbol]
            else:
                await send_alert(f"💼 <b>HOLDING:</b> {symbol}\n<b>Entry:</b> ${entry:.5f} | <b>Now:</b> ${current_price:.5f} | <b>P&L:</b> {pnl:.2f}%")
            save_positions(positions)
        except Exception as e:
            print(f"Error checking {symbol}: {e}")

async def research_and_trade():
    market_direction = "UNKNOWN"
    try:
        # 1. CHECK MARKET DIRECTION FIRST
        btc_df = pd.DataFrame(exchange.fetch_ohlcv('BTC/USDT', '1h', limit=200), columns=['t','o','h','l','c','v'])
        btc_df['ma200'] = ta.trend.SMAIndicator(btc_df['c'], 200).sma_indicator()
        if btc_df.iloc[-1]['c'] > btc_df.iloc[-1]['ma200']: market_direction = "BULLISH 🟢"
        else: market_direction = "BEARISH 🔴"
        
        await send_alert(f"🧠 <b>BRAIN SCAN START</b>\n<b>Market Direction:</b> {market_direction}")
        
        coins = get_top_100_coins()
        best_coin = None
        best_score = 0
        best_reason = ""

        for symbol in coins:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=200)
                df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
                df['ma20'] = ta.trend.SMAIndicator(df['c'], 20).sma_indicator()
                df['ma50'] = ta.trend.SMAIndicator(df['c'], 50).sma_indicator()
                df['ma200'] = ta.trend.SMAIndicator(df['c'], 200).sma_indicator()
                df['avg_vol'] = df['v'].rolling(20).mean()
                
                if df.iloc[-1]['v'] < MIN_VOLUME: continue
                
                signal, reason, change = analyze_market(df)
                
                if signal == "BUY" and symbol not in positions:
                    score = len(reason.split('|'))
                    if score > best_score:
                        best_score = score
                        best_coin = symbol
                        best_reason = reason
            except: pass
            await asyncio.sleep(0.1)

        # 2. AUTO BUY IF SIGNAL FOUND
        if best_coin and market_direction == "BULLISH 🟢":
            ticker = exchange.fetch_ticker(best_coin)
            price = ticker['last']
            amount = TRADE_AMOUNT / price
            order = exchange.create_market_buy_order(best_coin, amount)
            positions[best_coin] = {'entry': price, 'amount': amount, 'time': str(datetime.datetime.now())}
            save_positions(positions)
            await send_alert(f"""🚨 <b>NEW AUTO TRADE EXECUTED</b> 🚨

<b>Pair:</b> {best_coin}
<b>Action:</b> BUY ${TRADE_AMOUNT}
<b>Price:</b> ${price:.5f}
<b>Amount:</b> {amount:.4f}

<b>BRAIN ANALYSIS:</b>
{best_reason}

<b>RISK MANAGEMENT:</b>
SL: -{SL_PERCENT}% | TP: +{TP_PERCENT}%
<b>Market:</b> {market_direction}""")
        else:
            await send_alert(f"📊 <b>SCAN COMPLETE</b>\nNo strong BUY signal found.\n<b>Market:</b> {market_direction}\n<b>Best Score:</b> {best_score}/5")

    except Exception as e:
        await send_alert(f"🚨 SCAN CRASHED: `{str(e)}`")

async def trade_watcher():
    while True:
        await check_positions()
        await asyncio.sleep(60) # Check SL/TP every 1 min

def get_top_100_coins():
    markets = exchange.load_markets()
    return [s for s in markets if '/USDT' in s and markets[s]['active']][:100]

async def run_every(seconds, func):
    while True: await func(); await asyncio.sleep(seconds)
async def keep_alive():
    while True: 
        try: requests.get("https://bitget-bot-sg5v.onrender.com")
        except: pass
        await asyncio.sleep(240)
def run_flask(): app.run(host='0.0.0.0', port=10000)
@app.route('/')
def home(): return "Brian is alive"

async def main():
    global application
    application = Application.builder().token(TOKEN).build()
    await send_alert(f"🤖 <b>BRIAN V10 ONLINE</b>\nFull Auto Trading Active\nScan: Every 10min | SL: {SL_PERCENT}% | TP: {TP_PERCENT}%")
    asyncio.create_task(run_every(SCAN_INTERVAL, research_and_trade))
    asyncio.create_task(trade_watcher())
    asyncio.create_task(keep_alive())
    await application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
