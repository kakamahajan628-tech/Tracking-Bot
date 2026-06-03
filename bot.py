import os
import sys
import time
import json
import html
import hashlib
import asyncio
import logging
import aiohttp
import numpy as np
import pandas as pd
import ta
import requests
from threading import Thread
from flask import Flask
from scipy.signal import find_peaks

# --- LOGGING ENVIRONMENT SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

# --- WEB CONTAINER BINDER (FOR RENDER 24/7 ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Quant War Room Hybrid V19 Engine is Active.", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- SYSTEM ENVIRONMENT CONSTANTS ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
raw_chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("USER_CHAT_ID")
USER_CHAT_ID = int(raw_chat_id) if (raw_chat_id and raw_chat_id.strip().isdigit()) else None

if not TOKEN or not USER_CHAT_ID:
    logging.critical("ENVIRONMENT CONFIGURATION ERROR: System tokens missing. Core execution aborted.")
    sys.exit(1)

# --- MEMORY MATRIX REGISTRIES ---
TRACKED_COINS_ROUTER = {}  # Format: {'BTC/USDT:USDT': {'exchange': 'OKX', 'type': 'FUTURES'}}
PERSISTENCE_TRACKER = {}
LATEST_METRICS_CACHE = {}

# Rate-Limiting Hardware Isolation Pools
OKX_SEMAPHORE = asyncio.Semaphore(5)
GATEIO_SEMAPHORE = asyncio.Semaphore(5)
GLOBAL_SCAN_SEMAPHORE = asyncio.Semaphore(10)

# --- TELEGRAM SENDER ENGINE ---
def send_telegram_message(text):
    if not TOKEN or not USER_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": str(USER_CHAT_ID), "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"[TELEGRAM ERROR] Transport failed: {e}")

# --- REFINED HYBRID QUANT ENGINE ---
class RefinedQuantEngineV19:
    def __init__(self):
        # Initializing clean public abstraction layer clients
        self.okx = ccxt.okx({'enableRateLimit': True, 'timeout': 15000}) if 'ccxt' in sys.modules else None
        self.gate = ccxt.gate({'enableRateLimit': True, 'timeout': 15000}) if 'ccxt' in sys.modules else None
        
        # Internal fallback if native async ccxt isn't loaded yet
        if not self.okx:
            import ccxt
            self.okx = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}, 'timeout': 15000})
            self.gate = ccxt.gate({'enableRateLimit': True, 'options': {'defaultType': 'swap'}, 'timeout': 15000})
            
        self.timeframes = ['1m', '5m', '15m']

    def safe_api_call(self, exchange_instance, func, *args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == 2:
                    logging.debug(f"[EXCHANGE TIMEOUT] Safely bypassed network block: {e}")
                time.sleep(1)
        return None

    def analyze_orderbook_pressure(self, exchange_instance, symbol):
        """Fetches dynamic order depth walls utilizing precision weighting."""
        try:
            orderbook = self.safe_api_call(exchange_instance, exchange_instance.fetch_order_book, symbol, limit=20)
            if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
                return 50.0, "BALANCED"
                
            bids, asks = orderbook['bids'], orderbook['asks']
            best_bid, best_ask = bids[0][0], asks[0][0]
            mid_price = (best_bid + best_ask) / 2.0
            spread = max(best_ask - best_bid, mid_price * 0.0001)
            
            top_bid_val = sum(p * q for p, q in bids[:5])
            top_ask_val = sum(p * q for p, q in asks[:5])
            
            order_flow_status = "BALANCED"
            if top_bid_val > (top_ask_val * 1.8): order_flow_status = "BUY WALL"
            elif top_ask_val > (top_bid_val * 1.8): order_flow_status = "SELL WALL"
            
            weighted_bids = sum(qty * np.exp(-abs(price - mid_price) / (spread * 5)) for price, qty in bids[:10])
            weighted_asks = sum(qty * np.exp(-abs(price - mid_price) / (spread * 5)) for price, qty in asks[:10])
            
            total_v = weighted_bids + weighted_asks
            bid_ratio = (weighted_bids / total_v) * 100 if total_v > 0 else 50.0
            return bid_ratio, order_flow_status
        except Exception:
            return 50.0, "BALANCED"

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

    def check_market_structure_shift(self, df):
        p_highs, p_lows = self.get_confirmed_pivots(df)
        closes = df['close'].values
        macd_hist = df['macd_hist'].values
        
        mss = False
        if p_lows:
            last_low = p_lows[-1][1]
            if closes[-1] < last_low and closes[-2] < last_low:
                mss = True
                
        bearish_div = False
        if len(p_highs) >= 2:
            idx1, peak1 = p_highs[-2]
            idx2, peak2 = p_highs[-1]
            if idx2 < len(macd_hist) and idx1 < len(macd_hist):
                if peak2 > peak1 and macd_hist[idx2] < macd_hist[idx1]:
                    bearish_div = True
                    
        return mss, bearish_div

    def run_quantitative_indicators(self, df):
        df['ema_20'] = ta.trend.ema_indicator(df['close'], window=20)
        df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['ema_200'] = ta.trend.ema_indicator(df['close'], window=200)
        df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        df['macd_hist'] = ta.trend.MACD(df['close']).macd_diff()
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        return df

    def evaluate_hybrid_asset(self, symbol, route_info):
        ex_name = route_info['exchange']
        m_type = route_info['type']
        ex = self.okx if ex_name == 'OKX' else self.gate
        
        all_tickers = self.safe_api_call(ex, ex.fetch_tickers, [symbol])
        if not all_tickers or symbol not in all_tickers:
            return None
        live_price = all_tickers[symbol]['last']
        
        tf_data = {}
        for tf in self.timeframes:
            candles = self.safe_api_call(ex, ex.fetch_ohlcv, symbol, tf, limit=150)
            if not candles or len(candles) < 60:
                return None
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = self.run_quantitative_indicators(df)
            tf_data[tf] = df

        m1_df, m5_df, m15_df = tf_data['1m'], tf_data['5m'], tf_data['15m']
        i1, i5, i15 = m1_df.index[-1], m5_df.index[-1], m15_df.index[-1]
        p_i1 = m1_df.index[-2]
        
        # Core Calculations
        m1_mss, m1_div = self.check_market_structure_shift(m1_df)
        m5_mss, _ = self.check_market_structure_shift(m5_df)
        m15_mss, _ = self.check_market_structure_shift(m15_df)
        
        bid_pct, orderbook_status = self.analyze_orderbook_pressure(ex, symbol)
        
        # --- QUANT CORE MATRIX OVERHAUL (NO RSI ACCUMULATION) ---
        score = 0
        if m1_mss: score -= 15           # 1m MSS breaks down structure
        if m5_mss: score -= 25           # 5m core trend shifts bearish
        if m15_mss: score -= 35          # 15m anchor breaking down
        if m1_div: score -= 15           # Momentum Bearish Divergence
        
        macd_weakening_1m = m1_df.loc[i1, 'macd_hist'] < m1_df.loc[p_i1, 'macd_hist']
        if macd_weakening_1m: score -= 10
        if orderbook_status == "SELL WALL": score -= 15
        if orderbook_status == "BUY WALL": score += 20
        
        # Calculate dynamic momentum
        has_ema = len(m1_df['ema_50']) > 0 and pd.notna(m1_df.loc[i1, 'ema_50'])
        trend_regime = "BULLISH" if (has_ema and live_price > m1_df.loc[i1, 'ema_50']) else "BEARISH"
        momentum_strength = "STRONG" if m1_df.loc[i1, 'adx'] > 28 else "WEAK"
        
        # Whale flow approximation based on real volume metrics
        recent_vol = m1_df['volume'].tail(3).mean()
        historical_vol = m1_df['volume'].tail(20).head(15).mean()
        whale_flow = "BUYING" if (trend_regime == "BULLISH" and recent_vol > historical_vol) else "SELLING"

        # --- HARD LOCK REVERSE CRITICAL MATRIX ---
        # If the structure is completely parabolic but starting structural shifts emerge
        hyper_bullish_15m = m15_df.loc[i15, 'ema_20'] > m15_df.loc[i15, 'ema_50'] and m15_df.loc[i15, 'adx'] > 35
        if hyper_bullish_15m and not m1_mss and score < -50:
            score = -30 # Soft clamp raw signals to prevent pre-mature shorts on strong extensions

        if symbol not in PERSISTENCE_TRACKER:
            PERSISTENCE_TRACKER[symbol] = 0

        # Matrix Action Routing Assignments
        report_status = "SCAN"
        if score <= -65:
            PERSISTENCE_TRACKER[symbol] -= 1
            if PERSISTENCE_TRACKER[symbol] <= -3:
                report_status = "SHORT_THOKO"
                PERSISTENCE_TRACKER[symbol] = 0
        elif score >= 65:
            PERSISTENCE_TRACKER[symbol] += 1
            if PERSISTENCE_TRACKER[symbol] >= 3:
                report_status = "LONG_THOKO"
                PERSISTENCE_TRACKER[symbol] = 0
        else:
            PERSISTENCE_TRACKER[symbol] = 0

        return {
            "status": report_status, "score": score, "price": live_price,
            "whale_flow": whale_flow, "orderbook": orderbook_status,
            "trend": trend_regime, "momentum": momentum_strength, "exchange": f"{ex_name} ({m_type})"
        }

# --- PREMIUM VISUAL CARD FORMATTER ---
def build_premium_war_room_card(coin, data):
    """Outputs a mobile optimized visual telemetry card structure cleanly matching requested design constraints."""
    status_icon = "🟢" if "LONG" in data['status'] or data['score'] >= 0 else "🔴"
    execution_verdict = "WAIT & SCAN"
    
    if data['status'] == "LONG_THOKO": execution_verdict = "LONG THOKO 🟢"
    elif data['status'] == "SHORT_THOKO": execution_verdict = "SHORT THOKO 🔴"
    
    # Mathematical score mapping format display bounds
    abs_score = abs(int(data['score']))
    
    msg = "🛰️ *QUANT WAR ROOM*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"{status_icon} *{coin}/USDT*\n\n"
    msg += f"💰 *Price* ➜ ${data['price']}\n"
    msg += f"🐋 *Whale Flow* ➜ {data['whale_flow']}\n"
    msg += f"🏦 *Orderbook* ➜ {data['orderbook']}\n"
    msg += f"📡 *Trend* ➜ {data['trend']}\n"
    msg += f"⚡ *Momentum* ➜ {data['momentum']}\n\n"
    msg += f"📊 *Engine Score Matrix:* `{abs_score}/100` via `{data['exchange']}`\n\n"
    msg += "🤖 *AI Verdict:* \n"
    msg += f"• Matrix Shift: `{'MATCHED' if abs_score > 60 else 'STABLE'}`\n"
    msg += f"• Flows: `{'DOMINATING' if data['whale_flow'] != 'BALANCED' else 'CONSOLIDATING'}`\n\n"
    msg += f"🎯 *EXECUTION: {execution_verdict}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━"
    return msg

# --- TELEGRAM DECK MANAGER ---
def telegram_control_panel_listener():
    token = get_clean_env_var("TELEGRAM_TOKEN")
    chat_id = get_clean_env_var("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    offset = 0
    bot_instance = RefinedQuantEngineV19()
    
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
                        if incoming_chat_id != str(chat_id).strip(): continue

                        if msg_text.startswith('/add '):
                            raw_coin = msg_text.replace('/add ', '').strip().upper()
                            swap_symbol, spot_symbol = f"{raw_coin}/USDT:USDT", f"{raw_coin}/USDT"
                            determined_ex, market_type, final_symbol = None, None, None
                            
                            try:
                                if bot_instance.okx.markets is None: bot_instance.safe_api_call(bot_instance.okx, bot_instance.okx.load_markets)
                                if bot_instance.gate.markets is None: bot_instance.safe_api_call(bot_instance.gate, bot_instance.gate.load_markets)
                            except Exception: pass

                            if swap_symbol in bot_instance.okx.markets: determined_ex, market_type, final_symbol = 'OKX', 'FUTURES', swap_symbol
                            elif swap_symbol in bot_instance.gate.markets: determined_ex, market_type, final_symbol = 'GATE', 'FUTURES', swap_symbol
                            elif spot_symbol in bot_instance.okx.markets: determined_ex, market_type, final_symbol = 'OKX', 'SPOT', spot_symbol
                            elif spot_symbol in bot_instance.gate.markets: determined_ex, market_type, final_symbol = 'GATE', 'SPOT', spot_symbol

                            if not determined_ex:
                                send_telegram_message(f"❌ *{raw_coin}* Spot/Futures me OKX ya Gate.io par nahi mila!")
                                continue

                            if final_symbol not in TRACKED_COINS_ROUTER:
                                TRACKED_COINS_ROUTER[final_symbol] = {'exchange': determined_ex, 'type': market_type}
                                PERSISTENCE_TRACKER[final_symbol] = 0
                                send_telegram_message(f"⏳ Syncing *{raw_coin}* metrics via {determined_ex}...")
                                instant_m = bot_instance.evaluate_hybrid_asset(final_symbol, TRACKED_COINS_ROUTER[final_symbol])
                                if instant_m:
                                    LATEST_METRICS_CACHE[raw_coin] = instant_m
                                    send_telegram_message(build_premium_war_room_card(raw_coin, instant_m))
                                else:
                                    send_telegram_message(f"✅ *{raw_coin}* watchlist me add ho gaya hai pipeline pass queue me.")
                            else:
                                send_telegram_message(f"⚠️ *{raw_coin}* already active.")

                        elif msg_text.startswith('/remove '):
                            raw_coin = msg_text.replace('/remove ', '').strip().upper()
                            swap_sym, spot_sym = f"{raw_coin}/USDT:USDT", f"{raw_coin}/USDT"
                            target_symbol = swap_sym if swap_sym in TRACKED_COINS_ROUTER else spot_sym
                            if target_symbol in TRACKED_COINS_ROUTER:
                                del TRACKED_COINS_ROUTER[target_symbol]
                                if target_symbol in PERSISTENCE_TRACKER: del PERSISTENCE_TRACKER[target_symbol]
                                if raw_coin in LATEST_METRICS_CACHE: del LATEST_METRICS_CACHE[raw_coin]
                                send_telegram_message(f"🗑️ *{raw_coin}* cleanly removed from war room tracking matrices.")
                            else:
                                send_telegram_message(f"❌ *{raw_coin}* active list me nahi mila.")

                        elif msg_text == '/list':
                            if not TRACKED_COINS_ROUTER:
                                send_telegram_message("📋 *Watchlist Engine:* `Khali Hai` (Use `/add [coin]`) ")
                                continue
                            lines = [f"{k.split('/')[0]} ({v['exchange']}-{v['type']})" for k, v in TRACKED_COINS_ROUTER.items()]
                            send_telegram_message(f"📋 *Active Watchlist Tracker Elements:*\n`{', '.join(lines)}`")

                        elif msg_text == '/report':
                            if not LATEST_METRICS_CACHE:
                                send_telegram_message("⏳ Data synchronize ho raha hai.")
                                continue
                            for coin, data in list(LATEST_METRICS_CACHE.items()):
                                send_telegram_message(build_premium_war_room_card(coin, data))
        except Exception as e:
            print(f"[CONTROL PANEL MAIN LOG ERROR] {e}")
        time.sleep(1)

def run_bot_loop():
    bot = RefinedQuantEngineV19()
    last_report_time = time.time()

    while True:
        active_router_snapshot = dict(TRACKED_COINS_ROUTER)
        if not active_router_snapshot:
            time.sleep(5)
            continue
            
        for asset, route_info in active_router_snapshot.items():
            metrics = bot.evaluate_hybrid_asset(asset, route_info)
            if metrics:
                clean_name = asset.split('/')[0]
                LATEST_METRICS_CACHE[clean_name] = metrics
                
                # Dynamic Alert Push on Persistent Structural Shift Signals
                if metrics['status'] in ["LONG_THOKO", "SHORT_THOKO"]:
                    send_telegram_message(build_premium_war_room_card(clean_name, metrics))
            time.sleep(0.5)

        current_time = time.time()
        if current_time - last_report_time >= 60:
            for coin, data in list(LATEST_METRICS_CACHE.items()):
                send_telegram_message(build_premium_war_room_card(coin, data))
            last_report_time = current_time
        time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web_server, daemon=True).start()
    Thread(target=telegram_control_panel_listener, daemon=True).start()
    run_bot_loop()
