
import requests
import time
import schedule
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL = "1h"

last_signals = {}

# ─────────────────────────────────────────
def get_klines(symbol, limit=150):
    try:
        r = requests.get(
            "https://api.binance.us/api/v3/klines",
            params={"symbol": symbol, "interval": INTERVAL, "limit": limit},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 60:
            return None
        return {
            "opens":   [float(c[1]) for c in data],
            "highs":   [float(c[2]) for c in data],
            "lows":    [float(c[3]) for c in data],
            "closes":  [float(c[4]) for c in data],
            "volumes": [float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"  eroare date {symbol}: {e}")
        return None

def calc_ema(closes, p):
    if len(closes) < p:
        return closes[-1]
    e = sum(closes[:p]) / p
    k = 2 / (p + 1)
    for c in closes[p:]:
        e = c * k + e * (1 - k)
    return e

def calc_rsi(closes, period=14):
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag/al))

def find_support_resistance(highs, lows, lookback=20):
    """
    Găsește niveluri cheie de suport și rezistență
    bazate pe swing highs/lows recente.
    """
    levels = []
    for i in range(2, lookback - 2):
        idx = -(i)
        # Swing High
        if highs[idx] > highs[idx-1] and highs[idx] > highs[idx-2] and \
           highs[idx] > highs[idx+1] and highs[idx] > highs[idx+2]:
            levels.append(("R", highs[idx]))
        # Swing Low
        if lows[idx] < lows[idx-1] and lows[idx] < lows[idx-2] and \
           lows[idx] < lows[idx+1] and lows[idx] < lows[idx+2]:
            levels.append(("S", lows[idx]))
    return levels

def is_rejection_candle(o, h, l, c, direction):
    """
    Detectează lumânări de respingere (pin bar / hammer / shooting star).
    direction: 'LONG' sau 'SHORT'
    """
    body     = abs(c - o)
    candle   = h - l
    if candle == 0:
        return False
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l

    # LONG — Hammer: corp mic sus, fitil lung jos
    if direction == "LONG":
        return (lower_wick > body * 2 and
                lower_wick > upper_wick * 2 and
                body < candle * 0.4)

    # SHORT — Shooting Star: corp mic jos, fitil lung sus
    if direction == "SHORT":
        return (upper_wick > body * 2 and
                upper_wick > lower_wick * 2 and
                body < candle * 0.4)

    return False

def get_trend(closes, ema50, ema200):
    """Trend simplu bazat pe EMA50 vs EMA200 și structură."""
    price = closes[-1]
    # Bullish: pret si EMA50 peste EMA200
    if price > ema200 and ema50 > ema200:
        return "BULLISH"
    # Bearish: pret si EMA50 sub EMA200
    elif price < ema200 and ema50 < ema200:
        return "BEARISH"
    return "NEUTRAL"

def analyze(symbol):
    d = get_klines(symbol)
    if not d:
        return None

    opens   = d["opens"]
    highs   = d["highs"]
    lows    = d["lows"]
    closes  = d["closes"]
    volumes = d["volumes"]

    price = closes[-1]  # Ultima lumânare închisă (cea de -1 e cea curentă, deci luăm -2 ca ultima închisă)
    # Folosim lumânarea -1 deoarece scanăm exact la închiderea orei
    last_o = opens[-1]
    last_h = highs[-1]
    last_l = lows[-1]
    last_c = closes[-1]

    # Indicatori
    ema200 = calc_ema(closes, min(200, len(closes)-1))
    ema50  = calc_ema(closes, 50)
    ema20  = calc_ema(closes, 20)
    rsi    = calc_rsi(closes)

    # Trend
    trend = get_trend(closes, ema50, ema200)

    # Suport & Rezistenta
    levels = find_support_resistance(highs, lows, lookback=30)

    # Volum
    vol_avg = sum(volumes[-20:]) / 20
    vol_ok  = volumes[-1] > vol_avg * 1.0

    # ATR
    atr = sum([highs[i]-lows[i] for i in range(-14, 0)]) / 14
    atr = max(atr, price * 0.004)

    # Verifică dacă prețul e lângă un nivel S/R (în raza de 1%)
    near_support    = None
    near_resistance = None
    for level_type, level_price in levels:
        dist = abs(price - level_price) / price
        if dist < 0.012:
            if level_type == "S":
                near_support    = level_price
            elif level_type == "R":
                near_resistance = level_price

    sig      = None
    reason   = []
    sr_level = None

    # ═══════════════════════════════════════
    # SEMNAL LONG
    # ═══════════════════════════════════════
    if trend in ["BULLISH", "NEUTRAL"]:
        long_conditions = []

        # 1. Lumânare bullish (verde) — susține trendul
        candle_bullish = last_c > last_o
        long_conditions.append(candle_bullish)
        if candle_bullish:
            reason.append("🕯 Lumânare bullish")

        # 2. Pret peste EMA200 sau aproape (max 5% sub)
        ema_ok = price > ema200 * 0.95
        long_conditions.append(ema_ok)
        if ema_ok:
            if price > ema200:
                reason.append("📈 Peste EMA200")
            else:
                reason.append("📈 Aproape EMA200")

        # 3. Respingere de la suport
        rejection_long = is_rejection_candle(last_o, last_h, last_l, last_c, "LONG")
        if near_support or rejection_long:
            long_conditions.append(True)
            if near_support:
                reason.append(f"🛡 Suport: ${near_support:.4f}")
                sr_level = near_support
            if rejection_long:
                reason.append("📌 Respingere (Hammer)")
        else:
            long_conditions.append(False)

        # 4. RSI nu e overbought
        rsi_ok = rsi < 65
        long_conditions.append(rsi_ok)
        if rsi_ok:
            reason.append(f"📊 RSI: {rsi:.1f}")

        # 5. Trend bullish confirmat
        if trend == "BULLISH":
            long_conditions.append(True)
            reason.append("✅ Trend BULLISH")
        else:
            long_conditions.append(False)

        if sum(long_conditions) >= 4:
            sig = "LONG"

    # ═══════════════════════════════════════
    # SEMNAL SHORT
    # ═══════════════════════════════════════
    if not sig and trend in ["BEARISH", "NEUTRAL"]:
        short_conditions = []

        # 1. Lumânare bearish (roșie) — susține trendul
        candle_bearish = last_c < last_o
        short_conditions.append(candle_bearish)
        if candle_bearish:
            reason.append("🕯 Lumânare bearish")

        # 2. Pret sub EMA200 sau aproape (max 5% peste)
        ema_ok = price < ema200 * 1.05
        short_conditions.append(ema_ok)
        if ema_ok:
            if price < ema200:
                reason.append("📉 Sub EMA200")
            else:
                reason.append("📉 Aproape EMA200")

        # 3. Respingere de la rezistență
        rejection_short = is_rejection_candle(last_o, last_h, last_l, last_c, "SHORT")
        if near_resistance or rejection_short:
            short_conditions.append(True)
            if near_resistance:
                reason.append(f"🚧 Rezistență: ${near_resistance:.4f}")
                sr_level = near_resistance
            if rejection_short:
                reason.append("📌 Respingere (Shooting Star)")
        else:
            short_conditions.append(False)

        # 4. RSI nu e oversold
        rsi_ok = rsi > 35
        short_conditions.append(rsi_ok)
        if rsi_ok:
            reason.append(f"📊 RSI: {rsi:.1f}")

        # 5. Trend bearish confirmat
        if trend == "BEARISH":
            short_conditions.append(True)
            reason.append("✅ Trend BEARISH")
        else:
            short_conditions.append(False)

        if sum(short_conditions) >= 4:
            sig = "SHORT"

    if not sig:
        return None

    # Anti-duplicat 2 ore
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 120:
            print(f"duplicat ({diff:.0f} min)")
            return None
    last_signals[key] = now

    # SL/TP
    if sig == "LONG":
        sl  = round(price - atr * 1.5, 6)
        tp1 = round(price + atr * 2,   6)
        tp2 = round(price + atr * 4,   6)
    else:
        sl  = round(price + atr * 1.5, 6)
        tp1 = round(price - atr * 2,   6)
        tp2 = round(price - atr * 4,   6)

    risk   = round(abs(price - sl) / price * 100, 2)
    reward = round(abs(tp1 - price) / price * 100, 2)
    rr     = round(reward / risk, 1) if risk > 0 else 0

    return {
        "symbol":  symbol,
        "direction": sig,
        "price":   price,
        "sl":      sl,
        "tp1":     tp1,
        "tp2":     tp2,
        "rsi":     round(rsi, 1),
        "trend":   trend,
        "risk":    risk,
        "reward":  reward,
        "rr":      rr,
        "reason":  reason,
        "ema200":  round(ema200, 4),
        "time":    now.strftime("%H:%M %d.%m.%Y"),
    }

def fmt(p):
    if p > 100:   return f"${p:,.2f}"
    elif p > 1:   return f"${p:.4f}"
    else:         return f"${p:.6f}"

def send_telegram(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        print(f"  Telegram: {'OK' if r.status_code==200 else r.text}")
    except Exception as e:
        print(f"  Eroare Telegram: {e}")

def scan():
    now = datetime.now()
    print(f"\n🔍 Scanare {now.strftime('%H:%M:%S')}")
    found = 0

    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym)
        if sig:
            e     = "🟢" if sig["direction"] == "LONG" else "🔴"
            arrow = "⬆️" if sig["direction"] == "LONG" else "⬇️"
            t     = "🟢 BULLISH" if sig["trend"]=="BULLISH" else "🔴 BEARISH" if sig["trend"]=="BEARISH" else "🟡 NEUTRAL"
            print(f"{sig['direction']}! RSI:{sig['rsi']} R/R:1:{sig['rr']}")

            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *TP1:* {fmt(sig['tp1'])} (+{sig['reward']}%)\n"
            msg += f"🎯 *TP2:* {fmt(sig['tp2'])} (+{round(sig['reward']*2,2)}%)\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI: `{sig['rsi']}` | EMA200: `{fmt(sig['ema200'])}`\n"
            msg += f"📈 Trend: {t}\n"
            msg += f"📐 R/R: *1:{sig['rr']}*\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"✅ *Motive:*\n"
            for r in sig["reason"]:
                msg += f"  • {r}\n"
            msg += f"🕐 {sig['time']}\n"
            msg += f"_Tool educational. Nu e sfat financiar._"

            send_telegram(msg)
            found += 1
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.3)

    print(f"  Total: {found} semnal(e)")

# Pornire
send_telegram(
    f"🤖 *NEXUS Bot v4.0 ACTIV* ✅\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"• Monede: {', '.join(SYMBOLS)}\n"
    f"• Timeframe: 1H\n"
    f"• Logică: Suport/Rezistență + EMA200 + Trend + Respingeri\n"
    f"• Semnale: la închiderea lumânării de 1H\n"
    f"• Lumânare de confirmare: obligatorie\n"
    f"• Anti-duplicate: 2 ore\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"_Simplu. Clar. Precis._"
)

scan()

# Scanare la ore fixe — la 5 minute după închiderea lumânării de 1H
# (:05 în fiecare oră) ca să fie lumânarea complet închisă
schedule.every().hour.at(":05").do(scan)

print("⏰ Scanare la ora :05 în fiecare oră. Running...\n")
while True:
    schedule.run_pending()
    time.sleep(1)
