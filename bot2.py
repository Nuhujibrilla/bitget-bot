import ccxt
import time
import requests
import pandas as pd
import ta  # pip install ta
from datetime import datetime

# ==============================
# 1. WRITE YOUR KEYS HERE - NO BRACKETS
# ==============================
BITGET_KEY = bg_e20a831da9d95305247f7ebfe055590d
BITGET_SECRET =
30e290e99548c4f6a488f59ffd0f3cbd709df524076e1499923072ee004a4948
BITGET_PASSPHRASE = Nuhu2017

TELEGRAM_TOKEN = 8826348504:AAGNft0Nw3RB2r7P_F2sAQ8I0wji91u9BcU
TELEGRAM_CHAT_ID = 6261057148 

# ==============================
# 2. PRO BOT SETTINGS
# ==============================
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
LEVERAGE = 5
FIXED_USDT_PER_TRADE = 10  # $10 per trade
STOP_LOSS_ATR = 2.0
TAKE_PROFIT_RR = 2.0
TRADE_MODE = "spot"

# ==============================
# 3. CONNECT TO BITGET
# ==============================
exchange = ccxt.bitget({
    'apiKey': BITGET_KEY,
    'secret': BITGET_SECRET,
    'password': BITGET_PASSPHRASE,
    'enableRateLimit': True,
    'options': {'defaultType': TRADE_MODE}
})

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try: requests.post(url, data=payload)
    except Exception as e: print("Telegram Error:", e)

# ==============================
# 4. ANALYSIS ENGINE - RSI + MA + VOLUME
# ==============================
def analyze():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=200)
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

# ==============================
# 5. AUTO TRADE + STOP LOSS
# ==============================
def place_trade(signal, price, atr):
    balance = exchange.fetch_balance()
    usdt_balance = balance['USDT']['free']
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
        order = exchange.create_market_order(SYMBOL, side, quantity)
        exchange.create_order(SYMBOL, 'stop', side, quantity, None, {'stopPrice': sl_price, 'reduceOnly': True})
        exchange.create_order(SYMBOL, 'limit', 'sell' if side=='buy' else 'buy', quantity, tp_price, {'reduceOnly': True})
        
        msg = f"""
<b>✅ AUTO TRADE EXECUTED</b>
<b>Side:</b> {signal}
<b>Entry:</b> ${price:.2f}
<b>SL:</b> ${sl_price:.2f}
<b>TP:</b> ${tp_price:.2f}
<b>Reason:</b> {reason}
        """
        send_telegram(msg)
        
    except Exception as e:
        send_telegram(f"<b>❌ TRADE FAILED:</b> {e}")

# ==============================
# 6. MAIN LOOP
# ==============================
position = "NONE"
def main():
    global position
    send_telegram(f"🤖 <b>PRO BOT STARTED</b>\nMode: {TRADE_MODE} | {SYMBOL} | {TIMEFRAME}")
    
    while True:
        try:
            signal, price, atr, reason = analyze()
            print(f"{datetime.now()} - Signal: {signal} Price: {price}")
            
            if signal != "HOLD" and signal != position:
                place_trade(signal, price, atr)
                position = signal
                time.sleep(3600)
                
            time.sleep(60)
            
        except Exception as e:
            print("Loop Error:", e)
            time.sleep(60)

if __name__ == "__main__":
    main()
