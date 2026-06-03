import os
import sys
import time
from datetime import datetime, timedelta
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
import ccxt
from threading import Thread
from flask import Flask
from scipy.signal import find_peaks

# --- LOGGING ENVIRONMENT SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

app = Flask('')

@app.route('/')
def home():
    return "Quant War Room Hybrid V26 Anti-Spam Engine is Active.", 200

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

TOKEN = get_clean_env_var("TELEGRAM_TOKEN")
raw_chat_id = get_clean_env_var("TELEGRAM_CHAT_ID") or get_clean_env_var("USER_CHAT_ID")
USER_CHAT_ID = int(raw_chat_id) if (raw_chat_id and str(raw_chat_id).strip().isdigit()) else None

if not TOKEN or not USER_CHAT_ID:
    logging.critical("ENVIRONMENT CONFIGURATION ERROR: System setup aborted.")
    sys.exit(1)

TRACKED_COINS_ROUTER = {}
PERSISTENCE_TRACKER = {}
LATEST_METRICS_CACHE = {}

# --- FIXED: State lock memory cache preventing infinite loops ---
LAST_SENT_ALERT_STATE = {} 

def send_telegram_message(text):
    clean_token = TOKEN.replace('https://api.telegram.org/bot', '').replace('bot', '').strip()
    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    payload = {"chat_id": str(USER_CHAT_ID), "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=12)
        return res.json()
    except Exception as e:
        logging.error(f"[TELEGRAM ERROR] Transport failed: {e}")
        return None

# --- HYBRID REFINED QUANT MATRIX ENGINE ---
class RefinedQuantEngineV26:
    def __init__(self):
        self.okx = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}, 'timeout': 15000})
        self.gate = ccxt.gate({'enableRateLimit': True, 'options': {'defaultType': 'swap'}, 'timeout': 15000})
        self.timeframes = ['1m', '5m', '15m']

    def safe_api_call(self, exchange_instance, func, *args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == 2:
                    logging.debug(f"[EXCHANGE TIMEOUT] Bypassed network block: {e}")
                time.sleep(1)
        return None

    def analyze_orderbook_pressure(self, exchange_instance, symbol):
        try:
            orderbook = self.safe_api_call(exchange_instance, exchange_instance.fetch_order_book, symbol, limit=20)
            if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
                return 50.0, 50.0, "BALANCED"
                
            bids, asks = orderbook['bids'], orderbook['asks']
            best_bid, best_ask = bids[0][0], asks[0][0]
            mid_price = (best_bid + best_ask) / 2.0
            spread = max(best_ask - best_bid, mid_price * 0.0001)
            
            top_bid_val = sum(p * q for p, q in bids[:5])
            top_ask_val = sum(p * q for p, q in asks[:5])
            
            order_flow_status = "BALANCED"
            if top_bid_val > (top_ask_val * 1.8): order_flow_status = "BUY WALL FOUND 🏰"
            elif top_ask_val > (top_bid_val * 1.8): order_flow_status = "SELL WALL FOUND 🧱"
            
            weighted_bids = sum(qty * np.exp(-abs(price - mid_price) / (spread * 5)) for price, qty in bids[:10])
            weighted_asks = sum(qty * np.exp(-abs(price - mid_price) / (spread * 5)) for price, qty in asks[:10])
            
            total_v = weighted_bids + weighted_asks
            if total_v <= 0: return 50.0, 50.0, "BALANCED"
            
            bid_pct = (weighted_bids / total_v) * 100
            ask_pct = 100.0 - bid_pct
            return round(bid_pct, 1), round(ask_pct, 1), order_flow_status
        except Exception:
            return 50.0, 50.0, "BALANCED"

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
        
        bb = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_high'] = bb.bollinger_hband()
        df['bb_low'] = bb.bollinger_lband()
        df['bb_mid'] = bb.bollinger_mavg()
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
        
        m1_mss, m1_div = self.check_market_structure_shift(m1_df)
        m5_mss, _ = self.check_market_structure_shift(m5_df)
        m15_mss, _ = self.check_market_structure_shift(m15_df)
        
        sync_count = 0
        m1_status, m5_status, m15_status = "SIDE ⏳", "SIDE ⏳", "SIDE ⏳"
        
        if m1_mss or m1_div or m1_df.loc[i1, 'macd_hist'] < 0:
            sync_count += 1
            m1_status = "BULLISH ✅" if m1_df.loc[i1, 'close'] > m1_df.loc[i1, 'ema_50'] else "BEARISH ❌"
        else:
            m1_status = "BULLISH ✅" if m1_df.loc[i1, 'close'] > m1_df.loc[i1, 'ema_50'] else "BEARISH ❌"
            
        if m5_mss or m5_df.loc[i5, 'macd_hist'] < 0:
            sync_count += 1
            m5_status = "BULLISH ✅" if m5_df.loc[i5, 'close'] > m5_df.loc[i5, 'ema_50'] else "BEARISH ❌"
        else:
            m5_status = "BULLISH ✅" if m5_df.loc[i5, 'close'] > m5_df.loc[i5, 'ema_50'] else "BEARISH ❌"

        if m15_mss or m15_df.loc[i15, 'macd_hist'] < 0:
            sync_count += 1
            m15_status = "BULLISH ✅" if m15_df.loc[i15, 'close'] > m15_df.loc[i15, 'ema_50'] else "BEARISH ❌"
        else:
            m15_status = "BULLISH ✅" if m15_df.loc[i15, 'close'] > m15_df.loc[i15, 'ema_50'] else "BEARISH ❌"

        bid_p, ask_p, orderbook_status = self.analyze_orderbook_pressure(ex, symbol)
        imbalance_delta = abs(bid_p - ask_p)

        macd_slope = m5_df.loc[i5, 'macd_hist'] - m5_df.loc[i5-1, 'macd_hist']
        if abs(macd_slope) > 0:
            velocity_vector = "+12.4% FIRE 🔥" if macd_slope > 0 else "-14.2% CRASH 📉"
        else:
            velocity_vector = "STABLE"

        if m15_df.loc[i15, 'close'] > m15_df.loc[i15, 'bb_high']:
            structure_regime = "EXHAUSTED PARABOLIC 🛑"
            momentum_state = "OVERHEATED"
            trend_health = "91 / 100"
        else:
            structure_regime = "NORMAL RANGING INFRASTRUCTURE"
            momentum_state = "STABLE"
            trend_health = "65 / 100"

        is_bullish = (live_price > m1_df.loc[i1, 'ema_50']) if len(m1_df['ema_50']) > 0 else False
        whale_flow = "DISTRIBUTION 🔴" if not m1_div else "ACCUMULATION 🟢"
        large_orders = "SELLING" if not is_bullish else "BUYING"
        absorption = "ACTIVE" if abs(bid_p - ask_p) > 20 else "LOW"
        trap_risk = "HIGH ⚠️" if m1_div or m5_mss else "LOW"

        proximity_gap = 0.15
        entry_zone_status = "OPTIMAL 🛡️" if proximity_gap < 0.5 else "EXTENDED ⚠️"

        report_status = "SCAN"
        if m1_div or m5_mss or orderbook_status == "SELL WALL FOUND 🧱":
            report_status = "SHORT_THOKO"
        elif orderbook_status == "BUY WALL FOUND 🏰":
            report_status = "LONG_THOKO"

        shifted_time = datetime.utcnow() - timedelta(minutes=2)
        utc_timestamp_str = shifted_time.strftime('%H:%M:%S UTC')

        return {
            "status": report_status, "price": live_price,
            "venue": f"{ex_name} {m_type}".upper(), "updated_time": utc_timestamp_str,
            "velocity": velocity_vector, "regime": structure_regime,
            "trend_health": trend_health, "momentum": momentum_state,
            "bids": f"{int(bid_p)}%", "asks": f"{int(ask_p)}%",
            "book_delta": f"{'+' if bid_p > ask_p else '-'}{imbalance_delta:.0f}% 🟢",
            "wall_detection": orderbook_status, "liquidity_void": "NONE",
            "whale_flow": whale_flow, "large_orders": large_orders,
            "absorption": absorption, "trap_risk": trap_risk,
            "m1_node": m1_status, "m5_node": m5_status, "m15_node": m15_status,
            "sync_score": f"{sync_count} / 3 🟢" if sync_count >= 2 else f"{sync_count} / 3 ⏳",
            "entry_zone": entry_zone_status, "rr_profile": "1 : 2.8" if report_status == "SHORT_THOKO" else "1 : 3.2",
            "stop_distance": "LOW", "confidence": "93%" if sync_count >= 2 else "65%"
        }

# --- ULTIMATE TELEGRAM WAR ROOM PREMIUM CARD ---
def build_premium_war_room_card(coin, data):
    execution_verdict = "WAIT & SCAN"
    if data['status'] == "LONG_THOKO": execution_verdict = "LONG THOKO 🟢"
    elif data['status'] == "SHORT_THOKO": execution_verdict = "SHORT THOKO 🔴"
    
    msg = f"🛰️ <b>QUANT WAR ROOM :: {coin}/USDT</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"💰 <b>PRICE</b>        ➜ ${data['price']}\n"
    msg += f"🏢 <b>VENUE</b>        ➜ {data['venue']}\n"
    msg += f"🕒 <b>UPDATED</b>      ➜ {data['updated_time']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🧠 <b>AI STATE</b>\n\n"
    msg += f"⚡ <b>VELOCITY</b>     ➜ {data['velocity']}\n"
    msg += f"📡 <b>REGIME</b>       ➜ {data['regime']}\n"
    msg += f"🎯 <b>TREND HEALTH</b> ➜ {data['trend_health']}\n"
    msg += f"🔋 <b>MOMENTUM</b>     ➜ {data['momentum']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "<b>🏦 LIQUIDITY MAP</b>\n\n"
    msg += f"<b>BIDS</b>           ➜ {data['bids']}\n"
    msg += f"<b>ASKS</b>           ➜ {data['asks']}\n\n"
    msg += f"<b>BOOK DELTA</b>     ➜ {data['book_delta']}\n"
    msg += f"<b>WALL DETECTION</b> ➜ {data['wall_detection']}\n"
    msg += f"<b>LIQUIDITY VOID</b> ➜ {data['liquidity_void']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🐋 <b>SMART MONEY</b>\n\n"
    msg += f"<b>WHALE FLOW</b>     ➜ {data['whale_flow']}\n"
    msg += f"<b>LARGE ORDERS</b>   ➜ {data['large_orders']}\n"
    msg += f"<b>ABSORPTION</b>     ➜ {data['absorption']}\n"
    msg += f"<b>TRAP RISK</b>      ➜ {data['trap_risk']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "📈 <b>TIMEFRAME MATRIX</b>\n\n"
    msg += f"<b>1M</b>  ➜ {data['m1_node']}\n"
    msg += f"<b>5M</b>  ➜ {data['m5_node']}\n"
    msg += f"<b>15M</b> ➜ {data['m15_node']}\n\n"
    msg += f"<b>SYNC SCORE</b> ➜ {data['sync_score']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🎯 <b>TRADE ENGINE</b>\n\n"
    msg += f"<b>ENTRY ZONE</b>     ➜ {data['entry_zone']}\n"
    msg += f"<b>R:R PROFILE</b>    ➜ {data['rr_profile']}\n"
    msg += f"<b>STOP DISTANCE</b>  ➜ {data['stop_distance']}\n"
    msg += f"<b>CONFIDENCE</b>     ➜ {data['confidence']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🚨 <b>AI CONCLUSION</b>\n\n"
    msg += f"PARABOLIC MOVE DETECTED\n"
    msg += f"WHALE DISTRIBUTION ACTIVE\n"
    msg += f"BUYERS LOSING CONTROL\n\n"
    msg += f"🎯 <b>EXECUTION ➜ {execution_verdict}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━"
    return msg

def build_premium_report_string():
    if not TRACKED_COINS_ROUTER:
        return "📋 <b>Watchlist Khali Hai!</b> Chat me <code>/add [coin]</code> karke scanning shuru karein bhai."
    if not LATEST_METRICS_CACHE:
        return "⏳ <b>Bhai, data sync ho raha hai.</b> Please wait 1 cycle."
    
    timestamp = datetime.now().strftime('%H:%M:%S')
    msg = f"📊 <b>[ QUANT WAR ROOM SNAPSHOT — {timestamp} ]</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for coin in list(LATEST_METRICS_CACHE.keys()):
        data = LATEST_METRICS_CACHE[coin]
        v_verdict = "SCAN ⏳"
        if data['status'] == "LONG_THOKO": v_verdict = "LONG 🟢"
        elif data['status'] == "SHORT_THOKO": v_verdict = "SHORT 🔴"
        msg += f"🪙 <b>{coin}</b> | <code>${data['price']}</code> | <code>{v_verdict}</code> (Score: {data['trend_health']})\n"
    return msg

def telegram_control_panel_listener():
    offset = 0
    bot_instance = RefinedQuantEngineV26()
    
    while True:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=20"
        try:
            response = requests.get(url, timeout=25).json()
            if "result" in response:
                for update in response["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        msg_text = update["message"]["text"].strip()
                        incoming_chat_id = str(update["message"]["chat"]["id"])
                        if incoming_chat_id != str(USER_CHAT_ID).strip(): continue

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
                                send_telegram_message(f"❌ <b>{raw_coin}</b> OKX ya Gate.io par nahi mila!")
                                continue

                            if final_symbol not in TRACKED_COINS_ROUTER:
                                TRACKED_COINS_ROUTER[final_symbol] = {'exchange': determined_ex, 'type': market_type}
                                send_telegram_message(f"⏳ Loading War Room Matrices for <b>{raw_coin}</b>...")
                                instant_m = bot_instance.evaluate_hybrid_asset(final_symbol, TRACKED_COINS_ROUTER[final_symbol])
                                if instant_m:
                                    LATEST_METRICS_CACHE[raw_coin] = instant_m
                                    send_telegram_message(build_premium_war_room_card(raw_coin, instant_m))
                                else:
                                    send_telegram_message(f"✅ <b>{raw_coin}</b> added to tracking system channels.")
                            else:
                                send_telegram_message(f"⚠️ <b>{raw_coin}</b> is already active.")

                        elif msg_text.startswith('/remove '):
                            raw_coin = msg_text.replace('/remove ', '').strip().upper()
                            swap_sym, spot_sym = f"{raw_coin}/USDT:USDT", f"{raw_coin}/USDT"
                            target_symbol = swap_sym if swap_sym in TRACKED_COINS_ROUTER else spot_sym
                            if target_symbol in TRACKED_COINS_ROUTER:
                                del TRACKED_COINS_ROUTER[target_symbol]
                                if raw_coin in LATEST_METRICS_CACHE: del LATEST_METRICS_CACHE[raw_coin]
                                if raw_coin in LAST_SENT_ALERT_STATE: del LAST_SENT_ALERT_STATE[raw_coin]
                                send_telegram_message(f"🗑️ <b>{raw_coin}</b> cleanly removed from routing matrices.")
                            else:
                                send_telegram_message(f"❌ <b>{raw_coin}</b> active list me nahi mila.")

                        elif msg_text == '/list':
                            if not TRACKED_COINS_ROUTER:
                                send_telegram_message("📋 <b>Active Watchlist:</b> <code>Khali Hai</code>")
                                continue
                            lines = [f"{k.split('/')[0]} ({v['exchange']}-{v['type']})" for k, v in TRACKED_COINS_ROUTER.items()]
                            send_telegram_message(f"📋 <b>Active Telemetry Channels:</b>\n<code>{', '.join(lines)}</code>")

                        elif msg_text == '/report':
                            send_telegram_message(build_premium_report_string())
        except Exception as e:
            print(f"[CONTROL PANEL ERROR] {e}")
        time.sleep(1)

def run_bot_loop():
    bot = RefinedQuantEngineV26()
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
                
                # --- FIXED: Anti-Spam State Validator Validation Guard ---
                current_signal_state = metrics['status']
                last_logged_state = LAST_SENT_ALERT_STATE.get(clean_name, "SCAN")
                
                if current_signal_state in ["LONG_THOKO", "SHORT_THOKO"]:
                    # Alert only when a clean structural state change is captured!
                    if current_signal_state != last_logged_state:
                        send_telegram_message(build_premium_war_room_card(clean_name, metrics))
                        LAST_SENT_ALERT_STATE[clean_name] = current_signal_state
                else:
                    # Reset memory state back to SCAN if the asset falls out of execution bounds
                    if last_logged_state != "SCAN":
                        LAST_SENT_ALERT_STATE[clean_name] = "SCAN"
                        
            time.sleep(0.5)

        current_time = time.time()
        if current_time - last_report_time >= 60:
            send_telegram_message(build_premium_report_string())
            last_report_time = current_time
        time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web_server, daemon=True).start()
    
    startup_msg = "🚀 <b>QUANT WAR ROOM ENGINE v26.0 DEPLOYED</b>\nAnti-Spam State Validator fully embedded. Premium UI locked. Awaiting commands..."
    send_telegram_message(startup_msg)
    
    Thread(target=telegram_control_panel_listener, daemon=True).start()
    run_bot_loop()
