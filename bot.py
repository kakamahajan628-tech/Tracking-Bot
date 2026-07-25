import time
import traceback
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
# Stores the combination of exchange and specific market type (SWAP or SPOT)
TRACKED_COINS_ROUTER = {}
PERSISTENCE_TRACKER = {}
LATEST_METRICS_CACHE = {}

# --- EXCHANGE ROSTER ---
# Add/remove ccxt exchange ids here to widen or narrow the routing search.
# Order matters: futures/spot lookups scan this list top-to-bottom, so put
# your preferred/most liquid exchanges first.
EXCHANGE_IDS = [
    'okx',
    'gate',
    'binance',
    'bybit',
    'kucoin',
    'mexc',
    'bitget',
    'htx',
    'bingx',
]

app = Flask('')

@app.route('/')
def home():
    return "Institutional Scalper V18 Smart Routing Active.", 200

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

def safe_int(value, default=0):
    """Prevents ValueError crashes when RSI/other values are NaN."""
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return int(value)
    except Exception:
        return default

# --- HYBRID ROUTER ENGINE CORE ---
class HybridExhaustionEngineV18:
    def __init__(self):
        # We handle multi-market parameters dynamically inside the endpoints calls now
        # self.exchanges maps DISPLAY NAME (e.g. "OKX") -> live ccxt instance.
        # Built dynamically from EXCHANGE_IDS so adding an exchange is a one-line change.
        self.exchanges = {}
        for ex_id in EXCHANGE_IDS:
            try:
                exchange_class = getattr(ccxt, ex_id)
                self.exchanges[ex_id.upper()] = exchange_class({
                    'enableRateLimit': True,
                    'timeout': 15000,
                    'headers': {'User-Agent': 'Mozilla/5.0'}
                })
            except Exception as e:
                print(f"[EXCHANGE INIT SKIPPED] {ex_id}: {e}")
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
                print(f"[API EXCEPTION] Safely bypassed: {e}")
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
            if idx2 < len(rsi) and idx1 < len(rsi):
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

    def evaluate_hybrid_asset(self, symbol, route_info):
        """Processes calculations dynamically across configured spot or swap parameters.
        Wrapped defensively: any unexpected data issue returns None instead of
        propagating and killing the main loop."""
        try:
            ex_name = route_info['exchange']
            m_type = route_info['type']
            ex = self.exchanges.get(ex_name)
            if ex is None:
                return None

            all_tickers = self.safe_api_call(ex, ex.fetch_tickers, [symbol])
            if not all_tickers or symbol not in all_tickers:
                return None
            live_price = all_tickers[symbol].get('last')
            if live_price is None:
                return None

            tf_data = {}
            for tf in self.timeframes:
                candles = self.safe_api_call(ex, ex.fetch_ohlcv, symbol, tf, limit=250)
                if not candles or len(candles) < 60:
                    return None
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = self.run_quantitative_indicators(df)
                if df[['ema_20', 'ema_50', 'adx', 'rsi', 'macd_hist', 'atr']].iloc[-2:].isnull().values.any():
                    # Not enough clean data yet on the most recent bars - skip this pass
                    return None
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
            atr_ratio = m1_df.loc[i1, 'atr'] / atr_ma_50 if atr_ma_50 and atr_ma_50 > 0 else 1.0
            if atr_ratio > 1.5:
                score += 10

            price_up_15m = m15_df.loc[i15, 'close'] > m15_df.loc[p_i15, 'close']
            base_volume = self.analyze_volume_climax(ex, symbol)
            if base_volume and price_up_15m:
                score += 15

            hyper_bullish_15m = (m15_df.loc[i15, 'ema_20'] > m15_df.loc[i15, 'ema_50']
                                  and m15_df.loc[i15, 'adx'] > 32
                                  and m15_df.loc[i15, 'rsi'] > 65)
            if hyper_bullish_15m and not m5_mss:
                if symbol in PERSISTENCE_TRACKER:
                    PERSISTENCE_TRACKER[symbol] = 0
                return {"status": "BLOCKED", "score": score, "price": live_price,
                        "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'],
                        "rsi_1m": m1_df.loc[i1, 'rsi'], "route": f"{ex_name} ({m_type})"}

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

            return {"status": report_status, "score": score, "price": live_price,
                    "rsi_15m": m15_df.loc[i15, 'rsi'], "rsi_5m": m5_df.loc[i5, 'rsi'],
                    "rsi_1m": m1_df.loc[i1, 'rsi'], "route": f"{ex_name} ({m_type})"}

        except Exception as e:
            print(f"[EVALUATE EXCEPTION] {symbol}: {e}")
            traceback.print_exc()
            return None

def build_premium_report_string():
    if not TRACKED_COINS_ROUTER:
        return "📋 *Watchlist Khali Hai!* Chat me `/add [coin]` karke scanning shuru karein bhai."
    if not LATEST_METRICS_CACHE:
        return "⏳ *Bhai, data sync ho raha hai.* Please wait 1 cycle."

    timestamp = datetime.now().strftime('%H:%M:%S')
    msg = f"📊 *[SMART ROUTING WATCHLIST — {timestamp}]*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    for coin in list(LATEST_METRICS_CACHE.keys()):
        try:
            # Quick formatting lookup mapping strings safely
            swap_sym = f"{coin}/USDT:USDT"
            spot_sym = f"{coin}/USDT"
            if swap_sym not in TRACKED_COINS_ROUTER and spot_sym not in TRACKED_COINS_ROUTER:
                continue

            data = LATEST_METRICS_CACHE[coin]
            status_banner = "🟢 *TREND INTACT*"
            if data.get('status') == "BLOCKED":
                status_banner = "❌ *SHORT BLOCKED (Hyper-Bull)*"
            elif data.get('status') == "WATCHING":
                status_banner = "⚠️ *EXHAUSTION DETECTED*"

            msg += f"🪙 *Asset:* `{coin}` | *Price:* `{data.get('price')}`\n"
            msg += f"🏢 *Market Route:* `{data.get('route')}`\n"
            msg += f"🔥 *Exhaustion Score:* `{data.get('score', 0):.1f}/100` | Status: {status_banner}\n"
            msg += (f"📈 *RSI Metrics:* `15M:` {safe_int(data.get('rsi_15m'))}  •  "
                    f"`5M:` {safe_int(data.get('rsi_5m'))}  •  `1M:` {safe_int(data.get('rsi_1m'))}\n")
            msg += "────────────────────\n"
        except Exception as e:
            print(f"[REPORT BUILD EXCEPTION] {coin}: {e}")
            continue
    return msg

# --- TELEGRAM CONTROLLER WITH SMART FALLBACK ---
def telegram_control_panel_listener():
    token = get_clean_env_var("TELEGRAM_TOKEN")
    chat_id = get_clean_env_var("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    offset = 0
    bot_instance = HybridExhaustionEngineV18()

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
                            raw_coin = msg_text.replace('/add ', '').strip().upper()

                            swap_symbol = f"{raw_coin}/USDT:USDT"
                            spot_symbol = f"{raw_coin}/USDT"

                            determined_ex = None
                            market_type = None
                            final_symbol = None

                            # Step A: Load market registries dynamically for every configured exchange
                            loaded_markets = {}
                            for ex_name, ex_instance in bot_instance.exchanges.items():
                                try:
                                    if not ex_instance.markets:
                                        bot_instance.safe_api_call(ex_instance, ex_instance.load_markets)
                                    loaded_markets[ex_name] = ex_instance.markets or {}
                                except Exception:
                                    loaded_markets[ex_name] = {}

                            # Step B: Route Logic Pipeline (Perpetual Futures Checks First,
                            # scanned in EXCHANGE_IDS order so preferred exchanges win ties)
                            for ex_id in EXCHANGE_IDS:
                                ex_name = ex_id.upper()
                                if swap_symbol in loaded_markets.get(ex_name, {}):
                                    determined_ex, market_type, final_symbol = ex_name, 'FUTURES', swap_symbol
                                    break

                            # Step C: Fallback Route Pipeline (Spot Market Checks Second)
                            if not determined_ex:
                                for ex_id in EXCHANGE_IDS:
                                    ex_name = ex_id.upper()
                                    if spot_symbol in loaded_markets.get(ex_name, {}):
                                        determined_ex, market_type, final_symbol = ex_name, 'SPOT', spot_symbol
                                        break

                            if not determined_ex:
                                scanned_list = ', '.join(EXCHANGE_IDS)
                                send_telegram_message(token, chat_id, f"❌ *{raw_coin}* Spot ya Futures kisi bhi exchange par nahi mila!\n_Scanned: {scanned_list}_")
                                continue

                            if final_symbol not in TRACKED_COINS_ROUTER:
                                TRACKED_COINS_ROUTER[final_symbol] = {'exchange': determined_ex, 'type': market_type}
                                PERSISTENCE_TRACKER[final_symbol] = 0

                                send_telegram_message(token, chat_id, f"⏳ Syncing *{raw_coin}* via {determined_ex} ({market_type} Route)...")
                                instant_metrics = bot_instance.evaluate_hybrid_asset(final_symbol, TRACKED_COINS_ROUTER[final_symbol])
                                if instant_metrics:
                                    LATEST_METRICS_CACHE[raw_coin] = instant_metrics
                                    send_telegram_message(token, chat_id, f"✅ *{raw_coin}* successfully mapped onto the matrix cards!")
                                else:
                                    send_telegram_message(token, chat_id, f"⚠️ *{raw_coin}* added to pipeline, waiting for processing pass.")
                            else:
                                send_telegram_message(token, chat_id, f"⚠️ *{raw_coin}* is already active.")

                        elif msg_text.startswith('/remove '):
                            raw_coin = msg_text.replace('/remove ', '').strip().upper()
                            swap_symbol = f"{raw_coin}/USDT:USDT"
                            spot_symbol = f"{raw_coin}/USDT"

                            target_symbol = swap_symbol if swap_symbol in TRACKED_COINS_ROUTER else spot_symbol

                            if target_symbol in TRACKED_COINS_ROUTER:
                                del TRACKED_COINS_ROUTER[target_symbol]
                                if target_symbol in PERSISTENCE_TRACKER:
                                    del PERSISTENCE_TRACKER[target_symbol]
                                if raw_coin in LATEST_METRICS_CACHE:
                                    del LATEST_METRICS_CACHE[raw_coin]
                                send_telegram_message(token, chat_id, f"🗑️ *{raw_coin}* successfully removed from monitoring memory grids.")
                            else:
                                send_telegram_message(token, chat_id, f"❌ *{raw_coin}* active list me nahi mila.")

                        elif msg_text == '/list':
                            if not TRACKED_COINS_ROUTER:
                                send_telegram_message(token, chat_id, "📋 *Active Watchlist:* `Empty` (Use `/add`) ")
                                continue
                            lines = []
                            for k, v in TRACKED_COINS_ROUTER.items():
                                lines.append(f"{k.split('/')[0]} ({v['exchange']}-{v['type']})")
                            send_telegram_message(token, chat_id, f"📋 *Active Routing System Grid:*\n`{', '.join(lines)}`")

                        elif msg_text == '/report':
                            send_telegram_message(token, chat_id, build_premium_report_string())
        except Exception as e:
            print(f"[CONTROL PANEL ERROR] {e}")
            traceback.print_exc()
        time.sleep(1)

def run_bot_loop():
    TELEGRAM_TOKEN = get_clean_env_var("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = get_clean_env_var("TELEGRAM_CHAT_ID")

    startup_msg = "🚀 *Smart Fallback Hybrid Scalper V18 Live!*\nNow automatically routing between Futures and Spot markets safely."
    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, startup_msg)

    bot = HybridExhaustionEngineV18()
    last_report_time = time.time()

    while True:
        try:
            active_router_snapshot = dict(TRACKED_COINS_ROUTER)

            if not active_router_snapshot:
                time.sleep(5)
                continue

            for asset, route_info in active_router_snapshot.items():
                try:
                    metrics = bot.evaluate_hybrid_asset(asset, route_info)
                    if metrics:
                        clean_name = asset.split('/')[0]
                        LATEST_METRICS_CACHE[clean_name] = metrics
                        if metrics['status'] == "TRIGGER" and route_info['type'] == "FUTURES":
                            alert_txt = (f"🚨 *[FUTURES STRATEGY REVERSAL]* 🚨\n\n"
                                         f"*Coin:* {clean_name}\n*Network:* {route_info['exchange']}\n"
                                         f"*Price:* {metrics['price']}\n*Exhaustion Score:* {metrics['score']:.1f}/100")
                            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, alert_txt)
                except Exception as e:
                    # A single bad symbol should never take the whole bot down.
                    print(f"[BOT LOOP EXCEPTION] {asset}: {e}")
                    traceback.print_exc()
                time.sleep(0.5)

            current_time = time.time()
            if current_time - last_report_time >= 60:
                try:
                    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, build_premium_report_string())
                except Exception as e:
                    print(f"[REPORT SEND EXCEPTION] {e}")
                last_report_time = current_time
            time.sleep(5)

        except Exception as e:
            # Outer safety net: log it, notify, and keep the process alive.
            print(f"[MAIN LOOP EXCEPTION] {e}")
            traceback.print_exc()
            try:
                send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                                       f"⚠️ *Bot hit an internal error and recovered:* `{e}`")
            except Exception:
                pass
            time.sleep(5)

if __name__ == "__main__":
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    control_thread = Thread(target=telegram_control_panel_listener)
    control_thread.daemon = True
    control_thread.start()

    # Outermost guard so nothing — not even a bug we haven't anticipated —
    # can silently kill the process. Restarts the core loop instead of dying.
    while True:
        try:
            run_bot_loop()
        except Exception as e:
            print(f"[FATAL - RESTARTING run_bot_loop] {e}")
            traceback.print_exc()
            time.sleep(5)
