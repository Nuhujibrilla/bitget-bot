from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import ccxt
import time
import requests
import pandas as pd
import ta
import os

# ========== KEYS FROM RENDER ==========
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET") 
API_PASSWORD = os.environ.get("API_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ======================================

exchange = ccxt.bitget({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'password': API_PASSWORD,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram keys missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_all_usdt_pairs():
    try:
        markets = exchange.load_markets()
        usdt_pairs = [s for s in markets if s.endswith('/USDT') and markets[s]['spot']]
        tickers = exchange.fetch_tickers(usdt_pairs)
        sorted_pairs = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True)
        coins = [s for s, _ in sorted_pairs] # NO LIMIT - scans ALL
        return coins
    except Exception as e:
        send_telegram(f"Error loading pairs: {e}")
        return ['BTC/USDT', 'ETH/USDT']

COINS = get_all_usdt_pairs()
TRADE_AMOUNT_USDT = 10  # $10 per trade
SL_PERCENT = 0.01  # 1% stop loss
TP_PERCENT = 0.02  # 2% take profit
TIMEFRAME = '15m'

def get_data(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except:
        return None

def check_signal(df):
    if df is None or len(df) < 50: 
        return None
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(df['close'], 200).ema_indicator()
    
    last = df.iloc[-1]
    if last['rsi'] < 35 and last['ema50'] > last['ema200'] and last['volume'] > df['volume'].mean():
        return "LONG"
    if last['rsi'] > 65 and last['ema50'] < last['ema200'] and last['volume'] > df['volume'].mean():
        return "SHORT"
    return None

def place_trade_with_sl_tp(symbol, signal):
    try:
        side = 'buy' if signal == "LONG" else 'sell'
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        amount = TRADE_AMOUNT_USDT / price
        amount = round(amount, 4) # round to 4 decimals

        # 1. PLACE MARKET ORDER
        order = exchange.create_market_order(symbol, side, amount)
        entry = order['average'] if order['average'] else price
        
        # 2. CALCULATE SL AND TP
        if side == 'buy':
            sl_price = entry * (1 - SL_PERCENT)
            tp_price = entry * (1 + TP_PERCENT)
        else: # sell
            sl_price = entry * (1 + SL_PERCENT)
            tp_price = entry * (1 - TP_PERCENT)
        
        sl_price = round(sl_price, 4)
        tp_price = round(tp_price, 4)

        # 3. PLACE SL AND TP ORDERS
        exchange.create_order(symbol, 'stop', 'sell' if side=='buy' else 'buy', amount, None, {'stopPrice': sl_price})
        exchange.create_order(symbol, 'limit', 'sell' if side=='buy' else 'buy', amount, tp_price)

        # 4. ALERT YOU
        msg = f"""✅ TRADE EXECUTED
Coin: {symbol}
Signal: {signal}
Side: {side.upper()}
Amount: ${TRADE_AMOUNT_USDT}
Entry: ${entry:.4f}
SL: ${sl_price:.4f} (-1%)
TP: ${tp_price:.4f} (+2%)
OrderID: {order['id']}"""
        send_telegram(msg)
        
    except Exception as e:
        send_telegram(f"❌ TRADE FAILED: {symbol} - {str(e)}")

def scan():
    send_telegram(f"🤖 BRIAN IS ONLINE\nScanning {len(COINS)} coins every 15min\nMode: AUTO TRADE | ${TRADE_AMOUNT_USDT}/trade | SL:1% TP:2%")
    traded_coins = set() # to avoid buying same coin twice
    
    while True:
        signals = 0
        for symbol in COINS:
            # Skip if we already have a position
            try:
                balance = exchange.fetch_balance()
                base = symbol.split('/')[0]
                if balance[base]['free'] > 0:
                    continue
            except: pass
            
            df = get_data(symbol)
            signal = check_signal(df)
            if signal:
                signals += 1
                send_telegram(f"🚨 SIGNAL FOUND: {symbol} {signal}\nAuto-buying now...")
                place_trade_with_sl_tp(symbol, signal)
                time.sleep(3)
        print(f"Scan complete. {signals} signals found")
        time.sleep(900) # 15 minutes

async def chat_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.lower()
    if "hi" in msg or "hello" in msg:
        await update.message.reply_text("👋 Hi bro! BRIAN is live and scanning 1106 coins.\n\nSend /status to see what's up")
    elif "status" in msg:
        await update.message.reply_text("✅ BRIAN is online and scanning every 15 minutes")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ BRIAN is online and scanning every 15 minutes")

if __name__ == "__main__":
    import threading
    threading.Thread(target=scan, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_reply))
    app.run_polling()
