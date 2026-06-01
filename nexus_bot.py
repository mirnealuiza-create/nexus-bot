import requests
import time
import schedule
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL = "1h"

last_signals = {}
signals_today = []  # NOU v4.0: limita semnale/zi
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
    """Găsește swing highs și lows"""
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
    """Suporturi (sub preț) și rezistențe (peste preț), sortate după apropiere"""
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
    """Verifică dacă prețul e aproape de un nivel (default 0.8%)"""
    return abs(price - level) / price < tolerance_pct

def check_trend(closes, ema200):
    """
    Trend simplu: BULLISH / BEARISH / SIDEWAYS pe baza ultimelor 20 close
    """
    price = closes[-1]
    recent_avg = sum(closes[-20:]) / 20
    
    # Bullish: preț peste EMA200 ȘI peste media recentă
    if price > ema200 and price > recent_avg:
        return "BULLISH"
    # Bearish: preț sub EMA200 ȘI sub media recentă
    if price < ema200 and price < recent_avg:
        return "BEARISH"
    return "SIDEWAYS"

def analyze(symbol):
    d = get_klines(symbol, INTERVAL, 100)
    if not d:
        return None
    
    closes  = d["closes"]
    highs   = d["highs"]
    lows    = d["lows"]
    price   = closes[-1]
    
    # Indicatorii
    rsi = calc_rsi(closes)
    ema200 = calc_ema(closes, min(200, len(closes)-1))
    trend = check_trend(closes, ema200)
    
    # Swing points + suporturi/rezistențe
    swing_highs, swing_lows = find_swings(d, lookback=5)
    resistances, supports = find_supports_resistances(swing_highs, swing_lows, price)
    
    # Verifică dacă prețul e aproape de o rezistență sau support
    near_resistance = None
    near_support = None
    
    if resistances:
        if is_near_level(price, resistances[0]):
            near_resistance = resistances[0]
    
    if supports:
        if is_near_level(price, supports[0]):
            near_support = supports[0]
    
    sig = None
    reasons = []
    
    # ============ LOGICA SHORT ============
    # Conditii: preț la rezistență + RSI nu oversold + trend nu bullish
    if near_resistance and rsi > 40 and rsi < 70 and trend != "BULLISH":
        sig = "SHORT"
        reasons.append("📉 Sub EMA200" if price < ema200 else "↔️ Sideways la EMA200")
        reasons.append(f"🚧 Rezistență: ${near_resistance:.4f}")
        reasons.append(f"📊 RSI: {rsi:.1f}")
        reasons.append(f"✅ Trend {trend}")
    
    # ============ LOGICA LONG ============
    # Conditii: preț la support + RSI nu overbought + trend nu bearish
    elif near_support and rsi < 60 and rsi > 30 and trend != "BEARISH":
        sig = "LONG"
        reasons.append("📈 Peste EMA200" if price > ema200 else "↔️ Sideways la EMA200")
        reasons.append(f"🟩 Support: ${near_support:.4f}")
        reasons.append(f"📊 RSI: {rsi:.1f}")
        reasons.append(f"✅ Trend {trend}")
    
    if not sig:
        return None
    
    # Anti-duplicat 3 ore (mai strict ca înainte)
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 180:
            print(f"duplicat ({diff:.0f} min)")
            return None
    
    # ============ SL/TP INTELIGENT ============
    buffer = price * 0.003  # 0.3% buffer
    
    if sig == "SHORT":
        # SL: peste rezistență
        sl = near_resistance + buffer
        # TP1: primul support sub preț
        # TP2: al doilea support
        if len(supports) >= 2:
            tp1 = supports[0] + buffer  # ieșim puțin înainte
            tp2 = supports[1] + buffer
        elif len(supports) == 1:
            tp1 = supports[0] + buffer
            tp2 = price - (price - tp1) * 1.8
        else:
            # Fallback - 1.5% și 2.5%
            tp1 = price * 0.985
            tp2 = price * 0.975
    else:  # LONG
        sl = near_support - buffer
        if len(resistances) >= 2:
            tp1 = resistances[0] - buffer
            tp2 = resistances[1] - buffer
        elif len(resistances) == 1:
            tp1 = resistances[0] - buffer
            tp2 = price + (tp1 - price) * 1.8
        else:
            tp1 = price * 1.015
            tp2 = price * 1.025
    
    risk    = round(abs(price - sl) / price * 100, 2)
    reward  = round(abs(tp1 - price) / price * 100, 2)
    reward2 = round(abs(tp2 - price) / price * 100, 2)
    rr      = round(reward / risk, 2) if risk > 0 else 0
    rr2     = round(reward2 / risk, 2) if risk > 0 else 0
    
    # ============ FILTRU R/R MINIM 1:1.2 ============
    if rr < 1.2:
        print(f"R/R prost: {rr}")
        return None
    
    # ============ FILTRU RISK MAXIM 2% ============
    if risk > 2.0:
        print(f"risc prea mare: {risk}%")
        return None
    
    last_signals[key] = now
    
    return {
        "symbol": symbol, "direction": sig, "price": price,
        "sl": round(sl, 6), "tp1": round(tp1, 6), "tp2": round(tp2, 6),
        "rsi": round(rsi, 1), "ema200": round(ema200, 4),
        "risk": risk, "reward": reward, "reward2": reward2,
        "rr": rr, "rr2": rr2,
        "trend": trend, "reasons": reasons,
        "time": now.strftime("%H:%M %d.%m.%Y")
    }

def fmt(p):
    if p > 1000:
        return f"${p:,.2f}"
    elif p > 100:
        return f"${p:,.2f}"
    elif p > 1:
        return f"${p:.4f}"
    else:
        return f"${p:.6f}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"Telegram: {'OK' if r.status_code==200 else r.text}")
    except Exception as e:
        print(f"Eroare Telegram: {e}")

def reset_daily_count():
    """Resetează contorul la miezul nopții"""
    global signals_today
    signals_today = []
    print("Contor zilnic resetat")

def scan():
    global signals_today
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    
    # Curăță semnalele vechi (mai vechi de 24h)
    now = datetime.now()
    signals_today = [s for s in signals_today if (now - s).total_seconds() < 86400]
    
    # Verifică limita zilnică
    if len(signals_today) >= MAX_SIGNALS_PER_DAY:
        print(f"  Limită atinsă: {len(signals_today)}/{MAX_SIGNALS_PER_DAY} semnale azi")
        return
    
    for sym in SYMBOLS:
        # Stop dacă am atins limita
        if len(signals_today) >= MAX_SIGNALS_PER_DAY:
            print(f"  Limită atinsă în timpul scanării")
            break
        
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym)
        if sig:
            e     = "🟢" if sig["direction"]=="LONG" else "🔴"
            arrow = "⬆️" if sig["direction"]=="LONG" else "⬇️"
            print(f"{sig['direction']}! RSI:{sig['rsi']} R/R:{sig['rr']}")
            
            count_after = len(signals_today) + 1
            
            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *TP1:* {fmt(sig['tp1'])} (+{sig['reward']}%) | R/R 1:{sig['rr']}\n"
            msg += f"🎯 *TP2:* {fmt(sig['tp2'])} (+{sig['reward2']}%) | R/R 1:{sig['rr2']}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI: `{sig['rsi']}` | EMA200: {fmt(sig['ema200'])}\n"
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

send_telegram(
    f"🤖 *NEXUS Bot v4.0 ACTIV* ✅\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"📊 *Logică simplificată:*\n"
    f"  • RSI (40-70 pentru SHORT, 30-60 pentru LONG)\n"
    f"  • Suport/Rezistență reale\n"
    f"  • Trend EMA200 + media 20\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"🎯 *SL/TP din chart, nu din formulă:*\n"
    f"  • SL = peste rezistență / sub support\n"
    f"  • TP1 = primul nivel | TP2 = al doilea\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"🚦 *Filtre stricte:*\n"
    f"  • R/R minim 1:1.2\n"
    f"  • Risc maxim 2%\n"
    f"  • *Max {MAX_SIGNALS_PER_DAY} semnale/zi*\n"
    f"  • Anti-duplicat 3 ore\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"• Monede: {', '.join(SYMBOLS)}\n"
    f"• Timeframe: 1H | Scan: 15min\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"_Calitate. Mai puține semnale, mai bune..._"
)
scan()
schedule.every(15).minutes.do(scan)
# Reset contor la miezul nopții
schedule.every().day.at("00:00").do(reset_daily_count)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
