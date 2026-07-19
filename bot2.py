import ccxt
import time
import requests
import pandas as pd
import ta
from datetime import datetime

# ==============================
# 1. ONLY PASTE INSIDE THE QUOTES BELOW. DON'T DELETE QUOTES
# ==============================
BITGET_KEY = "bg_e20a831da9d95305247f7ebfe055590d"
BITGET_SECRET = "30e290e99548c4f6a488f59ffd0f3cbd709df524076e1499923072ee004a4948"
BITGET_PASSPHRASE = "Nuhu2017"

TELEGRAM_TOKEN = "8826348504:AAF9MYvnrix5h2jHW-uqtvOiM_7171CXMWo"
TELEGRAM_CHAT_ID = "6261057148"
# ==============================

# ==============================
# 2. BRIAN PRO SETTINGS - DO NOT TOUCH
# ==============================
COIN_LIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "TON/USDT", "AVAX/USDT", "LINK/USDT"]
TIMEFRAME = "15m"
FIXED_USDT_PER_TRADE = 10
STOP_LOSS_ATR = 2.0
TAKE_PROFIT_RR = 2.0
TRADE_MODE = "spot"
MAX_TRADES_AT_ONCE = 3

exchange = ccxt.bitget({
    'apiKey': BITGET_KEY,
    'secret': BITGET_SECRET,
    'password': BITGET_PASSPHRASE,
    'enableRateLimit': True,
    'options': {'defaultType': TRADE_MODE}
})

open_positions = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try: requests.post(url, data=payload)
    except Exception as e: print("Telegram Error:", e)

def analyze_coin(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=200)
        df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['ma20'] = ta.trend.sma_indicator(df['close'], window=20)
        df['ma50'] = ta.trend.sma_indicator(df['close'], window=50)
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        df['vol_ma'] = df['volume'].rolling(20).mean()
        last = df.iloc[-1]
        prev = df.iloc[-2]
        signal = "HOLD"
        reason = ""
        if prev['ma20'] < prev['ma50'] and last['ma20'] > last['ma50'] and last['rsi'] > 50 and last['volume'] > last['vol_ma']:
            signal = "LONG"
            reason = "MA Cross UP + RSI > 50 + High Volume"
        elif prev['ma20'] > prev['ma50'] and last['ma20'] < last['ma50'] and last['rsi'] < 50 and last['volume'] > last['vol_ma']:
            signal = "SHORT"
            reason = "MA Cross DOWN + RSI < 50 + High Volume"
        return signal, last['close'], last['atr'], reason
    except Exception as e:
        return "HOLD", 0, 0, str(e)

def place_trade(symbol, signal, price, atr, reason):
    trade_amount_usdt = FIXED_USDT_PER_TRADE
    sl_distance = atr * STOP_LOSS_ATR
    tp_distance = sl_distance * TAKE_PROFIT_RR
    if signal == "LONG":
        sl_price = price - sl_distance
        tp_price = price + tp_distance
        side = 'buy'
    else:
        sl_price = price + sl_distance
        tp_price = price - tp_distance
        side = 'sell'
    quantity = trade_amount_usdt / price
    try:
        order = exchange.create_market_order(symbol, side, quantity)
        exchange.create_order(symbol, 'stop', 'sell' if side=='buy' else 'buy', quantity, None, {'stopPrice': sl_price, 'reduceOnly': True})
        exchange.create_order(symbol, 'limit', 'sell' if side=='buy' else 'buy', quantity, tp_price, {'reduceOnly': True})
        open_positions[symbol] = signal
        msg = f"<b>✅ BRIAN EXECUTED TRADE</b>\n<b>Coin:</b> {symbol}\n<b>Side:</b> {signal}\n<b>Entry:</b> ${price:.4f}\n<b>SL:</b> ${sl_price:.4f}\n<b>TP:</b> ${tp_price:.4f}\n<b>Reason:</b> {reason}"
        send_telegram(msg)
    except Exception as e:
        send_telegram(f"<b>❌ TRADE FAILED {symbol}:</b> {e}")

def main():
    send_telegram(f"🤖 <b>BRIAN IS ONLINE</b>\nScanning {len(COIN_LIST)} coins every 15min\nMode: {TRADE_MODE} | ${FIXED_USDT_PER_TRADE}/trade | NO WITHDRAW PERMISSION")
    while True:
        try:
            print(f"\n--- BRIAN SCANNING AT {datetime.now()} ---")
            for symbol in COIN_LIST:
                if symbol in open_positions: continue
                if len(open_positions) >= MAX_TRADES_AT_ONCE: break
                signal, price, atr, reason = analyze_coin(symbol)
                print(f"{symbol}: {signal}")
                if signal!= "HOLD" and atr > 0:
                    place_trade(symbol, signal, price, atr, reason)
                    time.sleep(5)
            time.sleep(900)
        except Exception as e:
            print("Loop Error:", e)
            send_telegram(f"<b>❌ BRIAN ERROR:</b> {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
