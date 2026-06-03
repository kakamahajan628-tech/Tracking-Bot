import time
from datetime import datetime
import ccxt
import pandas as pd
import numpy as np
import ta
import os
from threading import Thread
from flask import Flask
from colorama import Fore, Style, init

init(autoreset=True)

# --- RENDER PORT BINDING SYSTEM ---
# Flask app handles dummy web traffic so Render keeps the background bot alive 24/7
app = Flask('')

@app.route('/')
def home():
    return "Institutional Scalper V6 Engine is Running Seamlessly Background.", 200

def run_web_server():
    # Render automatically assigns a PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- CORE TRADING ENGINE ---
class InstitutionalScalperV6:
    def __init__(self, symbols):
        self.exchange = ccxt.gate({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'timeout': 20000,
            'headers': {'User-Agent': 'Mozilla/5.0'}
        })
        self.symbols = symbols
        self.timeframes = ['1m', '5m', '15m']
        self.persistence_tracker = {symbol: 0 for symbol in symbols}

    def safe_api_call(self, func, *args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except ccxt.RateLimitExceeded:
                time.sleep(4)
            except (ccxt.NetworkError, ccxt.RequestTimeout):
                time.sleep(2)
        return None

    def fetch_open_interest_safely(self, symbol):
        try:
            market_id = symbol.split(':')[0] if ':' in symbol else symbol
            oi_data = self.safe_api_call(self.exchange.fetch_open_interest, market_id)
            if oi_data and len(oi_data) > 0:
                return float(oi_data[0]['openInterestAmount']) if 'openInterestAmount' in oi_data[0] else None
            return None
        except Exception:
            return None

    def get_confirmed_pivots(self, df, left_bars=4, right_bars=4):
        highs = df['high'].values
        lows = df['low'].values
        size = len(df)
        pivot_highs, pivot_lows = [], []
        
        for i in range(left_bars, size - right_bars):
            if all(highs[i] > highs[i - l] for l in range(1, left_bars + 1)) and \
               all(highs[i] >= highs[i + r] for r in range(1, right_bars + 1)):
                pivot_highs.append((i, highs[i]))
            if all(lows[i] < lows[i - l] for l in range(1, left_bars + 1)) and \
               all(lows[i] <= lows[i + r] for r in range(1, right_bars + 1)):
                pivot_lows.append((i, lows[i]))
        return pivot_highs, pivot_lows

    def analyze_divergence_and_mss(self, df):
        p_highs, p_lows = self.get_confirmed_pivots(df)
        closes = df['close'].values
        rsi = df['rsi'].values
        
        mss = False
        if p_lows:
            last_low = p_lows[-1][1]
            if closes[-1] < last_low and closes[-2] < last_low:
                mss = True
                
        bearish_div = False
        if len(p_highs) >= 2:
            idx1, peak1 = p_highs[-2]
            idx2, peak2 = p_highs[-1]
            if peak2 > peak1 and rsi[idx2] < rsi[idx1]:
                bearish_div = True
                
        return mss, bearish_div

    def run_quantitative_indicators(self, df):
        df['ema_20'] = ta.trend.ema_indicator(df['close'], window=20)
        df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['macd_hist'] = ta.trend.MACD(df['close']).macd_diff()
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        return df

    def evaluate_asset_metrics(self, symbol):
        all_tickers = self.safe_api_call(self.exchange.fetch_tickers, [symbol])
        if not all_tickers or symbol not in all_tickers:
            return
            
        live_price = all_tickers[symbol]['last']
        tf_data = {}
        
        for tf in self.timeframes:
            candles = self.safe_api_call(self.exchange.fetch_ohlcv, symbol, tf, limit=250)
            if not candles or len(candles) < 60:
                return
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = self.run_quantitative_indicators(df)
            tf_data[tf] = df

        m1_df, m5_df, m15_df = tf_data['1m'], tf_data['5m'], tf_data['15m']
        i1, i5, i15 = m1_df.index[-1], m5_df.index[-1], m15_df.index[-1]
        p_i1, p_i15 = m1_df.index[-2], m15_df.index[-2]
        
        m1_mss, m1_div = self.analyze_divergence_and_mss(m1_df)
        m5_mss, _ = self.analyze_divergence_and_mss(m5_df)
        m15_mss, _ = self.analyze_divergence_and_mss(m15_df)

        score = 0
        if m1_mss: score += 10
        if m5_mss: score += 25
        if m15_mss: score += 35
        if m1_div: score += 15
        
        macd_weakening_1m = m1_df.loc[i1, 'macd_hist'] < m1_df.loc[p_i1, 'macd_hist']
        if m1_df.loc[i1, 'rsi'] > 70 and macd_weakening_1m:
            score += 15
            
        atr_ma_50 = m1_df['atr'].tail(50).mean()
        atr_ratio = m1_df.loc[i1, 'atr'] / atr_ma_50 if atr_ma_50 > 0 else 1.0
        if atr_ratio > 1.5:
            score += 10

        price_up_15m = m15_df.loc[i15, 'close'] > m15_df.loc[p_i15, 'close']
        oi_now = self.fetch_open_interest_safely(symbol)
        time.sleep(0.1)
        
        if oi_now and price_up_15m:
            score += 15

        hyper_bullish_15m = m15_df.loc[i15, 'ema_20'] > m15_df.loc[i15, 'ema_50'] and m15_df.loc[i15, 'adx'] > 32 and m15_df.loc[i15, 'rsi'] > 65
        if hyper_bullish_15m and not m5_mss:
            print(f"❌ {symbol} | Price: {live_price} | SHORT BLOCKED - Parabolic Trend (15m-ADX: {m15_df.loc[i15, 'adx']:.1f})")
            self.persistence_tracker[symbol] = 0
            return

        if score >= 75:
            self.persistence_tracker[symbol] += 1
        else:
            self.persistence_tracker[symbol] = 0

        print(f"📊 {symbol} | Price: {live_price} | Score: {score:.1f}/100 | Loops: {self.persistence_tracker[symbol]}")
        
        if self.persistence_tracker[symbol] >= 3:
            print(f"🚨 [🚨 ENTRY TRIGGER] {symbol} Confirmed Exhaustion State Across Matrix Grid Layers!")
            self.persistence_tracker[symbol] = 0

def run_bot_loop():
    GATE_V6_WATCHLIST = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT', 'SUI/USDT:USDT']
    bot = InstitutionalScalperV6(symbols=GATE_V6_WATCHLIST)
    print("[BOT ENGINE] High Frequency Production Pass Loop Engaged.")
    while True:
        for asset in GATE_V6_WATCHLIST:
            bot.evaluate_asset_metrics(asset)
            time.sleep(0.5)
        time.sleep(15)

if __name__ == "__main__":
    # Step 1: Start the web port binding server inside a parallel daemon background thread
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    # Step 2: Start the sequential technical scanning engine loop
    run_bot_loop()
