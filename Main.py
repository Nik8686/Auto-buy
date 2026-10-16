# ============================================================
# PUMP.FUN ULTIMATE HUNTER + AUTO BUY / AUTO SELL
# (Top 10 Filter + Buyback Surge + Creator Rewards Badge)
# Google Colab - Multi-Public Free Nodes + Telegram Alerts
# Auto Trade: PumpPortal Local API (signing happens locally)
# ============================================================


import asyncio
import json
import html
from urllib.parse import urlparse
import aiohttp
import websockets
import base64
import hashlib
import struct
import time
import os

class userdata:
    """بديل لـ Colab userdata: كيقرا من متغيرات البيئة ديال Railway."""
    @staticmethod
    def get(name):
        v = os.environ.get(name)
        if v is None:
            raise KeyError(name)
        return v

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


# ============================================================
# CONFIG & MULTI-PUBLIC NODES
# ============================================================

PUBLIC_WSS_NODES = [
    "wss://api.mainnet-beta.solana.com",
    "wss://solana-rpc.publicnode.com"
]

# HTTP RPC (لإرسال المعاملات) - كيجرب وحدة وحدة
PUBLIC_HTTP_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com"
]

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPPORTAL_TRADE_LOCAL = "https://pumpportal.fun/api/trade-local"

# ============================================================
# COLAB SECRETS (TELEGRAM + WALLET)
# ============================================================

try:
    TELEGRAM_BOT_TOKEN = userdata.get("TELEGRAM_BOT_TOKEN")
except Exception:
    TELEGRAM_BOT_TOKEN = None

try:
    TELEGRAM_CHAT_ID = userdata.get("TELEGRAM_CHAT_ID")
except Exception:
    TELEGRAM_CHAT_ID = None

try:
    TRADING_WALLET_PRIVATE_KEY = userdata.get("TRADING_WALLET_PRIVATE_KEY")
except Exception:
    TRADING_WALLET_PRIVATE_KEY = None

try:
    HELIUS_API_KEY = userdata.get("HELIUS_API_KEY")
except Exception:
    HELIUS_API_KEY = None

print("Telegram Bot Token:", "OK ✅" if TELEGRAM_BOT_TOKEN else "MISSING ❌")
print("Telegram Chat ID:", "OK ✅" if TELEGRAM_CHAT_ID else "MISSING ❌")
print("Trading Wallet Key:", "OK ✅" if TRADING_WALLET_PRIVATE_KEY else "MISSING ❌")
print("Helius API Key:", "OK ✅ (Helius = primary)" if HELIUS_API_KEY else "MISSING ❌ (using public nodes)")

# Helius أول واحد، والعموميات كاحتياط
if HELIUS_API_KEY:
    HELIUS_API_KEY = HELIUS_API_KEY.strip()
    PUBLIC_WSS_NODES.insert(0, f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}")
    PUBLIC_HTTP_RPCS.insert(0, f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}")

def scrub(text):
    """كيخبي مفتاح Helius من أي طباعة أو رسالة خطأ."""
    text = str(text)
    if HELIUS_API_KEY:
        text = text.replace(HELIUS_API_KEY, "***")
    return text

def load_keypair(secret):
    """كيقبل المفتاح base58 (Phantom) أو JSON array."""
    if not secret:
        return None
    secret = secret.strip()
    try:
        if secret.startswith("["):
            return Keypair.from_bytes(bytes(json.loads(secret)))
        return Keypair.from_base58_string(secret)
    except Exception as e:
        print(f"❌ Invalid private key format: {e}")
        return None

TRADING_KEYPAIR = load_keypair(TRADING_WALLET_PRIVATE_KEY)
if TRADING_KEYPAIR:
    print(f"Trading Wallet: {TRADING_KEYPAIR.pubkey()}")

# ============================================================
# STRATEGY & RISK PARAMETERS (الفلاتر بلا تغيير)
# ============================================================

MIN_PEAK_MCAP_SOL = 60.0
MIN_DIP_DEPTH_PCT = 05.0
MAX_DIP_DEPTH_PCT = 80.0
MIN_POST_DIP_BUY_SOL = 10.0
MIN_CONSOLIDATION_WALLETS = 40
MAX_AGE_SECONDS = 6000

EARLY_WALLETS_LIMIT = 15
MAX_EARLY_BUY_SHARE_PCT = 25.0
MIN_BUY_DOMINANCE_PCT = 60.0

MAX_TOP_10_HOLDERS_SHARE_PCT = 6.0
BUYBACK_SURGE_THRESHOLD_SOL = 15.0

MIN_TRANSACTION_SOL = 0.008
TOTAL_SUPPLY = 1_000_000_000_000_000
LAMPORTS_PER_SOL = 1_000_000_000

SOL_PRICE_USD = 0.0
SOL_PRICE_REFRESH_SECONDS = 60
MAX_PROCESSED_SIGNATURES = 100_000

# ============================================================
# AUTO TRADE SETTINGS
# ============================================================

AUTO_TRADE_ENABLED = True       # False = تنبيهات فقط بلا شراء
DRY_RUN = False                 # True = كيحاكي الشراء/البيع بلا ما يرسل معاملات حقيقية
BUY_AMOUNT_SOL = 0.007          # مبلغ الصفقة
TAKE_PROFIT_PCT = 110.0          # +110%
STOP_LOSS_PCT = 50.0            # -50%
SLIPPAGE_PCT = 20               # slippage مسموح (%)
PRIORITY_FEE_SOL = 0.0005       # رسوم الأولوية
MAX_OPEN_POSITIONS = 3          # حماية: أقصى عدد صفقات مفتوحة فنفس الوقت
CONFIRM_TIMEOUT_SECONDS = 40

# إعدادات البيع (أسرع وأقوى من الشراء، لأن الخروج هو لي كيحمي الربح)
SELL_SLIPPAGE_PCT = 20          # slippage أكبر للبيع باش ما يفشلش ملي السعر كيتحرك بسرعة
SELL_PRIORITY_FEE_SOL = 0.001   # رسوم أولوية أعلى للبيع باش يوصل بسرعة
SELL_CONFIRM_SECONDS = 8        # إلا ما تأكدتش المعاملة فهاد المدة، كنبنيو وحدة جديدة
SELL_RETRIES = 6
MAX_SELL_ROUNDS = 8             # عدد جولات إعادة البيع قبل ما نوقف ونعلمك
SELL_ROUND_COOLDOWN_SECONDS = 8 # راحة بين الجولات

positions = {}   # mint -> {entry_mcap, status, selling, ...}
STATS = {"ws": None, "last_msg": time.time(), "msgs": 0, "events": 0, "alerts": 0}

# ============================================================
# BASE58 & DISCRIMINATOR
# ============================================================

TRADE_EVENT_DISCRIMINATOR = hashlib.sha256(b"event:TradeEvent").digest()[:8]
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def base58_encode(data):
    n = int.from_bytes(data, "big")
    result = ""
    while n > 0:
        n, r = divmod(n, 58)
        result = ALPHABET[r] + result
    pad = sum(1 for b in data if b == 0)
    return "1" * pad + result

def decode_trade_event(raw):
    try:
        if len(raw) < 8 or raw[:8] != TRADE_EVENT_DISCRIMINATOR:
            return None
        data = raw[8:]
        if len(data) < 121:
            return None

        offset = 0
        mint_bytes = data[offset:offset + 32]; offset += 32
        sol_amount = struct.unpack_from("<Q", data, offset)[0]; offset += 8
        token_amount = struct.unpack_from("<Q", data, offset)[0]; offset += 8
        is_buy = bool(data[offset]); offset += 1
        user_bytes = data[offset:offset + 32]; offset += 32
        timestamp = struct.unpack_from("<q", data, offset)[0]; offset += 8
        virtual_sol_reserves = struct.unpack_from("<Q", data, offset)[0]; offset += 8
        virtual_token_reserves = struct.unpack_from("<Q", data, offset)[0]; offset += 8
        real_sol_reserves = struct.unpack_from("<Q", data, offset)[0]; offset += 8
        real_token_reserves = struct.unpack_from("<Q", data, offset)[0]

        return {
            "mint": base58_encode(mint_bytes),
            "sol_amount": sol_amount,
            "token_amount": token_amount,
            "is_buy": is_buy,
            "user": base58_encode(user_bytes),
            "timestamp": timestamp,
            "virtual_sol_reserves": virtual_sol_reserves,
            "virtual_token_reserves": virtual_token_reserves,
            "real_sol_reserves": real_sol_reserves,
            "real_token_reserves": real_token_reserves,
        }
    except Exception:
        return None

# ============================================================
# SOL PRICE & TELEGRAM
# ============================================================

async def update_sol_price():
    global SOL_PRICE_USD
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    price = data.get("solana", {}).get("usd")
                    if price:
                        SOL_PRICE_USD = float(price)
                        return True
    except Exception:
        pass
    return False

async def sol_price_loop():
    await update_sol_price()
    while True:
        await asyncio.sleep(SOL_PRICE_REFRESH_SECONDS)
        await update_sol_price()

async def send_telegram_with_button(message, mint):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram Error: Token or Chat ID is missing!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🚀 Open Pump.fun", "url": f"https://pump.fun/coin/{mint}"},
                {"text": "📊 DexScreener", "url": f"https://dexscreener.com/solana/{mint}"}
            ]
        ]
    }

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": keyboard
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=15) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    print(f"✅ Telegram Alert Sent Successfully for {mint}!")
                    return True
                else:
                    print(f"❌ Telegram API Error ({resp.status}): {response_text}")
                    return False
    except Exception as e:
        print(f"❌ Telegram Connection Exception: {e}")
        return False

# ============================================================
# AUTO TRADE ENGINE
# ============================================================

async def build_signed_tx(action, mint, amount, denominated_in_sol, slippage=None, priority_fee=None, pool="auto"):
    """كيطلب المعاملة من PumpPortal وكيوقعها محليا بالمفتاح ديالك."""
    payload = {
        "publicKey": str(TRADING_KEYPAIR.pubkey()),
        "action": action,
        "mint": mint,
        "amount": amount,
        "denominatedInSol": "true" if denominated_in_sol else "false",
        "slippage": slippage if slippage is not None else SLIPPAGE_PCT,
        "priorityFee": priority_fee if priority_fee is not None else PRIORITY_FEE_SOL,
        "pool": pool,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(PUMPPORTAL_TRADE_LOCAL, data=payload, timeout=20) as resp:
            if resp.status != 200:
                raise RuntimeError(f"PumpPortal {resp.status}: {await resp.text()}")
            content = await resp.read()

    unsigned = VersionedTransaction.from_bytes(content)
    signed = VersionedTransaction(unsigned.message, [TRADING_KEYPAIR])
    return base64.b64encode(bytes(signed)).decode()

class SimFailed(Exception):
    """فشل simulation ديال المعاملة (preflight). السبب الحقيقي كيبقى فالرسالة."""

async def rpc_call(method, params):
    last_err = None
    errors = []
    for rpc in PUBLIC_HTTP_RPCS:
        try:
            async with aiohttp.ClientSession() as session:
                body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
                async with session.post(rpc, json=body, timeout=20) as resp:
                    data = await resp.json()
                    if "error" in data:
                        last_err = data["error"]
                        errors.append(f"{urlparse(rpc).netloc}: {scrub(json.dumps(last_err))[:200]}")
                        # المشكل فالمعاملة نفسها، ما فايدة نجرب RPC آخر (كيضيع الوقت ويخبي السبب)
                        if (method == "sendTransaction" and isinstance(last_err, dict)
                                and last_err.get("code") == -32002):
                            raise SimFailed(scrub(json.dumps(last_err))[:700])
                        continue
                    return data.get("result")
        except SimFailed:
            raise
        except Exception as e:
            last_err = e
            errors.append(f"{urlparse(rpc).netloc}: {scrub(e)[:200]}")
            continue
    raise RuntimeError("All RPCs failed -> " + " | ".join(errors))

async def get_token_balance(mint):
    """رصيد التوكن فالمحفظة (None إلا ما قدرناش نقراوه)."""
    try:
        res = await rpc_call("getTokenAccountsByOwner", [
            str(TRADING_KEYPAIR.pubkey()), {"mint": mint}, {"encoding": "jsonParsed"}
        ])
        total = 0.0
        for acc in (res or {}).get("value", []):
            amt = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
            total += float(amt.get("uiAmount") or 0)
        return total
    except Exception:
        return None

async def send_and_confirm(tx_b64, skip_preflight=True, timeout=None):
    sig = await rpc_call("sendTransaction", [tx_b64, {
        "encoding": "base64", "skipPreflight": skip_preflight, "maxRetries": 5,
        "preflightCommitment": "processed"
    }])
    deadline = time.time() + (timeout if timeout is not None else CONFIRM_TIMEOUT_SECONDS)
    while time.time() < deadline:
        await asyncio.sleep(1)
        try:
            res = await rpc_call("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
            st = (res or {}).get("value", [None])[0]
            if st:
                if st.get("err"):
                    return sig, False
                if st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return sig, True
        except Exception:
            pass
    return sig, False

def event_price(event):
    """سعر العملة بالـ SOL للتوكن الواحد، من احتياطيات الـ bonding curve."""
    try:
        vs = event["virtual_sol_reserves"] / LAMPORTS_PER_SOL
        vt = event["virtual_token_reserves"] / 1_000_000   # 6 decimals
        return vs / vt if vt > 0 else 0.0
    except Exception:
        return 0.0

async def execute_buy(mint, entry_mcap, entry_price=0.0):
    if not AUTO_TRADE_ENABLED:
        return
    if mint in positions:
        return
    open_count = sum(1 for p in positions.values() if p["status"] in ("buying", "open"))
    if open_count >= MAX_OPEN_POSITIONS:
        print(f"⚠️ Max open positions reached, skipping buy for {mint}")
        return
    if not DRY_RUN and not TRADING_KEYPAIR:
        print("❌ Auto-buy skipped: wallet private key missing/invalid")
        return

    positions[mint] = {
        "entry_mcap": entry_mcap, "entry_price": entry_price,
        "status": "buying", "selling": False,
        "opened_at": time.time(), "last_event": time.time()
    }

    try:
        if DRY_RUN:
            sig, ok = "DRY_RUN", True
        else:
            tx = await build_signed_tx("buy", mint, BUY_AMOUNT_SOL, True)
            sig, ok = await send_and_confirm(tx)

        if ok:
            positions[mint]["status"] = "open"
            tag = "🧪 [DRY RUN] " if DRY_RUN else ""
            msg = (
                f"🟢 <b>{tag}AUTO BUY EXECUTED</b>\n\n"
                f"🪙 <code>{mint}</code>\n"
                f"💰 Amount: <b>{BUY_AMOUNT_SOL} SOL</b>\n"
                f"📈 Entry MCAP: {entry_mcap:.2f} SOL\n"
                f"🎯 TP: +{TAKE_PROFIT_PCT:.0f}% ({entry_mcap * (1 + TAKE_PROFIT_PCT / 100):.2f} SOL)\n"
                f"🛑 SL: -{STOP_LOSS_PCT:.0f}% ({entry_mcap * (1 - STOP_LOSS_PCT / 100):.2f} SOL)\n"
                f"🔗 <a href=\"https://solscan.io/tx/{sig}\">Tx</a>"
            )
            await send_telegram_with_button(msg, mint)
        else:
            positions.pop(mint, None)
            await send_telegram_with_button(
                f"🔴 <b>AUTO BUY FAILED</b>\n<code>{mint}</code>\n🔗 <a href=\"https://solscan.io/tx/{sig}\">Tx</a>", mint)
    except Exception as e:
        positions.pop(mint, None)
        print(f"❌ Buy error: {e}")
        await send_telegram_with_button(f"🔴 <b>AUTO BUY ERROR</b>\n<code>{mint}</code>\n{str(e)[:200]}", mint)

async def execute_sell(mint, reason, current_mcap):
    pos = positions.get(mint)
    if not pos:
        return

    sig, ok = None, False
    try:
        if DRY_RUN:
            sig, ok = "DRY_RUN", True
        else:
            for attempt in range(1, SELL_RETRIES + 1):
                # بعد الـ migration العملة كتتباع فـ PumpSwap ماشي فالـ bonding curve.
                # كنبداو بالـ pool المناسب وكنبدلو بين المحاولات إلا فشل.
                preferred = "pump-amm" if pos.get("migrated") else "auto"
                if pos.get("last_pool") == preferred:   # المحاولة اللي فاتت فشلات بيه: نبدلو
                    pool = "auto" if preferred == "pump-amm" else "pump-amm"
                else:
                    pool = preferred
                pos["last_pool"] = pool
                try:
                    # كل محاولة = معاملة جديدة (blockhash جديد) بدل الانتظار الطويل
                    tx = await build_signed_tx("sell", mint, "100%", False,
                                               slippage=SELL_SLIPPAGE_PCT,
                                               priority_fee=SELL_PRIORITY_FEE_SOL,
                                               pool=pool)
                    # preflight شغال: إلا كانت المعاملة غادي تفشل ما كتتبعثش وما كتخلصش رسوم
                    sig, ok = await send_and_confirm(tx, skip_preflight=False,
                                                     timeout=SELL_CONFIRM_SECONDS)
                    if ok:
                        break
                    pos["last_err"] = f"المعاملة ما تأكدتش أو فشلات على الشبكة: {sig}"
                except Exception as e:
                    pos["last_err"] = f"[pool={pool}] {scrub(e)}"[:700]
                    if any(k in str(e).lower() for k in ("bondingcurvecomplete", "6005")):
                        pos["migrated"] = True   # الـ bonding curve سالات: العملة فـ PumpSwap
                    print(f"⚠️ Sell attempt {attempt} [{pool}] failed: {scrub(e)}")
                # بعد كل فشل: واش الرصيد وصل 0؟ (المعاملة وصلات متأخرة أو بعتيها يدويا)
                bal = await get_token_balance(mint)
                if bal is not None and bal == 0:
                    ok = True
                    break
                await asyncio.sleep(0.3)
    except Exception as e:
        print(f"❌ Sell error: {scrub(e)}")

    sig = sig or "unknown"
    entry = pos["entry_mcap"]
    pnl_pct = ((current_mcap - entry) / entry * 100.0) if entry > 0 else 0.0
    last_mcap = pos.get("last_mcap", current_mcap)
    last_pct = ((last_mcap - entry) / entry * 100.0) if entry > 0 else 0.0
    delay_s = time.time() - pos.get("trigger_time", time.time())

    if ok:
        positions.pop(mint, None)
        tag = "🧪 [DRY RUN] " if DRY_RUN else ""
        icon = "✅" if reason == "TAKE PROFIT" else "🛑"
        msg = (
            f"{icon} <b>{tag}AUTO SELL - {reason}</b>\n\n"
            f"🪙 <code>{mint}</code>\n"
            f"📈 Entry MCAP: {entry:.2f} SOL\n"
            f"🎯 Trigger MCAP: {current_mcap:.2f} SOL (<b>{pnl_pct:+.1f}%</b> وقت الإشارة)\n"
            f"📉 Last seen MCAP: {last_mcap:.2f} SOL (<b>{last_pct:+.1f}%</b> فاخر سعر شفناه)\n"
            f"⏱ Sell took: {delay_s:.0f}s\n"
            f"ℹ️ الربح الحقيقي كاين فالمعاملة (Tx)، هادو غير تقدير\n"
            f"🔗 <a href=\"https://solscan.io/tx/{sig}\">Tx</a>"
        )
        await send_telegram_with_button(msg, mint)
    else:
        # فشل البيع: كنعاود تلقائيا. "selling" كيبقى True باش TP/SL ما يتفعلوش جوج مرات،
        # والبيع كيبقى مطلوب حتى إلا رجع السعر تحت الـ TP.
        pos["fails"] = pos.get("fails", 0) + 1
        err = html.escape(str(pos.get("last_err", "unknown")))[:600]
        print(f"⚠️ Sell round {pos['fails']}/{MAX_SELL_ROUNDS} failed for {mint}: {err}")
        if pos["fails"] >= MAX_SELL_ROUNDS:
            positions.pop(mint, None)
            await send_telegram_with_button(
                f"⛔ <b>AUTO SELL GAVE UP ({reason})</b>\n<code>{mint}</code>\n"
                f"فشلات {MAX_SELL_ROUNDS} جولات. بيع يدويا دابا.\n"
                f"<b>آخر خطأ:</b>\n<code>{err}</code>", mint)
            return
        if pos["fails"] == 1:   # تنبيه واحد فقط باش ما تتعباش بالرسائل
            await send_telegram_with_button(
                f"⚠️ <b>AUTO SELL FAILED ({reason})</b>\n<code>{mint}</code>\n"
                f"كنعاود المحاولة تلقائيا (حتى {MAX_SELL_ROUNDS} جولات).\n"
                f"<b>الخطأ:</b>\n<code>{err}</code>", mint)
        await asyncio.sleep(SELL_ROUND_COOLDOWN_SECONDS)
        if mint in positions:
            await execute_sell(mint, reason, current_mcap)

def check_position(mint, current_mcap):
    pos = positions.get(mint)
    if (not pos or pos["status"] != "open" or pos["selling"] or current_mcap <= 0
            or time.time() < pos.get("next_try", 0)):
        return
    entry = pos["entry_mcap"]
    if entry <= 0:
        return
    change_pct = (current_mcap - entry) / entry * 100.0
    reason = None
    if change_pct >= TAKE_PROFIT_PCT:
        reason = "TAKE PROFIT"
    elif change_pct <= -STOP_LOSS_PCT:
        reason = "STOP LOSS"
    if reason:
        pos["selling"] = True
        pos["trigger_time"] = time.time()
        asyncio.create_task(execute_sell(mint, reason, current_mcap))

async def fetch_dex_price(mint):
    """سعر العملة بالـ SOL من DexScreener (كيخدم حتى بعد الـ migration لـ PumpSwap)."""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        pairs = [p for p in (data.get("pairs") or [])
                 if (p.get("quoteToken", {}).get("symbol") or "").upper() in ("SOL", "WSOL")
                 and p.get("priceNative")]
        if not pairs:
            return None
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        return float(best["priceNative"])
    except Exception:
        return None

async def position_watchdog():
    """شبكة أمان: إلا ما جاتش تريدات من الـ WebSocket لعملة مشتراة (مثلا migration
    لـ PumpSwap أو انقطاع)، كيجيب السعر من DexScreener كل 5 ثواني ويطبق TP/SL."""
    while True:
        await asyncio.sleep(2)
        for mint, pos in list(positions.items()):
            if pos["status"] != "open" or pos["selling"]:
                continue
            # بعد الـ migration ما كاين حتى event من الـ WebSocket، فنسولو DexScreener مباشرة
            if not pos.get("migrated") and time.time() - pos["last_event"] < 4:
                continue
            if pos.get("entry_price", 0) <= 0:
                continue
            price = await fetch_dex_price(mint)
            if not price:
                continue
            ratio = price / pos["entry_price"]
            if ratio < 0.001 or ratio > 50:
                continue  # قيمة غير منطقية، نتجاهلها
            pos["last_mcap"] = pos["entry_mcap"] * ratio
            check_position(mint, pos["last_mcap"])

async def heartbeat_loop():
    """كيطبع حالة البوت كل دقيقتين، وكيعاود الاتصال إلا الـ WebSocket سكت (ما جاو حتى رسائل)."""
    while True:
        await asyncio.sleep(120)
        idle = time.time() - STATS["last_msg"]
        peak_ok = sum(1 for t in tokens.values() if t["peak_mcap_sol"] >= MIN_PEAK_MCAP_SOL)
        dips = sum(1 for t in tokens.values() if t["in_dip"])
        print(f"💓 msgs={STATS['msgs']} events={STATS['events']} idle={idle:.0f}s | "
              f"tokens={len(tokens)} peak>={MIN_PEAK_MCAP_SOL:.0f}SOL={peak_ok} in_dip={dips} "
              f"alerts={STATS['alerts']} positions={len(positions)}")
        if idle > 45 and STATS["ws"] is not None:
            print("⚠️ WebSocket silent for >45s, forcing reconnect...")
            try:
                await STATS["ws"].close()
            except Exception:
                pass

# ============================================================
# TOKEN STATE & STRATEGY LOGIC
# ============================================================

tokens = {}
processed_signatures = set()

def create_token(event, signature):
    return {
        "mint": event["mint"],
        "first_timestamp": event["timestamp"],
        "trades": 0,
        "all_seen_wallets": [],
        "all_seen_wallet_set": set(),
        "wallet_token_balances": {},
        "peak_mcap_sol": 0.0,
        "in_dip": False,
        "dip_start_time": None,
        "post_dip_buy_sol": 0.0,
        "post_dip_sell_sol": 0.0,
        "post_dip_wallets": set(),
        "dip_wallet_buys": {},
        "last_activity": time.time(),
        "alert_sent": False
    }

def calculate_mcap(event):
    try:
        vs = event["virtual_sol_reserves"]
        vt = event["virtual_token_reserves"]
        if vt <= 0:
            return 0.0
        sol = vs / LAMPORTS_PER_SOL
        return sol / (vt / TOTAL_SUPPLY)
    except Exception:
        return 0.0

async def process_trade(event, signature):
    mint = event["mint"]
    sol_amount = event["sol_amount"] / LAMPORTS_PER_SOL
    token_amt = event["token_amount"]
    wallet = event["user"]
    is_buy = event["is_buy"]

    # مراقبة TP/SL على كل تريد للعملة المشتراة (قبل فلتر الحد الأدنى)
    STATS["events"] += 1
    if mint in positions:
        positions[mint]["last_event"] = time.time()
        _m = calculate_mcap(event)
        if _m > 0:
            positions[mint]["last_mcap"] = _m
        if event["real_token_reserves"] == 0:
            positions[mint]["migrated"] = True   # الـ bonding curve كملات، العملة غادي لـ PumpSwap
        check_position(mint, _m)

    if sol_amount < MIN_TRANSACTION_SOL:
        return

    if mint not in tokens:
        tokens[mint] = create_token(event, signature)

    token = tokens[mint]
    token["last_activity"] = time.time()
    token["trades"] += 1

    if is_buy:
        token["wallet_token_balances"][wallet] = token["wallet_token_balances"].get(wallet, 0) + token_amt
    else:
        token["wallet_token_balances"][wallet] = max(0, token["wallet_token_balances"].get(wallet, 0) - token_amt)

    if wallet not in token["all_seen_wallet_set"] and len(token["all_seen_wallet_set"]) < 100:
        token["all_seen_wallet_set"].add(wallet)
        token["all_seen_wallets"].append(wallet)

    current_mcap = calculate_mcap(event)

    if current_mcap > token["peak_mcap_sol"]:
        token["peak_mcap_sol"] = current_mcap

    if token["peak_mcap_sol"] >= MIN_PEAK_MCAP_SOL:
        dip_pct = ((token["peak_mcap_sol"] - current_mcap) / token["peak_mcap_sol"]) * 100.0

        if MIN_DIP_DEPTH_PCT <= dip_pct <= MAX_DIP_DEPTH_PCT:
            if not token["in_dip"]:
                token["in_dip"] = True
                token["dip_start_time"] = time.time()

        if token["in_dip"]:
            early_holders = set(token["all_seen_wallets"][:EARLY_WALLETS_LIMIT])

            if is_buy:
                if wallet in early_holders:
                    token["dip_wallet_buys"][wallet] = token["dip_wallet_buys"].get(wallet, 0.0) + sol_amount
                else:
                    token["post_dip_buy_sol"] += sol_amount
                    token["post_dip_wallets"].add(wallet)
                    token["dip_wallet_buys"][wallet] = token["dip_wallet_buys"].get(wallet, 0.0) + sol_amount
            else:
                token["post_dip_sell_sol"] += sol_amount

    total_dip_buy = token["post_dip_buy_sol"]
    for w in early_holders if 'early_holders' in locals() else []:
        w_buy = token["dip_wallet_buys"].get(w, 0.0)
        if total_dip_buy > 0 and (w_buy / (total_dip_buy + 0.0001)) <= (MAX_EARLY_BUY_SHARE_PCT / 100.0):
            total_dip_buy += w_buy

    total_dip_volume = total_dip_buy + token["post_dip_sell_sol"]
    buy_dominance_pct = (total_dip_buy / total_dip_volume * 100.0) if total_dip_volume > 0 else 0.0
    age = max(0, int(time.time() - token["first_timestamp"]))

    sorted_balances = sorted(token["wallet_token_balances"].values(), reverse=True)
    top_10_sum = sum(sorted_balances[:10])
    top_10_share_pct = (top_10_sum / TOTAL_SUPPLY) * 100.0 if TOTAL_SUPPLY > 0 else 0.0

    is_buyback_surge = (total_dip_buy >= BUYBACK_SURGE_THRESHOLD_SOL and buy_dominance_pct >= 75.0)

    if (token["in_dip"] and
        total_dip_buy >= MIN_POST_DIP_BUY_SOL and
        len(token["post_dip_wallets"]) >= MIN_CONSOLIDATION_WALLETS and
        buy_dominance_pct >= MIN_BUY_DOMINANCE_PCT and
        top_10_share_pct <= MAX_TOP_10_HOLDERS_SHARE_PCT and
        age <= MAX_AGE_SECONDS):

        if not token["alert_sent"]:
            token["alert_sent"] = True
            STATS["alerts"] += 1
            peak_usd = token["peak_mcap_sol"] * SOL_PRICE_USD if SOL_PRICE_USD > 0 else 0.0
            current_mcap_usd = current_mcap * SOL_PRICE_USD if SOL_PRICE_USD > 0 else 0.0

            surge_badge = "🔥 [BUYBACK SURGE DETECTED!]" if is_buyback_surge else "⚡ [CLEAN ACCUMULATION]"

            message = (
                f"🚀 <b>{surge_badge}</b>\n\n"
                f"🪙 <b>Mint:</b>\n<code>{mint}</code>\n\n"
                f"📈 <b>Peak MCAP:</b> {token['peak_mcap_sol']:.2f} SOL (${peak_usd:,.0f})\n"
                f"📉 <b>Current MCAP:</b> {current_mcap:.2f} SOL (${current_mcap_usd:,.0f})\n"
                f"👥 <b>Top 10 Holders Share:</b> <b>{top_10_share_pct:.1f}%</b> (Safe under {MAX_TOP_10_HOLDERS_SHARE_PCT:.0f}%)\n"
                f"🎁 <b>Creator Rewards:</b> <b>Holders 100%</b> (Eligible)\n"
                f"⏱ <b>Age:</b> {age}s\n\n"
                f"🔥 <b>DOMINANCE METRICS:</b>\n"
                f" ├─ Buy Dominance: <b>{buy_dominance_pct:.1f}%</b>\n"
                f" ├─ Clean Buy Volume: <b>{total_dip_buy:.2f} SOL</b>\n"
                f" └─ New Unique Wallets: <b>{len(token['post_dip_wallets'])} wallets</b>"
            )

            print(f"\n🎯 [SIGNAL FOUND] Mint: {mint} | Top 10 Share: {top_10_share_pct:.1f}% | Buyback Surge: {is_buyback_surge}\n")
            asyncio.create_task(send_telegram_with_button(message, mint))

            # ===== AUTO BUY =====
            if AUTO_TRADE_ENABLED:
                asyncio.create_task(execute_buy(mint, current_mcap, event_price(event)))

# ============================================================
# CLEANUP & WEBSOCKET LISTEN
# ============================================================

async def cleanup_loop():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        remove = [m for m, t in tokens.items()
                  if now - t["last_activity"] > 3600 and m not in positions]
        for mint in remove:
            tokens.pop(mint, None)

async def listen_solana():
    asyncio.create_task(sol_price_loop())
    node_index = 0
    reconnect_delay = 3

    while True:
        current_wss = PUBLIC_WSS_NODES[node_index]
        try:
            print(f"\n⏳ Connecting to: {scrub(current_wss)}")
            async with websockets.connect(current_wss, ping_interval=20, ping_timeout=30) as ws:
                subscription = {
                    "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                    "params": [{"mentions": [PUMP_FUN_PROGRAM]}, {"commitment": "confirmed"}]
                }
                await ws.send(json.dumps(subscription))
                await ws.recv()
                STATS["ws"] = ws
                STATS["last_msg"] = time.time()
                print(f"✅ Connected! Hunter + Auto Trade Active "
                      f"(enabled={AUTO_TRADE_ENABLED}, dry_run={DRY_RUN})...")

                async for raw_message in ws:
                    message = json.loads(raw_message)
                    if message.get("method") != "logsNotification":
                        continue
                    STATS["last_msg"] = time.time()
                    STATS["msgs"] += 1

                    value = message.get("params", {}).get("result", {}).get("value", {})
                    signature = value.get("signature")

                    if not signature or signature in processed_signatures:
                        continue

                    processed_signatures.add(signature)
                    if len(processed_signatures) > MAX_PROCESSED_SIGNATURES:
                        processed_signatures.pop()

                    for log in value.get("logs", []):
                        if log.startswith("Program data:"):
                            try:
                                encoded = log.split("Program data:", 1)[1].strip()
                                raw = base64.b64decode(encoded)
                                event = decode_trade_event(raw)
                                if event:
                                    await process_trade(event, signature)
                            except Exception:
                                continue

        except Exception as e:
            print(f"❌ WSS Error: {scrub(e)}")
            node_index = (node_index + 1) % len(PUBLIC_WSS_NODES)
            await asyncio.sleep(reconnect_delay)

# ============================================================
# START
# ============================================================

async def main():
    print("=" * 60)
    print("PUMP.FUN: HUNTER + AUTO BUY / AUTO SELL")
    print("=" * 60)
    await asyncio.gather(listen_solana(), cleanup_loop(), position_watchdog(), heartbeat_loop())

if __name__ == "__main__":
    asyncio.run(main())
