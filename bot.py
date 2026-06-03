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

# --- GLOBAL TRACKING REGISTRY ---
# Dynamic structural memory mapping each target asset directly to its optimal active exchange route
TRACKED_COINS_ROUTER = {
    'BTC/USDT:USDT': 'OKX',
    'ETH/USDT:USDT': 'OKX'
}
PERSISTENCE_TRACKER = {symbol: 0 for symbol in TRACKED_COINS_ROUTER}
LATEST_METRICS_CACHE = {}

app = Flask('')

@app.route('/')
def home():
    return "Institutional Scalper V15 Hybrid Dual-Exchange Engine Active.", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def get_clean_env_var(key):
    val = os.environ.get(key, None)
    if not val:
        return None
    clean_val = str(val).strip()
    for char in ['[', ']', '(', ')', "'", '"']:
        clean_val = clean_val.replace(char, '')
    if "api.telegram.org" in clean_val and "http" in clean_val:
        if "http" in clean_val:
            clean_val = clean_val.split("http")[-1]
            clean_val = "http" + clean_val
    return clean_val

def send_telegram_message(token, chat_id, text):
    if not token or not chat_id:
        return
    clean_token = token.replace('https://api.telegram.org/bot', '').replace('bot', '').strip()
    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    payload = {"chat_id": str(chat_id).strip(), "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM ERROR] Transport failed: {e}")

def clean_and_format_symbol(user_input):
    raw = user_input.strip().upper()
    if not raw:
        return None
    raw = raw.split(':')[0]
    if raw.endswith('/USDT'):
        raw = raw.replace('/USDT', '')
    return f"{raw}/USDT:USDT"

# --- CORE HYBRID ROUTER ENGINE ---
class HybridExhaustionEngineV15:
    def __init__(self):
        # Initialize OKX Router
        self.okx = ccxt.okx({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'timeout': 15000,
            'headers': {'User-Agent': 'Mozilla/5.0'}
        })
        # Initialize Gate.io Router
        self.gate = ccxt.gate({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'timeout': 15000,
            'headers': {'User-Agent': 'Mozilla/5.0'}
        })
        self.timeframes = ['1m', '5m', '15m']

    def safe_api_call(self, exchange_instance, func, *args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except ccxt.RateLimitExceeded:
                time.sleep(4)
            except (ccxt.NetworkError, ccxt.RequestTimeout):
                time.sleep(2)
            except Exception as e:
                print(f"[API EXCEPTION] Hybrid Route Skipped: {e}")
                return None
        return None

    def analyze_volume_climax(self, exchange_instance, symbol):
        try:
            ticker = self.safe_api_call(exchange_instance, exchange_instance.fetch_ticker, symbol)
            if ticker and 'baseVolume' in ticker:
                return float(ticker['baseVolume'])
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

    def evaluate_hybrid_asset(self, symbol, exchange_name):
        """Processes cross-exchange structural validations dynamically based on active mapping routes."""
        ex = self.okx if exchange_name == 'OKX' else self.gate
        
        try:
            if ex.markets is None:
                self.safe_api_call(ex, ex.load_markets)
            if symbol not in ex.markets:
                return None
        except Exception:
            pass

        all_tickers = self.safe_api_call(ex, ex.fetch_tickers, [symbol])
        if not all_tickers or symbol not in all_tickers:
            return None
        live_price = all_tickers[symbol]['last']
        
        tf_data = {}
        for tf in self.timeframes:
            candles = self.safe_api_call(ex, ex.fetch_ohlcv, symbol, tf, limit=250)
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
        base_volume = self.analyze_volume_climax(ex, symbol)
        if base_volume and price_up_15m:
            score += 15

        hyper_bullish_15m = m15_df.loc[i15, 'ema_20'] > m15_df.loc[i15, 'ema_50'] and m15_df.loc[i15, 'adx'] > 32 and m15_df.loc[i15, 'rsi'] > 65
        if hyper_bullish_15m and not m5_mss:
            if symbol in PERSISTENCE_TRACKER: PERSISTENCE_TRACKER[symbol] = 0
            return {"status": "BLOCKED", "score": score, "price": live_price, "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'], "rsi_1m": m1_df.loc[i1, 'rsi'], "route": exchange_name}

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

        return {"status": report_status, "score": score, "price": live_price, "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'], "rsi_1m": m1_df.loc[i1, 'rsi'], "route": exchange_name}

def build_premium_report_string():
    if not LATEST_METRICS_CACHE:
        return "⏳ *Bhai, Hybrid matrix synchronization in progress.* Wait 1 cycle."
    timestamp = datetime.now().strftime('%H:%M:%S')
    msg = f"📊 *[HYBRID EXHAUSTION DASHBOARD — {timestamp}]*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    for coin in list(LATEST_METRICS_CACHE.keys()):
        expected_symbol = f"{coin}/USDT:USDT"
        if expected_symbol not in TRACKED_COINS_ROUTER:
            continue
            
        data = LATEST_METRICS_CACHE[coin]
        status_banner = "🟢 *TREND INTACT*"
        if data['status'] == "BLOCKED":
            status_banner = "❌ *SHORT BLOCKED (Hyper-Bull)*"
        elif data['status'] == "WATCHING":
            status_banner = "⚠️ *EXHAUSTION DETECTED*"
        msg += f"🪙 *Asset:* `{coin}` | *Price:* `{data['price']}`\n"
        msg += f"🏢 *Route Network:* `{data['route']}`\n"
        msg += f"🔥 *Exhaustion Score:* `{data['score']:.1f}/100` | Status: {status_banner}\n"
        msg += f"📈 *RSI Metrics:* `15M:` {int(data['rsi_15m'])}  •  `5M:` {int(data['rsi_5m'])}  •  `1M:` {int(data['rsi_1m'])}\n"
        msg += "────────────────────\n"
    return msg

# --- TELEGRAM COMMAND LINK CONTROLLER ---
def telegram_control_panel_listener():
    token = get_clean_env_var("TELEGRAM_TOKEN")
    chat_id = get_clean_env_var("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    offset = 0
    bot_instance = HybridExhaustionEngineV15()
    
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
                        if incoming_chat_id != str(chat_id).strip():
                            continue

                        if msg_text.startswith('/add '):
                            raw_input = msg_text.replace('/add ', '').strip()
                            full_symbol = clean_and_format_symbol(raw_input)
                            if not full_symbol:
                                continue
                            
                            # DUAL EXCHANGE INTEGRATION ROUTING BLOCK
                            determined_exchange = None
                            
                            # Check Path A: Verify straight inside OKX market registries
                            try:
                                if bot_instance.okx.markets is None: bot_instance.safe_api_call(bot_instance.okx, bot_instance.okx.load_markets)
                                if full_symbol in bot_instance.okx.markets: determined_exchange = 'OKX'
                            except Exception: pass
                            
                            # Check Path B: If not on OKX, probe inside Gate.io asset structures
                            if not determined_exchange:
                                try:
                                    if bot_instance.gate.markets is None: bot_instance.safe_api_call(bot_instance.gate, bot_instance.gate.load_markets)
                                    if full_symbol in bot_instance.gate.markets: determined_exchange = 'GATE'
                                except Exception: pass

                            if not determined_exchange:
                                send_telegram_message(token, chat_id, f"❌ *{raw_input.upper()}* not found on OKX or Gate.io swap networks!")
                                continue

                            if full_symbol not in TRACKED_COINS_ROUTER:
                                TRACKED_COINS_ROUTER[full_symbol] = determined_exchange
                                PERSISTENCE_TRACKER[full_symbol] = 0
                                
                                send_telegram_message(token, chat_id, f"⏳ *{raw_input.upper()}* mapped to *{determined_exchange}*. Running extraction sync...")
                                instant_metrics = bot_instance.evaluate_hybrid_asset(full_symbol, determined_exchange)
                                if instant_metrics:
                                    LATEST_METRICS_CACHE[raw_input.upper()] = instant_metrics
                                    send_telegram_message(token, chat_id, f"✅ *{raw_input.upper()}* added successfully to the active scan matrix!")
                                else:
                                    send_telegram_message(token, chat_id, f"⚠️ *{raw_input.upper()}* queued, data sync will map on next master pass loop.")
                            else:
                                send_telegram_message(token, chat_id, f"⚠️ *{raw_input.upper()}* is already active.")

                        elif msg_text.startswith('/remove '):
                            raw_input = msg_text.replace('/remove ', '').strip()
                            full_symbol = clean_and_format_symbol(raw_input)
                            coin_display = raw_input.upper().split('/')[0]
                            if full_symbol in TRACKED_COINS_ROUTER:
                                del TRACKED_COINS_ROUTER[full_symbol]
                                if full_symbol in PERSISTENCE_TRACKER: del PERSISTENCE_TRACKER[full_symbol]
                                if coin_display in LATEST_METRICS_CACHE: del LATEST_METRICS_CACHE[coin_display]
                                send_telegram_message(token, chat_id, f"🗑️ *{coin_display}* erased cleanly from hybrid execution matrices.")
                            else:
                                send_telegram_message(token, chat_id, f"❌ *{coin_display}* not found in active list.")

                        elif msg_text == '/list':
                            lines = []
                            for k, v in TRACKED_COINS_ROUTER.items():
                                lines.append(f"{k.split('/')[0]} ({v})")
                            send_telegram_message(token, chat_id, f"📋 *Active Router Map:*\n`{', '.join(lines)}`")

                        elif msg_text == '/report':
                            send_telegram_message(token, chat_id, build_premium_report_string())
        except Exception as e:
            print(f"[CONTROL PANEL MAIN SYSTEM ERROR] {e}")
        time.sleep(1)

def run_bot_loop():
    TELEGRAM_TOKEN = get_clean_env_var("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = get_clean_env_var("TELEGRAM_CHAT_ID")
    
    startup_msg = "🚀 *Hybrid Dual-Exchange Scalper V15 Live!*\nAuto-Routing between OKX & Gate.io active. Controls fully connected!"
    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, startup_msg)

    bot = HybridExhaustionEngineV15()
    last_report_time = time.time()

    while True:
        # Avoid runtime mutation dictionary check execution blocks by duplicating states safely
        active_router_snapshot = dict(TRACKED_COINS_ROUTER)
        for asset, exchange_route in active_router_snapshot.items():
            metrics = bot.evaluate_hybrid_asset(asset, exchange_route)
            if metrics:
                clean_name = asset.split('/')[0]
                LATEST_METRICS_CACHE[clean_name] = metrics
                if metrics['status'] == "TRIGGER":
                    alert_txt = f"🚨 *[HYBRID ENTRY TRIGGER]* 🚨\n\n*Coin:* {clean_name}\n*Network Source:* {exchange_route}\n*Price:* {metrics['price']}\n*Exhaustion Score:* {metrics['score']:.1f}/100"
                    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, alert_txt)
            time.sleep(0.5)

        current_time = time.time()
        if current_time - last_report_time >= 60:
            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, build_premium_report_string())
            last_report_time = current_time
        time.sleep(5)

if __name__ == "__main__":
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    control_thread = Thread(target=telegram_control_panel_listener)
    control_thread.daemon = True
    control_thread.start()

    run_bot_loop()
