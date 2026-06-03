import requests
import time
import schedule
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# v4.3: 14 monede - majoră, memes, DeFi, Layer 1
SYMBOLS = [
    # Originale
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT",
    # Memes
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    # DeFi
    "UNIUSDT", "AAVEUSDT", "LINKUSDT",
    # Layer 1 bonus
    "AVAXUSDT", "DOTUSDT",
]

INTERVAL = "1h"

last_signals = {}
signals_today = []
MAX_SIGNALS_PER_DAY = 3

def get_klines(symbol, interval=INTERVAL, limit=100):
    try:
        url = "https://api.binance.us/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None
        return {
            "closes":  [float(c[4]) for c in data],
            "highs":   [float(c[2]) for c in data],
            "lows":    [float(c[3]) for c in data],
            "volumes": [float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"eroare date: {e}")
        return None

def calc_rsi(closes, period=14):
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag/al))

def calc_ema(closes, p):
    if len(closes) < p:
        return closes[-1]
    e = sum(closes[:p]) / p
    k = 2 / (p + 1)
    for c in closes[p:]:
        e = c * k + e * (1 - k)
    return e

def find_swings(data, lookback=5):
    highs = data["highs"]
    lows  = data["lows"]
    swing_highs = []
    swing_lows  = []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows

def find_supports_resistances(swing_highs, swing_lows, price, min_distance_pct=0.003):
    min_dist = price * min_distance_pct
    resistances = sorted(
        [h[1] for h in swing_highs if h[1] > price + min_dist],
        key=lambda x: x - price
    )
    supports = sorted(
        [l[1] for l in swing_lows if l[1] < price - min_dist],
        key=lambda x: price - x
    )
    return resistances, supports

def is_near_level(price, level, tolerance_pct=0.008):
    return abs(price - level) / price < tolerance_pct

def check_trend(closes, ema200):
    """Trend detection cu prag agresiv"""
    price = closes[-1]
    distance_pct = abs(price - ema200) / price * 100
    
    last_3 = closes[-3:]
    declining = last_3[0] > last_3[1] > last_3[2]
    rising = last_3[0] < last_3[1] < last_3[2]
    
    avg_10 = sum(closes[-10:]) / 10
    avg_20 = sum(closes[-20:]) / 20
    
    if price < ema200:
        if distance_pct > 1.0 or declining or avg_10 < avg_20 * 0.99:
            return "BEARISH"
    
    if price > ema200:
        if distance_pct > 1.0 or rising or avg_10 > avg_20 * 1.01:
            return "BULLISH"
    
    return "SIDEWAYS"

def is_support_valid(support, recent_lows, recent_closes, lookback=10):
    for low in recent_lows[-lookback:]:
        if low < support * 0.995:
            return False
    for close in recent_closes[-lookback:]:
        if close < support * 0.997:
            return False
    return True

def is_resistance_valid(resistance, recent_highs, recent_closes, lookback=10):
    for high in recent_highs[-lookback:]:
        if high > resistance * 1.005:
            return False
    for close in recent_closes[-lookback:]:
        if close > resistance * 1.003:
            return False
    return True

def has_lower_lows(lows, lookback=10):
    if len(lows) < lookback:
        return False
    recent_5 = lows[-5:]
    previous_5 = lows[-lookback:-5]
    min_recent = min(recent_5)
    min_previous = min(previous_5)
    return min_recent < min_previous * 0.995

def has_higher_highs(highs, lookback=10):
    if len(highs) < lookback:
        return False
    recent_5 = highs[-5:]
    previous_5 = highs[-lookback:-5]
    max_recent = max(recent_5)
    max_previous = max(previous_5)
    return max_recent > max_previous * 1.005

def get_distanced_tps(price, levels, direction, min_distance_pct=0.005):
    if not levels:
        return None, None
    
    buffer = price * 0.003
    
    if direction == "SHORT":
        tp1 = levels[0] + buffer
        tp2 = None
        for level in levels[1:]:
            if (tp1 - level) / price >= min_distance_pct:
                tp2 = level + buffer
                break
        if tp2 is None:
            tp2 = price - (price - tp1) * 1.8
    else:
        tp1 = levels[0] - buffer
        tp2 = None
        for level in levels[1:]:
            if (level - tp1) / price >= min_distance_pct:
                tp2 = level - buffer
                break
        if tp2 is None:
            tp2 = price + (tp1 - price) * 1.8
    
    return tp1, tp2

def analyze(symbol):
    d = get_klines(symbol, INTERVAL, 100)
    if not d:
        return None
    
    closes  = d["closes"]
    highs   = d["highs"]
    lows    = d["lows"]
    price   = closes[-1]
    
    rsi = calc_rsi(closes)
    ema200 = calc_ema(closes, min(200, len(closes)-1))
    trend = check_trend(closes, ema200)
    
    swing_highs, swing_lows = find_swings(d, lookback=5)
    resistances, supports = find_supports_resistances(swing_highs, swing_lows, price)
    
    distance_ema_pct = (price - ema200) / price * 100
    block_long = distance_ema_pct < -1.0
    block_short = distance_ema_pct > 1.0
    
    structure_bearish = has_lower_lows(lows, lookback=10)
    structure_bullish = has_higher_highs(highs, lookback=10)
    
    near_resistance = None
    near_support = None
    
    if resistances:
        for r in resistances[:3]:
            if is_near_level(price, r):
                if is_resistance_valid(r, highs, closes, lookback=10):
                    near_resistance = r
                    break
    
    if supports:
        for s in supports[:3]:
            if is_near_level(price, s):
                if is_support_valid(s, lows, closes, lookback=10):
                    near_support = s
                    break
    
    sig = None
    reasons = []
    
    # SHORT
    if (near_resistance 
        and rsi > 40 and rsi < 70 
        and trend != "BULLISH" 
        and not block_short
        and not structure_bullish):
        sig = "SHORT"
        reasons.append("📉 Sub EMA200" if price < ema200 else "↔️ Sideways la EMA200")
        reasons.append(f"🚧 Rezistență validă: {fmt(near_resistance)}")
        reasons.append(f"📊 RSI: {rsi:.1f}")
        reasons.append(f"✅ Trend {trend}")
        reasons.append("📉 Structură: Lower Lows" if has_lower_lows(lows) else "↔️ Structură: stabilă")
    
    # LONG
    elif (near_support 
          and rsi < 60 and rsi > 30 
          and trend != "BEARISH" 
          and not block_long
          and not structure_bearish):
        sig = "LONG"
        reasons.append("📈 Peste EMA200" if price > ema200 else "↔️ Sideways la EMA200")
        reasons.append(f"🟩 Support valid: {fmt(near_support)}")
        reasons.append(f"📊 RSI: {rsi:.1f}")
        reasons.append(f"✅ Trend {trend}")
        reasons.append("📈 Structură: Higher Highs" if has_higher_highs(highs) else "↔️ Structură: stabilă")
    
    if not sig:
        return None
    
    # Anti-duplicat 3 ore
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 180:
            print(f"duplicat ({diff:.0f} min)")
            return None
    
    buffer = price * 0.003
    
    if sig == "SHORT":
        sl = near_resistance + buffer
        tp1, tp2 = get_distanced_tps(price, supports, "SHORT")
        if tp1 is None:
            tp1 = price * 0.985
            tp2 = price * 0.975
    else:
        sl = near_support - buffer
        tp1, tp2 = get_distanced_tps(price, resistances, "LONG")
        if tp1 is None:
            tp1 = price * 1.015
            tp2 = price * 1.025
    
    risk    = round(abs(price - sl) / price * 100, 2)
    reward  = round(abs(tp1 - price) / price * 100, 2)
    reward2 = round(abs(tp2 - price) / price * 100, 2)
    rr      = round(reward / risk, 2) if risk > 0 else 0
    rr2     = round(reward2 / risk, 2) if risk > 0 else 0
    
    if rr < 1.2:
        print(f"R/R prost: {rr}")
        return None
    
    if risk > 2.0:
        print(f"risc prea mare: {risk}%")
        return None
    
    tp_distance_pct = abs(tp2 - tp1) / price * 100
    if tp_distance_pct < 0.4:
        print(f"TP-uri prea apropiate: {tp_distance_pct:.2f}%")
        return None
    
    last_signals[key] = now
    
    # NOU v4.3: rotunjire mai precisă pentru prețuri mici (PEPE, SHIB)
    if price < 0.01:
        precision = 10
    elif price < 1:
        precision = 8
    else:
        precision = 6
    
    return {
        "symbol": symbol, "direction": sig, "price": price,
        "sl": round(sl, precision), "tp1": round(tp1, precision), "tp2": round(tp2, precision),
        "rsi": round(rsi, 1), "ema200": round(ema200, precision),
        "ema_distance": round(distance_ema_pct, 2),
        "risk": risk, "reward": reward, "reward2": reward2,
        "rr": rr, "rr2": rr2,
        "trend": trend, "reasons": reasons,
        "time": now.strftime("%H:%M %d.%m.%Y")
    }

def fmt(p):
    """Formater pentru prețuri - ajustat pentru memes (PEPE, SHIB) v4.3"""
    if p > 1000:
        return f"${p:,.2f}"
    elif p > 100:
        return f"${p:,.2f}"
    elif p > 1:
        return f"${p:.4f}"
    elif p > 0.01:
        return f"${p:.5f}"
    elif p > 0.0001:
        return f"${p:.7f}"
    elif p > 0.000001:
        return f"${p:.9f}"
    else:
        return f"${p:.11f}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"Telegram: {'OK' if r.status_code==200 else r.text}")
    except Exception as e:
        print(f"Eroare Telegram: {e}")

def reset_daily_count():
    global signals_today
    signals_today = []
    print("Contor zilnic resetat")

def scan():
    global signals_today
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    
    now = datetime.now()
    signals_today = [s for s in signals_today if (now - s).total_seconds() < 86400]
    
    if len(signals_today) >= MAX_SIGNALS_PER_DAY:
        print(f"  Limită atinsă: {len(signals_today)}/{MAX_SIGNALS_PER_DAY}")
        return
    
    for sym in SYMBOLS:
        if len(signals_today) >= MAX_SIGNALS_PER_DAY:
            break
        
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym)
        if sig:
            e     = "🟢" if sig["direction"]=="LONG" else "🔴"
            arrow = "⬆️" if sig["direction"]=="LONG" else "⬇️"
            print(f"{sig['direction']}! RSI:{sig['rsi']} R/R:{sig['rr']}")
            
            count_after = len(signals_today) + 1
            ema_sign = "+" if sig['ema_distance'] >= 0 else ""
            
            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *TP1:* {fmt(sig['tp1'])} (+{sig['reward']}%) | R/R 1:{sig['rr']}\n"
            msg += f"🎯 *TP2:* {fmt(sig['tp2'])} (+{sig['reward2']}%) | R/R 1:{sig['rr2']}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI: `{sig['rsi']}` | EMA200: {fmt(sig['ema200'])} ({ema_sign}{sig['ema_distance']}%)\n"
            msg += f"📈 *Trend:* {sig['trend']}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"*✅ Motive:*\n"
            for reason in sig['reasons']:
                msg += f"  • {reason}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"🕐 {sig['time']} | Semnal {count_after}/{MAX_SIGNALS_PER_DAY} azi\n"
            msg += f"_Tool educational. Nu e sfat financiar._"
            
            send_telegram(msg)
            signals_today.append(now)
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.5)
    
    print(f"  Status: {len(signals_today)}/{MAX_SIGNALS_PER_DAY} semnale azi")

# Mesaj de startup
send_telegram(
    f"🤖 *NEXUS Bot v4.3 ACTIV* ✅\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"🆕 *Listă extinsă - 14 monede:*\n"
    f"💎 *Top:* BTC, ETH, SOL, XRP, LTC, ADA\n"
    f"🐶 *Memes:* DOGE, SHIB, PEPE\n"
    f"🦄 *DeFi:* UNI, AAVE, LINK\n"
    f"⛰️ *Layer 1:* AVAX, DOT\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"📊 *Logică:*\n"
    f"  • RSI (40-70 SHORT, 30-60 LONG)\n"
    f"  • Suport/Rezistență validate 10h\n"
    f"  • Trend EMA200 + media + momentum\n"
    f"  • Structură Lower Lows/Higher Highs\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"🚦 *Filtre stricte:*\n"
    f"  • R/R minim 1:1.2 | Risc max 2%\n"
    f"  • Max {MAX_SIGNALS_PER_DAY} semnale/zi\n"
    f"  • Anti-duplicat 3 ore\n"
    f"  • Limită EMA200 ±1.0%\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"• Timeframe: 1H | Scan: 15min\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"_Mai multe monede, aceleași standarde._"
)
scan()
schedule.every(15).minutes.do(scan)
schedule.every().day.at("00:00").do(reset_daily_count)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
