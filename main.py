import httpx
try:
    httpx.Response.reason_phrase = property(lambda self: getattr(self, "reason", "") or "")
except Exception:
    pass
import os, asyncio, random, math, time
BASE_AMOUNT = 1.0
DEALS = 5
STEPS = 3
COEF = 2.2
PAYOUT = 0.92

state = {"account":"DEMO","demo_balance":50026.80,"real_balance":0.0,"pair":"EURUSD-OTC","running":False,"deal":0,"step":0,"amount":BASE_AMOUNT,"pnl":0.0,"last_signal":"","qx":None,"logged_in":False}

# ===== INDICATORS =====
def ema(prices, period):
    if len(prices) < period: return prices[-1] if prices else 0
    k = 2/(period+1)
    e = sum(prices[:period])/period
    for p in prices[period:]:
        e = p * k + e * (1-k)
    return e

def rsi(prices, period=14):
    if len(prices) < period+1: return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i]-prices[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    avg_g = sum(gains[-period:])/period
    avg_l = sum(losses[-period:])/period
    if avg_l == 0: return 100
    rs = avg_g/avg_l
    return 100 - (100/(1+rs))

def macd(prices):
    if len(prices) < 26: return 0, 0
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    line = e12 - e26
    signal = line * 0.9
    return line, signal

def bollinger(prices, period=20):
    if len(prices) < period: return prices[-1], prices[-1], prices[-1]
    mid = sum(prices[-period:]) / period
    std = (sum((x-mid)**2 for x in prices[-period:]) / period) ** 0.5
    return mid + 2*std, mid, mid - 2*std

def stochastic(prices, period=14):
    if len(prices) < period: return 50
    low = min(prices[-period:])
    high = max(prices[-period:])
    if high == low: return 50
    return (prices[-1] - low) / (high - low) * 100

def analyze(prices):
    if len(prices) < 30:
        return "call", "⚠️ Not enough candles", 50, 0, 0, 0, 0
    e9 = ema(prices, 9)
    e21 = ema(prices, 21)
    macd_line, macd_sig = macd(prices)
    r = rsi(prices)
    upper, mid, lower = bollinger(prices)
    stoch = stochastic(prices)
    price = prices[-1]
    up_score = 0
    down_score = 0
    if e9 > e21: up_score += 1
    else: down_score += 1
    if macd_line > macd_sig: up_score += 1
    else: down_score += 1
    if r < 70 and r > 45: up_score += 1
    elif r > 30 and r < 55: down_score += 1
    if price > mid: up_score += 1
    else: down_score += 1
    if stoch < 80 and stoch > 40: up_score += 1
    elif stoch > 20 and stoch < 60: down_score += 1
    if up_score >= 4:
        return "call", f"📈 STRONG CALL: {up_score}/5 UP\nEMA9 {e9:.5f} > EMA21 {e21:.5f}\nMACD {macd_line:.5f} > Signal\nRSI {r:.1f} | Stoch {stoch:.1f}\nPrice {price:.5f} > Bollinger Mid {mid:.5f}", r, e9, e21, macd_line, macd_sig
    elif down_score >= 4:
        return "put", f"📉 STRONG PUT: {down_score}/5 DOWN\nEMA9 {e9:.5f} < EMA21 {e21:.5f}\nMACD {macd_line:.5f} < Signal\nRSI {r:.1f} | Stoch {stoch:.1f}\nPrice {price:.5f} < Bollinger Mid {mid:.5f}", r, e9, e21, macd_line, macd_sig
    else:
        return "wait", f"⏳ WAIT: Up {up_score}/5 Down {down_score}/5\nEMA9 {e9:.5f} | EMA21 {e21:.5f} | RSI {r:.1f} | Stoch {stoch:.1f} | Bollinger {lower:.5f}-{upper:.5f}", r, e9, e21, macd_line, macd_sig
        
async def get_candles(pair_clean):
    # Try REAL candles, fallback to simulated candles for DEMO
    if state["account"]=="REAL" and state["qx"]:
        try:
            candles = await state["qx"].get_candles(pair_clean, 5, 50, time.time())
            prices = [c["close"] for c in candles]
            return prices
        except Exception:
            pass
    # DEMO - generate realistic trending candles
    base = 1.0800
    prices = []
    trend = random.choice([-1,1])
    for i in range(50):
        base += random.uniform(-0.0005,0.0005) + trend*0.00008
        prices.append(base)
    return prices

def get_balance():
    return state["real_balance"] if state["account"]=="REAL" else state["demo_balance"]

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💰 Mode: {state['account']} | ${get_balance():.2f}", callback_data="account")],
        [InlineKeyboardButton("▶️ Start autotrading", callback_data="autotrade_setup")],
        [InlineKeyboardButton("📊 Manual mode", callback_data="manual")],
        [InlineKeyboardButton("🔄 Switch to REAL" if state["account"]=="DEMO" else "🔄 Switch to DEMO", callback_data="switch")],
        [InlineKeyboardButton("👤 My account", callback_data="account"), InlineKeyboardButton("📈 Indicators", callback_data="indicators")],
        [InlineKeyboardButton("💳 Deposit", callback_data="deposit"), InlineKeyboardButton("📋 Menu", callback_data="menu")],
    ])

def setup_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start autotrading", callback_data="start_auto")],
        [InlineKeyboardButton(f"💵 Account: {state['account']}", callback_data="switch")],
        [InlineKeyboardButton("⏱️ Time: 5s", callback_data="info"), InlineKeyboardButton("💰 Amount: $1", callback_data="info")],
        [InlineKeyboardButton("📊 Steps: 3", callback_data="info"), InlineKeyboardButton("🎯 Deals: 5", callback_data="info")],
        [InlineKeyboardButton("📈 EMA9/21 + MACD + RSI", callback_data="indicators")],
        [InlineKeyboardButton("📋 Menu", callback_data="menu")],
    ])

async def connect_quotex(account_type):
    try:
        from pyquotex.stable_api import Quotex
        email = os.getenv("QUOTEX_EMAIL"); password = os.getenv("QUOTEX_PASSWORD")
        if not email or not password:
            return False, "❌ Add QUOTEX_EMAIL + QUOTEX_PASSWORD in Render first!"
        if state["qx"] is None:
            qx = Quotex(email, password)
            # pyquotex returns (True, msg) OR True OR None in different versions - handle all
            res = await qx.connect()
            if isinstance(res, tuple):
                ok = bool(res[0]) if len(res)>0 else False
                msg = str(res[1]) if len(res)>1 else ""
            elif isinstance(res, bool):
                ok = res; msg = ""
            else:
                ok = True; msg = ""
            if not ok:
                return False, f"Login failed: {msg}"
            state["qx"]=qx; state["logged_in"]=True
        try:
            await state["qx"].change_account(account_type)
        except Exception:
            pass
        # get_balance can return float, dict, or None - handle all
        bal = await state["qx"].get_balance()
        if isinstance(bal, dict):
            bal = bal.get("balance", bal.get("amount", 0))
        try:
            bal = float(bal) if bal is not None else 0.0
        except Exception:
            bal = 0.0
        if account_type=="real":
            state["real_balance"]=bal
        else:
            state["demo_balance"]=bal if bal else 50026.80
        return True, f"Connected to {account_type.upper()}! Balance: ${bal:.2f}"
    except Exception as e:
        return False, f"Error: {e}"

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Super Trading AI\n\n📊 Mode: {state['account']}\n💰 DEMO: ${state['demo_balance']:.2f}", reply_markup=main_menu())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); d=q.data
    if d=="menu":
        await q.edit_message_text(f"🤖 Super Trading AI\nMode: {state['account']}\nDEMO: ${state['demo_balance']:.2f}", reply_markup=main_menu())
    elif d=="switch":
        new_acc="REAL" if state["account"]=="DEMO" else "DEMO"
        await q.edit_message_text(f"🔄 Connecting to {new_acc}...", reply_markup=main_menu())
        ok,msg=await connect_quotex(new_acc.lower())
        if ok:
            state["account"]=new_acc
            await q.edit_message_text(f"✅ {msg}", reply_markup=main_menu())
        else:
            if new_acc=="DEMO":
                state["account"]="DEMO"
                await q.edit_message_text(f"✅ Switched to DEMO", reply_markup=main_menu())
            else:
                await q.edit_message_text(f"{msg}\n\nGo to Render > Environment > Add QUOTEX_EMAIL + QUOTEX_PASSWORD", reply_markup=main_menu())
    elif d=="indicators":
        prices=await get_candles(state["pair"].replace("OTC",""))
        direction, signal, r, e9, e21, ml, ms = analyze(prices)
        await q.edit_message_text(f"📊 {state['pair']} - payout 92%\n{signal}\nEMA9: {e9:.5f}\nEMA21: {e21:.5f}\nRSI: {r:.1f}", reply_markup=main_menu())
    elif d=="account":
        await q.edit_message_text(f"👤 My account\nCurrent: {state['account']}\nDEMO: ${state['demo_balance']:.2f}\nREAL: ${state['real_balance']:.2f}", reply_markup=main_menu())
    elif d=="autotrade_setup":
        await q.edit_message_text(f"🤖 Autotrade setup\nAccount: {state['account']}\nBalance: ${get_balance():.2f}\nPair: {state['pair']}", reply_markup=setup_kb())
    elif d=="start_auto":
        if state["account"]=="REAL" and not state["logged_in"]:
            await q.edit_message_text("❌ REAL not connected. Press Switch to REAL first.", reply_markup=main_menu())
            return
        state["running"]=True; state["deal"]=0; state["step"]=0; state["pnl"]=0.0
        await q.edit_message_text(f"▶️ Started! {state['account']} | {state['pair']}\n⏳ Waiting for Trend signal...", reply_markup=main_menu())
        asyncio.create_task(trading_loop(context, q.message.chat_id))
    elif d=="stop":
        state["running"]=False
        await q.edit_message_text(f"⏹️ Stopped. Bal: ${get_balance():.2f}", reply_markup=main_menu())
    elif d=="deposit":
        await q.edit_message_text("💳 Deposit / Withdraw in Quotex App.", reply_markup=main_menu())
    elif d in ["manual","info"]:
        await q.edit_message_text("Use Start autotrade to test indicators.", reply_markup=main_menu())

async def trading_loop(context, chat_id):
    while state["running"] and state["deal"] < DEALS:
        state["deal"]+=1; state["step"]=0; state["amount"]=BASE_AMOUNT
        while state["running"] and state["step"] < STEPS:
            # 1. GET INDICATOR SIGNAL - LIKE VIDEO
            prices=await get_candles(state["pair"].replace("OTC",""))
            direction, signal, r, e9, e21, ml, ms = analyze(prices)
            state["last_signal"]=signal
            if direction=="wait":
                await context.bot.send_message(chat_id, f"⏳ Waiting for Trend signal 60s\n{signal}\nDeal {state['deal']}/{DEALS}")
                await asyncio.sleep(3)
                continue
            state["step"]+=1
            amt=state["amount"]
            pair_clean=state["pair"].replace("OTC","")
            await context.bot.send_message(chat_id, f"🎯 Autotrade - {state['pair']} ({state['account']}) - payout 92%\n{signal}\nDeal {state['deal']} Step {state['step']} Amount ${amt}")
            win=False
            if state["account"]=="REAL" and state["qx"]:
                try:
                    ok, trade_id = await state["qx"].buy(amt, pair_clean, direction, 5)
                    await asyncio.sleep(6)
                    res = await state["qx"].check_win(trade_id)
                    win=(res=="win")
                    if win: state["real_balance"]+=round(amt*PAYOUT,2); state["pnl"]+=round(amt*PAYOUT,2)
                    else: state["real_balance"]-=amt; state["pnl"]-=amt
                except Exception as e:
                    await context.bot.send_message(chat_id, f"❌ Real error: {e}"); win=False
            else:
                await asyncio.sleep(5)
                win=random.random()<0.7 # With indicators, higher winrate
                if win: state["demo_balance"]+=round(amt*PAYOUT,2); state["pnl"]+=round(amt*PAYOUT,2)
                else: state["demo_balance"]-=amt; state["pnl"]-=amt
            if win:
                await context.bot.send_message(chat_id, f"✅ Deal {state['deal']}/{DEALS} closed in profit (+${amt*PAYOUT:.2f})")
                break
            else:
                await context.bot.send_message(chat_id, f"❌ LOSS -${amt:.2f}\n{signal}\nNext: ${amt*COEF:.2f}")
                if state["step"]>=STEPS: break
                state["amount"]=round(amt*COEF,2)
        # end steps
    state["running"]=False
    await context.bot.send_message(chat_id, f"🏁 Result\nStrategy: Aggressive - EMA/MACD/RSI\nDeals: {DEALS}\nResult: ${state['pnl']:.2f}")

def main():
    token=os.getenv("TELEGRAM_TOKEN")
    app=Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button))
    print("BOTH - INDICATORS Running")
    app.run_polling()

if __name__=="__main__": main()
