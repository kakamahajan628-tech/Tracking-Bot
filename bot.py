import time
from datetime import datetime
import ccxt
import pandas as pd
import numpy as np
import ta
import os
import requests
from threading import Thread
from flask import Flask

# --- GLOBAL LIVE WATCHLIST ---
# Initial memory state. These can be fully modified live via Telegram /add and /remove commands!
TRACKED_COINS = ['BTC/USDT:USDT', 'ETH/USDT:USDT']

# Global persistence dictionary shared across threads
PERSISTENCE_TRACKER = {symbol: 0 for symbol in TRACKED_COINS}

# Global dictionary to cache the latest scanned metrics for instant reports
LATEST_METRICS_CACHE = {}

# --- RENDER PORT BINDING SYSTEM ---
app = Flask('')

@app.route('/')
def home():
    return "Institutional Scalper V10 Control Panel Active.", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- TELEGRAM API WRAPPERS ---
def send_telegram_message(token, chat_id, text):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM ERROR] Failed pushing alert: {e}")

# --- BOT ENGINE CLASS ---
class InstitutionalScalperV10:
    def __init__(self):
        self.exchange = ccxt.gate({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'timeout': 20000,
            'headers': {'User-Agent': 'Mozilla/5.0'}
        })
        self.timeframes = ['1m', '5m', '15m']

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
            return None
        live_price = all_tickers[symbol]['last']
        tf_data = {}
        for tf in self.timeframes:
            candles = self.safe_api_call(self.exchange.fetch_ohlcv, symbol, tf, limit=250)
            if not candles or len(candles) < 60:
                return None
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
            PERSISTENCE_TRACKER[symbol] = 0
            return {"status": "BLOCKED", "score": score, "price": live_price, "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'], "rsi_1m": m1_df.loc[i1, 'rsi']}

        if symbol not in PERSISTENCE_TRACKER:
            PERSISTENCE_TRACKER[symbol] = 0

        if score >= 75:
            PERSISTENCE_TRACKER[symbol] += 1
        else:
            PERSISTENCE_TRACKER[symbol] = 0

        report_status = "NORMAL"
        if score >= 75 and PERSISTENCE_TRACKER[symbol] >= 3:
            report_status = "TRIGGER"
            PERSISTENCE_TRACKER[symbol] = 0
        elif score >= 50:
            report_status = "WATCHING"

        return {"status": report_status, "score": score, "price": live_price, "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'], "rsi_1m": m1_df.loc[i1, 'rsi']}

# --- GENERATE TABULAR STRING UTILITY ---
def build_matrix_table_string():
    if not LATEST_METRICS_CACHE:
        return "Bhai, database khali hai. Ek scanning cycle complete hone ka wait karo."
    timestamp_str = datetime.now().strftime('%H:%M:%S')
    report_msg = f"📊 *[LIVE GRID REPORT - {timestamp_str}]*\n```text\n"
    report_msg += "COIN   | PRICE    | SCORE | 15M  | 5M   | 1M   \n"
    report_msg += "───────┼──────────┼───────┼──────┼──────┼──────\n"
    for coin, data in list(LATEST_METRICS_CACHE.items()):
        c_name = f"{coin:<6}"
        c_price = f"{str(data['price']):<8}"[:8]
        c_score = f"{int(data['score']):<5}"
        r15 = f"{int(data['rsi_15m']):<4}"
        r5 = f"{int(data['rsi_5m']):<4}"
        r1 = f"{int(data['rsi_1m']):<4}"
        flag = ""
        if data['status'] == "BLOCKED": flag = " ❌"
        elif data['status'] == "WATCHING": flag = " ⚠️"
        report_msg += f"{c_name} | {c_price} | {c_score} | {r15} | {r5} | {r1}{flag}\n"
    report_msg += "```"
    return report_msg

# --- TELEGRAM CONTROL PANEL ENGINE (INBOUND LISTENER) ---
def telegram_control_panel_listener():
    """Listens for inbound slash commands from the user to dynamically edit vectors."""
    token = os.environ.get("TELEGRAM_TOKEN", None)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", None)
    if not token or not chat_id:
        return

    offset = 0
    print("[CONTROL PANEL] Telegram Inbound Command Listener Active.")
    
    while True:
        url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
        try:
            response = requests.get(url, timeout=25).json()
            if "result" in response:
                for update in response["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        msg_text = update["message"]["text"].strip()
                        incoming_chat_id = str(update["message"]["chat"]["id"])
                        
                        # Security Check: Process commands ONLY if they come from your configured chat ID
                        if incoming_chat_id != str(chat_id):
                            continue

                        # Command Processing Logic
                        if msg_text.startswith('/add '):
                            coin_to_add = msg_text.replace('/add ', '').strip().upper()
                            full_symbol = f"{coin_to_add}/USDT:USDT"
                            if full_symbol not in TRACKED_COINS:
                                TRACKED_COINS.append(full_symbol)
                                PERSISTENCE_TRACKER[full_symbol] = 0
                                send_telegram_message(token, chat_id, f"✅ *{coin_to_add}* successfully added to live tracking matrix grid!")
                            else:
                                send_telegram_message(token, chat_id, f"⚠️ *{coin_to_add}* is already being scanned.")

                        elif msg_text.startswith('/remove '):
                            coin_to_rem = msg_text.replace('/remove ', '').strip().upper()
                            full_symbol = f"{coin_to_rem}/USDT:USDT"
                            if full_symbol in TRACKED_COINS:
                                TRACKED_COINS.remove(full_symbol)
                                if full_symbol in PERSISTENCE_TRACKER: del PERSISTENCE_TRACKER[full_symbol]
                                if coin_to_rem in LATEST_METRICS_CACHE: del LATEST_METRICS_CACHE[coin_to_rem]
                                send_telegram_message(token, chat_id, f"🗑️ *{coin_to_rem}* removed cleanly from core memory streams.")
                            else:
                                send_telegram_message(token, chat_id, f"❌ *{coin_to_rem}* not found in active tracking list.")

                        elif msg_text == '/list':
                            clean_list = [c.split('/')[0] for c in TRACKED_COINS]
                            send_telegram_message(token, chat_id, f"📋 *Active Watchlist Engine Status:*\n`{', '.join(clean_list)}`")

                        elif msg_text == '/report':
                            # Instant report on demand bypasses 1 minute timer limits
                            send_telegram_message(token, chat_id, build_matrix_table_string())
        except Exception as e:
            print(f"[CONTROL PANEL ERROR] Listener loop glitch: {e}")
        time.sleep(1)

# --- LIVE COMPUTATION PROCESS LOOP ---
def run_bot_loop():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", None)
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", None)
    
    startup_msg = "🚀 *Gate.io Institutional Scalper Bot V10 Live!*\nControl Panel Connected. Use `/add`, `/remove`, `/list`, `/report` in chat."
    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, startup_msg)

    bot = InstitutionalScalperV10()
    last_report_time = time.time()

    while True:
        # Create a local copy of the list to prevent runtime multi-threading adjustment errors
        active_loop_list = list(TRACKED_COINS)
        
        for asset in active_loop_list:
            metrics = bot.evaluate_asset_metrics(asset)
            if metrics:
                clean_name = asset.split('/')[0]
                # Cache results for explicit on-demand tracking lookups
                LATEST_METRICS_CACHE[clean_name] = metrics
                
                if metrics['status'] == "TRIGGER":
                    alert_txt = f"🚨 *[EXECUTION TRIGGER]* 🚨\n\n*Coin:* {clean_name}\n*Price:* {metrics['price']}\n*Exhaustion Score:* {metrics['score']:.1f}/100\n\nGrid execution metrics matched. Short position viable."
                    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, alert_txt)
            time.sleep(0.5)

        # Automatic 1-Minute routine push update loop
        current_time = time.time()
        if current_time - last_report_time >= 60:
            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, build_matrix_table_string())
            last_report_time = current_time

        time.sleep(5)

if __name__ == "__main__":
    # 1. Web Endpoint Binder thread for keeping Render host execution alive
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    # 2. Control Panel Listener thread managing instant incoming chat commands
    control_thread = Thread(target=telegram_control_panel_listener)
    control_thread.daemon = True
    control_thread.start()

    # 3. Main processing scanner thread running quantitative loops sequentially
    run_bot_loop()
