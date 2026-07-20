import ccxt
import time
import requests
import pandas as pd
import ta
import datetime
import os # THIS LETS US READ KEYS FROM RENDER

# ========== KEYS COME FROM RENDER ENVIRONMENT ==========
API_KEY = os.environ.get("API_KEY"bg_e20a831da9d95305247f7ebfe055590d
API_SECRET = os.environ.get("API_SECRET"30e290e99548c4f6a488f59ffd0f3cbd709df524076e1499923072ee004a4948
API_PASSWORD = os.environ.get("API_PASSWORD"Nuhu2017
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN"8826348504:AAF9MYvnrix5h2jHW-uqtvOiM_7171CXMWo
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID"6261057148
# ====================================================

exchange = ccxt.bitget({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'password': API_PASSWORD,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

def get_all_usdt_pairs():
    markets = exchange.load_markets()
    usdt_pairs = [s for s in markets if s.endswith('/USDT') and markets[s]['spot']]
    tickers = exchange.fetch_tickers(usdt_pairs)
    sorted_pairs = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True)
    coins = [s.replace('/', '') for s, _ in sorted_pairs[:150]]
    return coins

COINS = get_all_usdt_pairs()
TRADE_AMOUNT = 10 # $10 per trade
TIMEFRAME = '15m'
MAX_TRADES = 3

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=data)

def get_data(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except:
        return None

def check_signal(df):
    if df is None or len(df) < 50: return None
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(df['close'], 200).ema_indicator()
    
    last = df.iloc[-1]
    if last['rsi'] < 35 and last['ema50'] > last['ema200'] and last['volume'] > df['volume'].mean():
        return "LONG"
    if last['rsi'] > 65 and last['ema50'] < last['ema200'] and last['volume'] > df['volume'].mean():
        return "SHORT"
    return None

def place_trade(symbol, side):
    try:
        amount = TRADE_AMOUNT / exchange.fetch_ticker(symbol)['last']
        order = exchange.create_market_order(symbol, side, amount)
        entry = order['average']
        sl = entry * 0.99 if side == 'buy' else entry * 1.01
        tp = entry * 1.02 if side == 'buy' else entry * 0.98
        send_telegram(f"✅ TRADE EXECUTED\n{symbol} {side.upper()}\nEntry: ${entry:.4f}\nSL: ${sl:.4f} | TP: ${tp:.4f}")
    except Exception as e:
        send_telegram(f"❌ TRADE FAILED: {symbol} - {str(e)}")

def scan():
    send_telegram(f"🤖 BRIAN IS ONLINE\nScanning {len(COINS)} coins every 15min\nMode: spot | ${TRADE_AMOUNT}/trade")
    while True:
        signals = 0
        for symbol in COINS:
            df = get_data(symbol)
            signal = check_signal(df)
            if signal:
                signals += 1
                side = 'buy' if signal == "LONG" else 'sell'
                send_telegram(f"🚨 SIGNAL: {symbol} {signal}")
                place_trade(symbol, side)
                time.sleep(2)
        print(f"Scan complete. {signals} signals found")
        time.sleep(900)

if __name__ == "__main__":
    scan()
