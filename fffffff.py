#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════
#   ⚡ ARYA BOT ═══════════════════════════════════════════════════════

import asyncio
import os
import random
import re
import time
import logging
import traceback
import io
import json
import gzip
import subprocess
import tempfile
import urllib.parse
import urllib.request
import sys
import base64
from datetime import datetime
from typing import Set, Dict, List, Any, Optional

# ═══════════════════════════════════════════════════════
# AUTO INSTALL
# ═══════════════════════════════════════════════════════

REQUIRED_PIP = [
    "python-telegram-bot>=20.0", "yt-dlp", "pillow",
    "rlottie-python", "motor", "aiohttp",
]


def _run(cmd, capture=True):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=600)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, str(e)


def install_pip():
    print("\n📦 Installing packages...")
    for pkg in REQUIRED_PIP:
        pkg_name = pkg.split(">=")[0]
        imp_map = {
            "python-telegram-bot": "telegram", "pillow": "PIL",
            "yt-dlp": "yt_dlp", "rlottie-python": "rlottie_python",
        }
        imp = imp_map.get(pkg_name, pkg_name.replace("-", "_"))
        try:
            __import__(imp)
            print(f"   ✓ {pkg_name}")
            continue
        except ImportError:
            pass
        print(f"   ⏳ {pkg}...")
        rc, _ = _run(f"{sys.executable} -m pip install --upgrade {pkg}")
        if rc != 0:
            rc, _ = _run(f"{sys.executable} -m pip install --user {pkg}")
        print(f"   {'✅' if rc == 0 else '❌'} {pkg_name}")


def install_ffmpeg():
    print("\n🎬 ffmpeg...")
    try:
        if subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5).returncode == 0:
            print("   ✓ ffmpeg"); return
    except Exception: pass
    if os.path.exists("/usr/bin/apt"):
        _run("sudo -n apt-get install -y ffmpeg")
    elif os.path.exists("/sbin/apk"):
        _run("apk add --no-cache ffmpeg")
    try:
        if subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5).returncode == 0:
            print("   ✅ ffmpeg")
        else: print("   ⚠️ missing")
    except Exception: print("   ⚠️ missing")


if not os.path.exists("/.dockerenv"):
    print("\n⚡ ARYA BOT — SETUP")
    install_pip()
    install_ffmpeg()
    print("✅ Done\n")
else:
    print("\n🐳 Docker — skip install\n")

# ═══════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════

try:
    from telegram import (
        Update, ChatMember, ChatMemberUpdated,
        InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions,
    )
    from telegram.ext import (
        Application, MessageHandler, ContextTypes, filters,
        ChatMemberHandler, CallbackQueryHandler,
    )
except ImportError:
    print("❌ pip install python-telegram-bot"); sys.exit(1)

try:
    import yt_dlp
except ImportError:
    print("❌ pip install yt-dlp"); sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
except ImportError:
    print("❌ pip install pillow"); sys.exit(1)

try:
    from rlottie_python import LottieAnimation
    HAS_RLOTTIE = True
except Exception:
    HAS_RLOTTIE = False; LottieAnimation = None

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    HAS_MONGO = True
except ImportError:
    HAS_MONGO = False; AsyncIOMotorClient = None

try:
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False; web = None

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════

TOKENS = [os.getenv("BOT_TOKEN", "")]
DOWNLOAD_DIR = "downloads"
FONT_DIR = "fonts"
COMMAND_PREFIX = "."
OWNER_ID = int(os.getenv("OWNER_ID", "8783901855"))

FORCE_JOIN_ENABLED = os.getenv("FORCE_JOIN_ENABLED", "True").lower() == "true"
FORCE_JOIN_LINK = os.getenv("FORCE_JOIN_LINK", "https://t.me/+e56LxHnciK5lOWI1")
FORCE_JOIN_CHAT_ID = int(os.getenv("FORCE_JOIN_CHAT_ID", "-1004343483155"))

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "arya_secret_" + str(int(time.time())))
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
PORT = int(os.getenv("PORT", "10000"))
MONGO_URI = os.getenv("MONGO_URI", "")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(SCRIPT_DIR, "hosted_files")
LOG_DIR = os.path.join(SCRIPT_DIR, "host_logs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

apps: List[Any] = []
bots: List[Any] = []

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════
# STORAGE
# ═══════════════════════════════════════════════════════

VERIFIED_USERS: Set[int] = set()
BLOCKED_USERS: Set[int] = set()
KNOWN_CHATS: Set[int] = set()
RR_USERS: Dict[str, Dict] = {}
LOCKED_CHATS: Set[int] = set()

_mongo_client = None
_mongo_db = None
_use_mongo = False


async def init_mongo():
    global _mongo_client, _mongo_db, _use_mongo
    global VERIFIED_USERS, BLOCKED_USERS, KNOWN_CHATS, RR_USERS, LOCKED_CHATS
    if not HAS_MONGO or not MONGO_URI:
        print("⚠️ MongoDB — in-memory mode"); _use_mongo = False; return
    try:
        _mongo_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _mongo_db = _mongo_client["arya_bot"]
        await _mongo_client.admin.command("ping")
        _use_mongo = True
        print("✅ MongoDB connected")
        for name, target in [("verified", VERIFIED_USERS), ("blocked", BLOCKED_USERS),
                              ("chats", KNOWN_CHATS), ("locked", LOCKED_CHATS)]:
            d = await _mongo_db[name].find_one({"_id": name})
            if d:
                key = name if name != "chats" else "chats"
                target.clear(); target.update(d.get(key, d.get("users", [])))
        r = await _mongo_db.rr.find_one({"_id": "rr"})
        if r: RR_USERS.update({str(k): v for k, v in r.get("users", {}).items()})
        print(f"📋 Loaded: {len(VERIFIED_USERS)}v {len(BLOCKED_USERS)}b {len(RR_USERS)}rr {len(LOCKED_CHATS)}l {len(KNOWN_CHATS)}c")
    except Exception as e:
        print(f"⚠️ MongoDB fail: {e}"); _use_mongo = False


async def _save(name: str, doc: dict):
    if not _use_mongo: return
    try: await _mongo_db[name].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    except Exception as e: logger.error(f"save {name}: {e}")


async def save_verified(): await _save("verified", {"_id": "verified", "users": list(VERIFIED_USERS)})
async def save_blocked(): await _save("blocked", {"_id": "blocked", "users": list(BLOCKED_USERS)})
async def save_chats(): await _save("chats", {"_id": "chats", "chats": list(KNOWN_CHATS)})
async def save_rr(): await _save("rr", {"_id": "rr", "users": dict(RR_USERS)})
async def save_locked(): await _save("locked", {"_id": "locked", "chats": list(LOCKED_CHATS)})


# ═══════════════════════════════════════════════════════
# HOST STORAGE
# ═══════════════════════════════════════════════════════

TOKENS_FILE = "Arya_tokens.json"
SUDO_FILE = "Arya_sudo.json"
hosted_scripts: Dict[int, Dict[str, Any]] = {}
hosted_menus: Dict[int, Dict[str, Dict[str, Any]]] = {}
_seen: Set[tuple] = set()
all_bot_instances: List[Any] = []


def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default


SUDO_USERS: Set[int] = set(int(x) for x in _load_json(SUDO_FILE, []))
SUDO_USERS.add(OWNER_ID)


def is_admin(uid: int) -> bool: return uid == OWNER_ID or uid in SUDO_USERS
def is_owner(user_id) -> bool: return OWNER_ID and user_id == OWNER_ID


async def is_group_admin(chat_id, user_id, context):
    if is_owner(user_id): return True
    try:
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception: return False

# ═══════════════════════════════════════════════════════
# FONTS
# ═══════════════════════════════════════════════════════

FONTS = {
    "Anton": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "BebasNeue": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    "Bungee": "https://github.com/google/fonts/raw/main/ofl/bungee/Bungee-Regular.ttf",
    "BlackOpsOne": "https://github.com/google/fonts/raw/main/ofl/blackopsone/BlackOpsOne-Regular.ttf",
    "Bangers": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
    "RussoOne": "https://github.com/google/fonts/raw/main/ofl/russoone/RussoOne-Regular.ttf",
    "Staatliches": "https://github.com/google/fonts/raw/main/ofl/staatliches/Staatliches-Regular.ttf",
    "Teko": "https://github.com/google/fonts/raw/main/ofl/teko/Teko%5Bwght%5D.ttf",
    "GreatVibes": "https://github.com/google/fonts/raw/main/ofl/greatvibes/GreatVibes-Regular.ttf",
    "DancingScript": "https://github.com/google/fonts/raw/main/ofl/dancingscript/DancingScript%5Bwght%5D.ttf",
    "Pacifico": "https://github.com/google/fonts/raw/main/ofl/pacifico/Pacifico-Regular.ttf",
}

_font_paths: List[str] = []
_fonts_loaded = False


def _dl_font(name, url):
    path = os.path.join(FONT_DIR, f"{name}.ttf")
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        try: ImageFont.truetype(path, 40); return path
        except Exception:
            try: os.remove(path)
            except Exception: pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r: data = r.read()
        if len(data) < 10000: return None
        with open(path, "wb") as f: f.write(data)
        ImageFont.truetype(path, 40); return path
    except Exception: return None


def load_fonts():
    global _font_paths, _fonts_loaded
    if _fonts_loaded: return _font_paths
    os.makedirs(FONT_DIR, exist_ok=True)
    paths = []
    for n, u in FONTS.items():
        p = _dl_font(n, u)
        if p: paths.append(p)
    for sf in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
               "DejaVuSans-Bold.ttf", "arialbd.ttf"]:
        try: ImageFont.truetype(sf, 40); paths.append(sf)
        except Exception: pass
    _font_paths = paths or [None]; _fonts_loaded = True
    return _font_paths


def _get_font(size):
    if not _font_paths: return ImageFont.load_default()
    fp = random.choice(_font_paths)
    if fp is None: return ImageFont.load_default()
    try: return ImageFont.truetype(fp, size)
    except Exception: return ImageFont.load_default()


def _find_font_path():
    for p in _font_paths:
        if p and os.path.exists(p): return p
    return None


def _get_stk_font(size):
    for name in ["GreatVibes", "DancingScript", "Pacifico"]:
        p = os.path.join(FONT_DIR, f"{name}.ttf")
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except Exception: continue
    return _get_font(size)

# ═══════════════════════════════════════════════════════
# YT-DLP + COBALT
# ═══════════════════════════════════════════════════════

_COOKIES_B64 = os.getenv("YTDL_COOKIES_B64", "")
_COOKIES_PATH = None


def _setup_cookies():
    global _COOKIES_PATH
    if _COOKIES_PATH and os.path.exists(_COOKIES_PATH): return _COOKIES_PATH
    if not _COOKIES_B64: return None
    try:
        data = base64.b64decode(_COOKIES_B64).decode("utf-8", errors="ignore")
        if "# Netscape" not in data and "# HTTP Cookie" not in data:
            data = "# Netscape HTTP Cookie File\n" + data
        _COOKIES_PATH = "/tmp/ytdl_cookies.txt"
        with open(_COOKIES_PATH, "w", encoding="utf-8") as f: f.write(data)
        return _COOKIES_PATH
    except Exception: return None


def get_ydl_opts(extra=None):
    opts = {
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web_creator", "tv_embedded", "mweb"]}},
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "quiet": True, "no_warnings": True, "noplaylist": True, "no_color": True,
        "socket_timeout": 30, "retries": 10, "fragment_retries": 10,
        "extractor_retries": 5, "default_search": "ytsearch1",
        "nocheckcertificate": True, "geo_bypass": True, "age_limit": 99,
        "postprocessor_args": {"ffmpeg": ["-strict", "-2"]},
    }
    c = _setup_cookies()
    if c: opts["cookiefile"] = c
    p = os.getenv("YTDL_PROXY", "").strip()
    if p: opts["proxy"] = p
    if extra: opts.update(extra)
    return opts


COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://co.wuk.sh",
    "https://cobalt-api.kwiatekmiki.com",
    "https://cobalt-api.ayo.tf",
]


async def cobalt_download(query: str, is_audio: bool = False) -> Optional[dict]:
    try:
        import aiohttp
    except ImportError: return None
    url = query if query.startswith("http") else f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    payload = {"url": url, "videoQuality": "720", "audioFormat": "mp3",
               "audioBitrate": "128", "downloadMode": "audio" if is_audio else "auto",
               "filenameStyle": "basic"}
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "User-Agent": "Mozilla/5.0"}
    for inst in COBALT_INSTANCES:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(inst, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=45)) as r:
                    if r.status != 200: continue
                    try: data = await r.json()
                    except Exception: continue
                    st = data.get("status")
                    logger.info(f"Cobalt {inst}: {st}")
                    if st in ("tunnel", "redirect"):
                        u = data.get("url")
                        if u: return {"url": u, "title": data.get("filename") or "Video"}
                    elif st == "picker":
                        p = (data.get("picker") or [])
                        if p: return {"url": p[0].get("url"), "title": p[0].get("filename") or "Video"}
        except Exception as e:
            logger.warning(f"Cobalt {inst}: {str(e)[:120]}")
            continue
    return None


async def dl_from_url(url: str, out: str) -> bool:
    try:
        import aiohttp
    except ImportError:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                while True:
                    ch = r.read(65536)
                    if not ch: break
                    f.write(ch)
            return True
        except Exception: return False
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=180),
                             headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status != 200: return False
                with open(out, "wb") as f:
                    async for ch in r.content.iter_chunked(65536): f.write(ch)
        return True
    except Exception: return False

# ═══════════════════════════════════════════════════════
# DEDUP + GUARDS
# ═══════════════════════════════════════════════════════

_processed: Dict = {}
_dedup_lock = asyncio.Lock()


def dedup(func):
    async def w(update: Update, ctx):
        if not update.message: return await func(update, ctx)
        k = (update.message.chat_id, update.message.message_id)
        now = time.time()
        async with _dedup_lock:
            if len(_processed) > 3000:
                for kk in list(_processed.keys()):
                    if _processed[kk] < now - 120: del _processed[kk]
            if k in _processed: return
            _processed[k] = now
        return await func(update, ctx)
    w.__name__ = func.__name__
    return w


def _guard(h):
    async def w(update: Update, ctx):
        user = update.effective_user
        msg = update.message or update.edited_message
        if not user or not is_admin(user.id):
            if msg:
                try: await msg.reply_text("⛔ ACCESS DENIED")
                except Exception: pass
            return
        k = (msg.chat_id, msg.message_id) if msg else None
        if k:
            if k in _seen: return
            _seen.add(k)
            if len(_seen) > 8000:
                for kk in list(_seen)[:4000]: _seen.discard(kk)
        await h(update, ctx)
    w.__name__ = h.__name__
    return w


def _get_args(ctx): return ctx.args or []
def _txt_arg(ctx): return " ".join(_get_args(ctx)).strip()
def _bots(): return [b for b in all_bot_instances if b]


async def safe_reply(m, t, **kw):
    try: return await m.reply_text(t, **kw)
    except Exception as e:
        logger.error(f"reply: {e}"); return None


async def safe_edit(m, t, **kw):
    try: return await m.edit_text(t, **kw)
    except Exception as e:
        logger.error(f"edit: {e}"); return None


async def safe_del(m):
    try: await m.delete()
    except Exception: pass


def _tname(update):
    try:
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            u = update.message.reply_to_message.from_user
            return f"@{u.username}" if u.username else u.first_name
    except Exception: pass
    return None

# ═══════════════════════════════════════════════════════
# FORCE JOIN
# ═══════════════════════════════════════════════════════

async def is_joined(update, ctx):
    if not FORCE_JOIN_ENABLED or not FORCE_JOIN_CHAT_ID: return True
    uid = update.effective_user.id
    if is_owner(uid): return True
    try:
        m = await ctx.bot.get_chat_member(FORCE_JOIN_CHAT_ID, uid)
        return m.status in ("member", "administrator", "creator")
    except Exception: return False


async def send_join_msg(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Join Group", url=FORCE_JOIN_LINK)],
        [InlineKeyboardButton("✅ I'm Joined", callback_data="check_join")],
    ])
    await safe_reply(update.message,
        "⚠️ **GROUP JOIN KARO** ⚠️\n\n"
        "Bot use karne ke liye pehle group join karna zaroori hai.\n\n"
        "1️⃣ **Join Group** dabao\n2️⃣ Group join karo\n3️⃣ **I'm Joined** dabao",
        reply_markup=kb, parse_mode="Markdown")


async def check_join_cb(update, ctx):
    q = update.callback_query
    try: await q.answer()
    except Exception: pass
    try:
        m = await ctx.bot.get_chat_member(FORCE_JOIN_CHAT_ID, q.from_user.id)
        if m.status in ("member", "administrator", "creator"):
            VERIFIED_USERS.add(q.from_user.id); await save_verified()
            await q.edit_message_text("✅ Verified! `.help` bhejo", parse_mode="Markdown")
        else:
            await q.edit_message_text("❌ Join nahi kiya. Pehle join karo.")
    except Exception as e:
        logger.error(f"join cb: {e}")

# ═══════════════════════════════════════════════════════
# HOST SYSTEM
# ═══════════════════════════════════════════════════════

def _host_active(cid) -> bool:
    if cid not in hosted_scripts: return False
    for sid in ("script1", "script2"):
        if sid in hosted_scripts[cid]:
            p = hosted_scripts[cid][sid].get("process")
            if p and p.returncode is None: return True
    return False


def _extract_meta(path):
    r = {"commands": [], "tokens": [], "prefix": ".", "lines": 0, "type": "unknown"}
    if not os.path.exists(path): return r
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f: src = f.read()
    except Exception: return r
    r["lines"] = len(src.splitlines())
    for m in re.finditer(r'CommandHandler\(\s*["\']([^"\']+)["\']', src):
        c = m.group(1)
        if c not in r["commands"]: r["commands"].append(c)
    for m in re.finditer(r'add_handler\(\s*["\']([a-zA-Z0-9_]+)["\']', src):
        c = m.group(1)
        if c not in r["commands"]: r["commands"].append(c)
    r["tokens"] = list(dict.fromkeys(re.findall(r'["\'](\d{8,12}:[A-Za-z0-9_\-]{30,40})["\']', src)))
    if "set_chat_title" in src: r["type"] = "NC Bot"
    if "send_message" in src: r["type"] = "Messaging Bot"
    return r


def _find_script(name):
    if not name.endswith(".py"): name += ".py"
    for c in [name, os.path.join(SCRIPT_DIR, name), os.path.join(UPLOAD_DIR, name)]:
        if os.path.exists(c) and os.path.isfile(c): return os.path.abspath(c)
    return None


async def run_script(path, cid, sid):
    try:
        p = os.path.abspath(path)
        if not os.path.exists(p): return False, f"❌ Not found"
        lp = os.path.join(LOG_DIR, f"{cid}_{sid}.log")
        lf = open(lp, "wb")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", p, stdout=lf, stderr=lf,
                cwd=os.path.dirname(p),
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except Exception as e:
            lf.close(); return False, f"❌ Spawn: {e}"
        await asyncio.sleep(2.0)
        if proc.returncode is not None:
            lf.close()
            try:
                with open(lp, encoding="utf-8", errors="ignore") as f: err = f.read()[-500:]
            except Exception: err = f"Exit {proc.returncode}"
            return False, f"❌ Crash:\n{err}"
        hosted_scripts.setdefault(cid, {})[sid] = {
            "process": proc, "path": p, "started": datetime.now().strftime("%H:%M:%S"),
            "name": os.path.basename(p), "log_file": lf,
        }
        meta = _extract_meta(p)
        hosted_menus.setdefault(cid, {})[sid] = meta
        return True, f"✅ Started ({len(meta['commands'])} cmds)"
    except Exception as e: return False, f"❌ {str(e)[:200]}"


async def stop_script(cid, sid):
    if cid not in hosted_scripts or sid not in hosted_scripts[cid]:
        return False, "❌ Not running"
    try:
        info = hosted_scripts[cid][sid]
        proc = info["process"]
        if proc and proc.returncode is None:
            proc.terminate()
            try: await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                try: await proc.wait()
                except Exception: pass
        try: info.get("log_file", type("x", (), {"close": lambda: None})()).close()
        except Exception: pass
        del hosted_scripts[cid][sid]
        if cid in hosted_menus: hosted_menus[cid].pop(sid, None)
        if not hosted_scripts.get(cid): hosted_scripts.pop(cid, None)
        return True, f"✅ {sid} stopped"
    except Exception as e: return False, f"❌ {str(e)[:150]}"


async def _host_file(update, ctx, slot):
    msg = update.message or update.edited_message
    if not msg: return
    cid = msg.chat_id; sid = f"script{slot}"; rep = msg.reply_to_message
    if rep and rep.document:
        doc = rep.document
        fname = doc.file_name or "hosted.py"
        if not fname.endswith(".py"):
            await msg.reply_text("❌ Only .py files"); return
        status = await msg.reply_text(f"📥 Downloading `{fname}`...")
        try:
            tgf = await ctx.bot.get_file(doc.file_id)
            sp = os.path.join(UPLOAD_DIR, fname)
            await tgf.download_to_drive(sp)
        except Exception as e:
            await status.edit_text(f"❌ DL fail: {str(e)[:200]}"); return
        script_path = sp
        try: await status.edit_text("🚀 Starting...")
        except Exception: pass
    else:
        args = _get_args(ctx)
        if not args:
            await msg.reply_text(f"⚠️ Usage:\n`.host{slot} <file.py>`\nOR reply to .py");
            return
        script_path = _find_script(args[0])
        if not script_path:
            await msg.reply_text(f"❌ Not found: `{args[0]}`"); return
    if cid in hosted_scripts and sid in hosted_scripts[cid]:
        await stop_script(cid, sid)
    ok, res = await run_script(script_path, cid, sid)
    meta = hosted_menus.get(cid, {}).get(sid, {})
    cmds = meta.get("commands", [])
    cmd_list = "\n".join(f"  ▸ `.{c}`" for c in cmds[:15]) or "  (none)"
    if ok:
        await msg.reply_text(
            f"╔══════════════════════════════╗\n"
            f"  📜 𝐇𝐎𝐒𝐓 {slot} — 𝐒𝐓𝐀𝐑𝐓𝐄𝐃\n"
            f"╚══════════════════════════════╝\n\n"
            f"📁 `{os.path.basename(script_path)}`\n"
            f"📊 {res}\n🔤 Prefix: `{meta.get('prefix', '.')}`\n"
            f"📄 Lines: {meta.get('lines', 0)}\n\n"
            f"⚠️ **HOST MODE** — ARYA commands silent\n\n"
            f"**Commands:**\n{cmd_list}")
    else:
        await msg.reply_text(f"❌ **HOST {slot} FAIL**\n\n{res}")


@_guard
async def cmd_host1(update, ctx): await _host_file(update, ctx, 1)


@_guard
async def cmd_host2(update, ctx): await _host_file(update, ctx, 2)


@_guard
async def cmd_stopfile(update, ctx):
    msg = update.message or update.edited_message
    args = _get_args(ctx)
    if not args:
        await msg.reply_text("⚠️ .stopfile <1/2/all>"); return
    t = args[0].lower(); res = []
    if t == "1": res.append((await stop_script(msg.chat_id, "script1"))[1])
    elif t == "2": res.append((await stop_script(msg.chat_id, "script2"))[1])
    elif t == "all":
        for s in ["script1", "script2"]: res.append((await stop_script(msg.chat_id, s))[1])
    else:
        await msg.reply_text("⚠️ 1/2/all"); return
    still = _host_active(msg.chat_id)
    st = "\n🟢 Host active" if still else "\n✅ ARYA resumed"
    await msg.reply_text("🛑 STOP\n" + "\n".join(res) + st)


@_guard
async def cmd_hoststat(update, ctx):
    msg = update.message or update.edited_message
    cid = msg.chat_id
    if cid not in hosted_scripts or not hosted_scripts[cid]:
        await msg.reply_text("📋 No scripts.\n💡 .host1 file.py"); return
    lines = ["📋 HOST STATUS\n"]
    for sid, d in hosted_scripts[cid].items():
        run = d["process"].returncode is None
        m = hosted_menus.get(cid, {}).get(sid, {})
        slot = 1 if sid == "script1" else 2
        lines.append(f"{'🟢' if run else '🔴'} {sid.upper()}\n  📁 {os.path.basename(d['path'])}\n"
                     f"  ⏱ {d['started']}\n  🎯 {len(m.get('commands', []))} cmds\n"
                     f"  🛑 .stopfile {slot}\n")
    await msg.reply_text("\n".join(lines))


@_guard
async def cmd_hostlog(update, ctx):
    msg = update.message or update.edited_message
    args = _get_args(ctx)
    if not args or args[0] not in ("1", "2"):
        await msg.reply_text("⚠️ .hostlog <1/2>"); return
    lp = os.path.join(LOG_DIR, f"{msg.chat_id}_script{args[0]}.log")
    if not os.path.exists(lp):
        await msg.reply_text("📋 No log"); return
    try:
        with open(lp, encoding="utf-8", errors="ignore") as f: c = f.read()
        if not c.strip(): await msg.reply_text("📋 Empty"); return
        await msg.reply_text(f"📋 LOG SLOT {args[0]}\n\n```\n{c[-3000:]}\n```")
    except Exception as e: await msg.reply_text(f"⚠️ {e}")


@_guard
async def cmd_menufile1(update, ctx): await _show_file_menu(update, 1)


@_guard
async def cmd_menufile2(update, ctx): await _show_file_menu(update, 2)


async def _show_file_menu(update, slot):
    msg = update.message or update.edited_message
    cid = msg.chat_id; sid = f"script{slot}"
    if cid not in hosted_scripts or sid not in hosted_scripts[cid]:
        await msg.reply_text(f"❌ Slot {slot} not running"); return
    d = hosted_scripts[cid][sid]; m = hosted_menus.get(cid, {}).get(sid, {})
    cmds = m.get("commands", [])
    ct = "\n".join(f"  ✨ `.{c}`" for c in cmds) if cmds else "  ⚠️ None"
    await msg.reply_text(
        f"📜 HOST SLOT {slot}\n\n"
        f"📁 `{os.path.basename(d['path'])}`\n"
        f"📊 {'🟢 Running' if d['process'].returncode is None else '🔴 Stopped'}\n"
        f"⏱ {d['started']}\n📄 Lines: {m.get('lines', 0)}\n\n"
        f"**Commands:**\n{ct}\n\n🛑 `.stopfile {slot}`")

# ═══════════════════════════════════════════════════════
# IMAGE SEARCH
# ═══════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


def _bing(q):
    r = []
    try:
        url = f"https://www.bing.com/images/search?q={urllib.parse.quote(q)}&form=HDRSC2"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        urls = re.findall(r'"murl":"(https?://[^"]+?)"', html) + \
               re.findall(r'"mediaurl":"(https?://[^"]+?)"', html)
        for u in urls:
            if any(x in u.lower() for x in [".jpg", ".jpeg", ".png", ".webp"]):
                if u not in r: r.append(u)
    except Exception: pass
    return r


def _ddg(q):
    r = []
    try:
        su = f"https://duckduckgo.com/?q={urllib.parse.quote(q)}&iax=images&ia=images"
        req = urllib.request.Request(su, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            h = resp.read().decode("utf-8", errors="ignore")
        vm = re.search(r'vqd=["\']?([\d-]+)', h)
        if not vm: return r
        iu = f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(q)}&vqd={vm.group(1)}&f=,,,&p=1"
        req = urllib.request.Request(iu, headers={**HEADERS, "Referer": "https://duckduckgo.com/",
            "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for it in data.get("results", [])[:30]:
            u = it.get("image", "")
            if u and any(x in u.lower() for x in [".jpg", ".jpeg", ".png", ".webp"]):
                r.append(u)
    except Exception: pass
    return r


def _age_w(a):
    if a <= 0: return ""
    if a <= 2: return "baby"
    if a <= 4: return "toddler"
    if a <= 12: return "kid"
    if a <= 18: return "teenage"
    if a <= 25: return "young"
    if a <= 45: return "adult"
    return "old"


def _logo_q(g, a):
    gg = "boy" if g == "boy" else "girl"
    aw = _age_w(a)
    if aw: return [f"{aw} {gg} portrait photography", f"{a} year old {gg} dp",
                   f"{aw} {gg} stylish photo"]
    return [f"stylish {gg} portrait", f"{gg} attitude dp hd",
            f"handsome {gg}" if g == "boy" else f"beautiful {gg}"]


def _fetch_best(queries, mins=5000, minwh=250):
    random.shuffle(queries); imgs = []
    for q in queries[:3]:
        try:
            x = _bing(q)
            if x:
                imgs.extend(x)
                if len(imgs) >= 20: break
        except Exception: pass
    if len(imgs) < 10:
        for q in queries[:3]:
            try:
                x = _ddg(q)
                if x:
                    imgs.extend(x)
                    if len(imgs) >= 20: break
            except Exception: pass
    if not imgs: raise Exception("No image found")
    imgs = list(dict.fromkeys(imgs)); random.shuffle(imgs)
    for u in imgs[:20]:
        try:
            req = urllib.request.Request(u, headers={**HEADERS, "Referer": "https://google.com/"})
            with urllib.request.urlopen(req, timeout=15) as r: d = r.read()
            if len(d) < mins: continue
            try:
                im = Image.open(io.BytesIO(d)); w, h = im.size
                if w < minwh or h < minwh: continue
                im.verify()
            except Exception: continue
            return u, d
        except Exception: continue
    raise Exception("Download fail")


def fetch_img(g="boy", a=0): return _fetch_best(_logo_q(g, a))


def fetch_famous(t):
    return _fetch_best([f"{t} famous", f"famous {t}", f"{t} hd portrait", f"{t} 4k"],
                       mins=8000, minwh=300)

# ═══════════════════════════════════════════════════════
# LOGO CREATE
# ═══════════════════════════════════════════════════════

def _center(draw, text, font, W, H, sw=0):
    bb = draw.textbbox((0, 0), text, font=font, stroke_width=sw)
    tw = bb[2] - bb[0]; th = bb[3] - bb[1]
    return (W - tw) // 2 - bb[0], (H - th) // 2 - bb[1], tw, th


def _simple_style(draw, text, font, x, y, col=(220,20,20)):
    for r in range(20, 0, -2):
        draw.text((x+r,y), text, font=font, fill=(*col,50))
        draw.text((x-r,y), text, font=font, fill=(*col,50))
        draw.text((x,y+r), text, font=font, fill=(*col,50))
        draw.text((x,y-r), text, font=font, fill=(*col,50))
    draw.text((x+6,y+6), text, font=font, fill=(0,0,0,240))
    draw.text((x,y), text, font=font, fill=(255,255,255,255), stroke_width=8, stroke_fill=col)


def create_logo(img_bytes, name, out_path, darken=0.65):
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    W, H = img.size; t = 1080
    if W < H: nw, nh = t, int(H * (t/W))
    else: nh, nw = t, int(W * (t/H))
    img = img.resize((nw, nh), Image.LANCZOS)
    if nw > nh:
        l = (nw - t) // 2; img = img.crop((l, 0, l + t, nh))
    else:
        tp = (nh - t) // 2; img = img.crop((0, tp, nw, tp + t))
    img = ImageEnhance.Brightness(img).enhance(darken)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    vig = Image.new("L", (t, t), 0); vd = ImageDraw.Draw(vig)
    mr = int((t**2 + t**2)**0.5 / 2); cx = cy = t // 2
    for i in range(40):
        a = int(140 * (i/40))
        vd.ellipse([cx-mr+i*4, cy-mr+i*4, cx+mr-i*4, cy+mr-i*4], fill=255-a)
    vig = vig.filter(ImageFilter.GaussianBlur(80))
    img = Image.composite(img, Image.new("RGB", (t, t), (0,0,0)), vig).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    text = name.upper().strip()
    size = int(t * 0.26); font = _get_font(size)
    tmp = Image.new("RGB", (10,10)); td = ImageDraw.Draw(tmp)
    while size > 50:
        bb = td.textbbox((0,0), text, font=font, stroke_width=10)
        if bb[2]-bb[0] < t-100: break
        size -= 8; font = _get_font(size)
    x, y, _, _ = _center(draw, text, font, t, t, 10)
    colors = [(220,20,20), (255,0,60), (255,90,0), (0,220,220), (230,180,40)]
    try: _simple_style(draw, text, font, x, y, random.choice(colors))
    except Exception:
        draw.text((x,y), text, font=font, fill=(255,255,255), stroke_width=8, stroke_fill=(200,10,10))
    try:
        wf = _get_font(30)
        wb = draw.textbbox((0,0), "⚡ ARYA ⚡", font=wf)
        draw.text((t-(wb[2]-wb[0])-25, t-55), "⚡ ARYA ⚡", font=wf,
                  fill=(255,255,255,220), stroke_width=2, stroke_fill=(0,0,0))
    except Exception: pass
    img.convert("RGB").save(out_path, "JPEG", quality=95)
    return out_path

# ═══════════════════════════════════════════════════════
# STICKERS
# ═══════════════════════════════════════════════════════

def sticker_name(sticker_bytes, naam):
    img = Image.open(io.BytesIO(sticker_bytes)).convert("RGBA")
    W, H = img.size; T = 512
    if W >= H: nw, nh = T, max(1, int(H*T/W))
    else: nh, nw = T, max(1, int(W*T/H))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (T, T), (0,0,0,0))
    canvas.paste(img, ((T-nw)//2, (T-nh)//2), img)
    draw = ImageDraw.Draw(canvas, "RGBA")
    text = naam.upper().strip()
    size = int(T * 0.16); font = _get_font(size)
    tmp = Image.new("RGBA", (10,10)); td = ImageDraw.Draw(tmp)
    while size > 18:
        bb = td.textbbox((0,0), text, font=font, stroke_width=6)
        if bb[2]-bb[0] < T-30: break
        size -= 4; font = _get_font(size)
    bb = draw.textbbox((0,0), text, font=font, stroke_width=6)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    x = (T-tw)//2 - bb[0]; y = T-th-25 - bb[1]
    draw.text((x+3,y+3), text, font=font, fill=(0,0,0,180), stroke_width=6, stroke_fill=(0,0,0,180))
    draw.text((x,y), text, font=font, fill=(255,255,255,255), stroke_width=6, stroke_fill=(200,10,10,255))
    out = io.BytesIO(); canvas.save(out, "WEBP", quality=95, method=6); out.seek(0)
    return out


_STK_COLORS = [(180,220,255),(255,180,220),(180,255,200),(255,220,150),
               (200,180,255),(255,200,200),(200,255,255),(255,240,180),(255,160,180)]


def _draw_wing(d, cx, cy, sz, color, alpha=230, mirror=False):
    r, g, b = color; dirn = -1 if not mirror else 1
    for lw, dy, ln in [(5,0,1.0),(4,18,0.75),(3,34,0.5)]:
        x1=cx; y1=cy+dy
        x2=cx+dirn*int(sz*ln); y2=cy+dy-int(sz*0.35*ln)
        xm=cx+dirn*int(sz*ln*0.5); ym=cy+dy+int(sz*0.15*ln)
        pts=[]
        for t in range(15):
            tt=t/14
            bx=(1-tt)**2*x1+2*(1-tt)*tt*xm+tt**2*x2
            by=(1-tt)**2*y1+2*(1-tt)*tt*ym+tt**2*y2
            pts.append((bx,by))
        d.line(pts, fill=(r,g,b,alpha), width=lw, joint="curve")


def _create_stk(naam, color_override=None):
    T = 512
    canvas = Image.new("RGBA", (T,T), (0,0,0,0))
    text = naam.strip() or "ARYA"
    color = color_override or random.choice(_STK_COLORS)
    r, g, b = color
    size = int(T*0.32); font = _get_stk_font(size)
    tmp = Image.new("RGBA", (10,10)); td = ImageDraw.Draw(tmp)
    while size > 30:
        bb = td.textbbox((0,0), text, font=font)
        if bb[2]-bb[0] < T-130: break
        size -= 6; font = _get_stk_font(size)
    bb = td.textbbox((0,0), text, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    x = (T-tw)//2 - bb[0]; y = (T-th)//2 - bb[1]

    glow = Image.new("RGBA", (T,T), (0,0,0,0)); gd = ImageDraw.Draw(glow)
    for rad in [50,40,30,22,15,10,6]:
        a = max(20, 70-rad)
        gd.text((x,y), text, font=font, fill=(r,g,b,a), stroke_width=rad, stroke_fill=(r,g,b,a))
    glow = glow.filter(ImageFilter.GaussianBlur(6))

    wings = Image.new("RGBA", (T,T), (0,0,0,0)); wd = ImageDraw.Draw(wings)
    wsz = max(30, th//2)
    _draw_wing(wd, x-15, y+th//2, wsz, (255,255,255), 230, False)
    _draw_wing(wd, x+tw+15, y+th//2, wsz, (255,255,255), 230, True)
    wings_g = wings.filter(ImageFilter.GaussianBlur(3))

    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, wings_g)
    canvas = Image.alpha_composite(canvas, wings)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((x+2,y+3), text, font=font, fill=(0,0,0,100))
    draw.text((x,y), text, font=font, fill=(255,255,255,255), stroke_width=2, stroke_fill=(r,g,b,255))
    tg = Image.new("RGBA", (T,T), (0,0,0,0)); td2 = ImageDraw.Draw(tg)
    for rad in [8,5]:
        td2.text((x,y), text, font=font, fill=(r,g,b,60), stroke_width=rad, stroke_fill=(r,g,b,60))
    tg = tg.filter(ImageFilter.GaussianBlur(3))
    canvas = Image.alpha_composite(canvas, tg)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((x,y), text, font=font, fill=(255,255,255,255), stroke_width=1, stroke_fill=(255,255,255,255))
    out = io.BytesIO(); canvas.save(out, "WEBP", quality=95, method=6); out.seek(0)
    return out


def _has_ffmpeg():
    try: return subprocess.run(["ffmpeg","-version"], capture_output=True, timeout=5).returncode == 0
    except Exception: return False


HAS_FFMPEG = _has_ffmpeg()


def proc_video_stk(webm, naam):
    if not HAS_FFMPEG: raise Exception("ffmpeg missing")
    fp = _find_font_path()
    if not fp: raise Exception("Font missing")
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "in.webm"); op = os.path.join(td, "out.webm")
        tf = os.path.join(td, "t.txt")
        with open(ip, "wb") as f: f.write(webm)
        with open(tf, "w", encoding="utf-8") as f: f.write(naam.upper())
        fpp = fp.replace("'", "'\\''")
        vf = f"drawtext=fontfile='{fpp}':textfile='{tf}':fontcolor=white:fontsize=44:borderw=4:bordercolor=red:x=(w-text_w)/2:y=h-text_h-20"
        cmd = ["ffmpeg","-y","-i",ip,"-vf",vf,"-c:v","libvpx-vp9","-pix_fmt","yuva420p",
               "-b:v","250k","-crf","38","-an","-t","3",op]
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        if r.returncode != 0: raise Exception("ffmpeg fail")
        with open(op, "rb") as f: data = f.read()
        if len(data) > 500*1024: raise Exception("Too big")
        return io.BytesIO(data)


def proc_tgs(tgs, naam):
    if not HAS_RLOTTIE: raise Exception("rlottie missing")
    if not HAS_FFMPEG: raise Exception("ffmpeg missing")
    jd = gzip.decompress(tgs).decode("utf-8")
    anim = LottieAnimation.from_data(jd)
    total = min(anim.lottie_animation_get_totalframe(), 180)
    fps = int(round(anim.lottie_animation_get_framerate() or 30))
    with tempfile.TemporaryDirectory() as td:
        for i in range(total):
            pil = anim.render_pillow_frame(frame_num=i).convert("RGBA")
            w, h = pil.size
            if w != 512 or h != 512:
                nw, nh = (512, max(1,int(h*512/w))) if w >= h else (max(1,int(w*512/h)), 512)
                pil = pil.resize((nw, nh), Image.LANCZOS)
                c = Image.new("RGBA", (512,512), (0,0,0,0))
                c.paste(pil, ((512-nw)//2, (512-nh)//2), pil); pil = c
            d = ImageDraw.Draw(pil, "RGBA")
            text = naam.upper().strip()
            size = int(512*0.16); font = _get_font(size)
            tmp = Image.new("RGBA", (10,10)); td2 = ImageDraw.Draw(tmp)
            while size > 14:
                bb = td2.textbbox((0,0), text, font=font, stroke_width=6)
                if bb[2]-bb[0] < 512-30: break
                size -= 4; font = _get_font(size)
            bb = d.textbbox((0,0), text, font=font, stroke_width=6)
            tw, th = bb[2]-bb[0], bb[3]-bb[1]
            x = (512-tw)//2 - bb[0]; y = 512-th-25 - bb[1]
            d.text((x+3,y+3), text, font=font, fill=(0,0,0,180), stroke_width=6, stroke_fill=(0,0,0,180))
            d.text((x,y), text, font=font, fill=(255,255,255,255), stroke_width=6, stroke_fill=(200,10,10,255))
            pil.save(os.path.join(td, f"f_{i:05d}.png"), "PNG")
        op = os.path.join(td, "out.webm")
        cmd = ["ffmpeg","-y","-framerate",str(fps),"-i",os.path.join(td,"f_%05d.png"),
               "-c:v","libvpx-vp9","-pix_fmt","yuva420p","-b:v","250k","-crf","38","-an","-t","3",op]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0: raise Exception("ffmpeg fail")
        with open(op, "rb") as f: data = f.read()
        if len(data) > 500*1024: raise Exception("Too big")
        return io.BytesIO(data)

# ═══════════════════════════════════════════════════════
# CONTENT
# ═══════════════════════════════════════════════════════

ROASTS = ["Tera face dekh ke Google bhi bolta hai '404' 😂",
    "Tu itna slow hai ki WiFi bhi tujhse faster hai 🐌",
    "Tere jaisa banda dekh ke mirror bhi sharma jata hai 🪞",
    "Teri personality Windows Vista jaisi — purani aur useless 💀",
    "Tu itna useless hai ki Google bhi tujhe search nahi karta 🔍"]

SHAYARI = ["Dil ki baat labon pe na laao,\nJo tumhe chahe use jaanne do,\nMohabbat me koi jaldi nahi hoti ❤️",
    "Zindagi ek kitaab hai,\nHar panne pe naya sabaq,\nPadhte raho, seekhte raho 📖",
    "Chand ko dekh ke tare jalte hain,\nTumhe dekh ke hum pagal hote hain 🌙"]

FLIRT = ["Teri smile dekh ke lagta hai,\nChand bhi sharma gaya hoga 🌙",
    "Dil ne kaha dhadakna zaroori hai,\nTumse milna bhi zaroori hai ❤️",
    "Tere aankhon mein doob jaana chahta hoon,\nTeri baahon mein kho jaana chahta hoon 💘"]

JOKES = ["Teacher: 2+2 kitna?\nStudent: 4\nTeacher: 4+4?\nStudent: 44 😂",
    "Wife: Surprise do!\nHusband: Tum aaj bhi sundar lag rahi ho 😂",
    "Doctor: Bimari?\nBanda: Bhoolne ki\nDoctor: Kab se?\nBanda: Kya? 🤔"]

QUOTES = ["✨ 'Sapne wo nahi jo sote hue dekhte ho' — Kalam",
    "💪 'Kamyabi ka raaz — shuru karna aur laga rehna'",
    "🔥 'Grind karo, results khud bolenge'"]

TRUTHS = ["Kabhi kisi ko secretly block kiya? 🤐", "Sabse embarrassing moment? 😳",
    "Last kisi ko kab jhooth bola? 🤥", "Crush kaun hai? 💘"]

DARES = ["Apni photo bhej 10 sec me 📸", "5 log ko msg 'I love you' 💌",
    "Ek emoji se feeling bata 😊", "Phone wallpaper bhej 📱"]

RR_REPLIES = ["Kya Re Randike Cool Banega Tu Chal Ab Chud Apne Baap AryA Se",
    "acha beta ? coi na me toh HATER codunga",
    "chudke bhaga kaise",
    "ne toh AryA ka lun muh me lelia",
    "try maa surya nikalte hi pel du",
    "mkl lun te vaj",
    "TmkB pe AryA ka hamla",
    "Chl Haramzadi Ke ladke",
    "oi Teri Maa gulam",
    "chl rndyce chud ke dikha",
    "Ki Maa Marr Gayi naacho",
    "tera baap bass AryA hai",
    "try maa hagte hue paad mari",
    "Teri Mummy Chod Di AryA Ne Bwahahaha",
    "Cyu Re madarchod AryA baap ke samne Fyter Banega",
    "nahi nahi teri maa ko Sirf AryA baap chod sakta hai samjha randike",
    "teri maa ka Stylish bhosda",
    "Tery maa randAL h bas baat khatam",
"༒🩷༒ᴛᴇʀɪ  माँ चुद ɢʏɪ ༒🩷༒",
 "Tᴇʀɪ MᴜᴍᴍY Cʜᴜᴅᴋʀ Mᴇᴏᴡ Mᴇᴏᴡ Bᴏʟᴇ🛑⊕⊖⊚◎◌○○",
    "Pɪʟʟᴇ Jᴏʀ Lᴀɢᴀ Sᴘᴀᴍ Kʀ♛♜",
    "RANDYK हाग के गांड धोना सीख FIR ANA Arya SE LADNE",
    " CʜᴜP ! 𝐂ʜᴜᴅᴀɪᴋʜᴀɴ𝐈 ! >  🌙",
    "ɱ~ų~ɬ~ɧ ₘₐₐᵣ ARYA 𝐊i ✨",
    "कमजोर मादरचोद ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴋᴀʟɪ ɢɴᴅ ᴩᴇ нαg∂υ 🤸🤸🤸",
    "𝗢𝗥 𝗕𝗘𝗧𝗘 🅼🅰️🅰️ 🅺🅰️🅸🆂🅴 🅷 🆃🅷🆄🅼🅰️🆁🅸 𝙎𝙐𝙉 𝙍𝙃𝘼 𝙈𝙀𝙍𝙄 𝙔𝘼𝘼𝘿 𝘼𝘼𝙏𝙄  ",
    "𝘾𝙃𝘼𝙇 𝙆𝙃𝙐𝙎𝙃 𝙃𝙊𝙅𝘼 𝙏𝙀𝙍𝙄  मां  𝙆𝙄 चुदाई 𝙆𝘼𝙍𝙉𝙀 ARYA 𝘽𝙃𝘼𝙂𝙒𝘼𝙉 𝘼𝘼𝙔𝙀 𝙃𝘼𝙄𝙉",
    "ᴀᴍᴊᴏʀ 🇦‌🇼‌🇸‌ 🇺‌🇸‌🇪‌🇷 ᴛᴇʀɪ  ᴍᴀᴀ  ᴄʜᴏᴅ  ᴋᴇ  ᴍᴀᴀʀ  ᴅᴜɴɢᴀ (𓃵)- ​🇰​​🇺​​🇹​​🇹​​🇮​ ​🇰​​🇪‌",
    "Cʜᴜᴅᴋʀ Mᴀʀɢʏᴀ Kᴍᴊᴏʀ Gᴜʟᴀᴍ? 𓄅𓅨𓄀𓄆𓅃𓆀𓅃",
"TMKC 🅶︎🆄︎🅻︎🅰︎🅼︎ 🅷︎ 🆃︎🆄︎ 🅶︎🆄︎🅻︎🅰︎🅼︎🅸︎ 🅺︎🅰︎🆁︎ 🇦‌🇷‌🇾‌🇦‌ 🇵‌🇦‌🇵‌🇦‌ 🇰‌🇮‌𒀱ꪳ❤𒀱ꪳ🩵𒀱ꪳ💛𒀱ꪳ💚𒀱ꪳ❤𒀱ꪳ🩵𒀱ꪳ💛𒀱ꪳ💚𒀱ꪳ❤𒀱ꪳ🩵𒀱ꪳ💛𒀱ꪳ💚𒀱ꪳ❤𒀱ꪳ",
    "soch teri behan ko AryA baap ka gulam chod raha",
"━〔 {तेरी माँ की चुदाई हो रही??🧐〕━━",
    "Tery maa randAL h bas baat ख़तम",
"╰┈➤कमजोर पिल्ले °•*⁀➷💛᪲᪲᪲ [ 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀 𝐊𝐀 𝐁𝐇𝐎𝐒𝐃𝐀 ]  ׂ╰┈➤˚.👑❤️‍🔥",
    "Shut up randike warna duniya yahi bolegi teri behan AryA baap se sahi chudia",
    "tu or teri maa dono Arya baap ke lnd se kabhi uth nahi paye",]

# ═══════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════

@dedup
async def start_cmd(u, c):
    await safe_reply(u.message, "⚡ **ARYA BOT**\n`.help` dekho", parse_mode="Markdown")


@dedup
async def help_cmd(u, c):
    p = COMMAND_PREFIX
    await safe_reply(u.message, f"""⚡ **ARYA BOT** ⚡

📌 **Media**
`{p}yt` `{p}song` `{p}logo` `{p}fem` `{p}custmstk` `{p}stk`

📌 **Fun**
`{p}roast` `{p}shayari` `{p}joke` `{p}quote` `{p}qt` `{p}truth` `{p}dare`
`{p}ship` `{p}coin` `{p}dice` `{p}8ball` `{p}rps` `{p}cat` `{p}dog` `{p}wasted`

📌 **Group Admin**
`{p}mute` `{p}unmute` `{p}prompt` `{p}lock` `{p}unlock`

📌 **Owner Only**
`{p}block` `{p}unblock` `{p}blocklist` `{p}rr` `{p}srr` `{p}gc`
`{p}host1` `{p}host2` `{p}stopfile` `{p}hoststat` `{p}hostlog`
`{p}menufile1` `{p}menufile2`""", parse_mode="Markdown")


@dedup
async def ping_cmd(u, c):
    t0 = time.time(); m = await safe_reply(u.message, "🏓")
    if m: await safe_edit(m, f"🏓 {int((time.time()-t0)*1000)}ms")


@dedup
async def test_cmd(u, c):
    await safe_reply(u.message, f"✅ WORKING\n`{u.effective_chat.id}`", parse_mode="Markdown")


@dedup
async def check_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group", "supergroup"):
        return await safe_reply(u.message, "ℹ️ Group me use karo")
    try:
        me = await c.bot.get_me()
        m = await c.bot.get_chat_member(chat.id, me.id)
        ok = m.status == ChatMember.ADMINISTRATOR
        await safe_reply(u.message, f"{'✅ ADMIN' if ok else '⚠️ NOT ADMIN'}\n`{chat.id}`", parse_mode="Markdown")
    except Exception as e: await safe_reply(u.message, f"❌ {e}")


@dedup
async def gc_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if not KNOWN_CHATS: return await safe_reply(u.message, "📋 None")
    lines = [f"📋 **{len(KNOWN_CHATS)} groups**\n"]
    for cid in list(KNOWN_CHATS)[:30]:
        try:
            ch = await c.bot.get_chat(cid)
            lines.append(f"• {ch.title} — `{cid}`")
        except Exception: lines.append(f"• `{cid}`")
    await safe_reply(u.message, "\n".join(lines), parse_mode="Markdown")

# ─── YT / SONG ────────────────────────────────────────

@dedup
async def yt_cmd(u, c):
    if not c.args:
        return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}yt <search>`")
    q = " ".join(c.args).strip()
    st = await safe_reply(u.message, f"🎬 **{q}**\n⏳ Downloading...", parse_mode="Markdown")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    fn = None
    try:
        def _dl():
            o = get_ydl_opts({
                "format": "best[ext=mp4][height<=720]/best[ext=mp4]/best[height<=720]/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
                "max_filesize": 50*1024*1024,
            })
            with yt_dlp.YoutubeDL(o) as y: return y.extract_info(f"ytsearch1:{q}", download=True)
        info = await asyncio.get_event_loop().run_in_executor(None, _dl)
        if not info: return await safe_edit(st, "❌ Not found")
        v = info["entries"][0] if "entries" in info else info
        if not v: return await safe_edit(st, "❌ Empty")
        title = (v.get("title") or "Video")[:200]; vid = v.get("id") or "v"
        dur = v.get("duration") or 0; up = v.get("uploader") or ""
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(str(vid)): fn = os.path.join(DOWNLOAD_DIR, f); break
        if not fn or not os.path.exists(fn):
            return await safe_edit(st, "❌ Download fail")
        mb = os.path.getsize(fn) / (1024*1024)
        if mb > 50:
            try: os.remove(fn)
            except Exception: pass
            return await safe_edit(st, f"❌ Too big ({mb:.1f}MB)")
        await safe_edit(st, f"📤 {mb:.1f}MB...")
        with open(fn, "rb") as vf:
            await u.message.reply_video(video=vf,
                caption=f"🎬 **{title}**\n👤 {up}\n📦 {mb:.1f}MB",
                parse_mode="Markdown", supports_streaming=True,
                duration=int(dur) if dur else 0)
        await safe_del(st)
    except yt_dlp.utils.DownloadError as e:
        err = str(e); logger.error(f"YT: {err[:200]}")
        if "Sign in to confirm" in err or "bot" in err.lower():
            await safe_edit(st, "🔄 **Cobalt try...**", parse_mode="Markdown")
            try:
                r = await cobalt_download(q, is_audio=False)
                if r and r.get("url"):
                    out = os.path.join(DOWNLOAD_DIR, f"cb_{int(time.time())}.mp4")
                    if await dl_from_url(r["url"], out) and os.path.exists(out):
                        mb = os.path.getsize(out) / (1024*1024)
                        if mb <= 50:
                            with open(out, "rb") as vf:
                                await u.message.reply_video(video=vf,
                                    caption=f"🎬 **{(r.get('title') or q)[:200]}**\n⚡ via Cobalt",
                                    parse_mode="Markdown", supports_streaming=True)
                            await safe_del(st)
                            try: os.remove(out)
                            except Exception: pass
                            return
                        else: 
                            try: os.remove(out)
                            except Exception: pass
                await safe_edit(st,
                    "❌ **Bot detection**\n\n"
                    "**Options:**\n• 5 min baad try karo\n"
                    "• Cookies set karo (`YTDL_COOKIES_B64`)",
                    parse_mode="Markdown")
            except Exception as fe:
                await safe_edit(st, f"⚠️ `{str(fe)[:150]}`", parse_mode="Markdown")
            return
        if "Video unavailable" in err: msg = "❌ Video unavailable"
        elif "429" in err: msg = "⚠️ Rate limit — 5 min"
        else: msg = f"⚠️ `{err[:200]}`"
        await safe_edit(st, msg)
    except Exception as e:
        logger.error(f"YT: {e}")
        await safe_edit(st, f"⚠️ `{str(e)[:200]}`")
    finally:
        if fn and os.path.exists(fn):
            try: os.remove(fn)
            except Exception: pass


@dedup
async def song_cmd(u, c):
    if not c.args:
        return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}song <name>`")
    q = " ".join(c.args).strip()
    st = await safe_reply(u.message, f"🎵 **{q}**\n⏳...", parse_mode="Markdown")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    fn = None
    try:
        def _dl():
            o = get_ydl_opts({
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio","preferredcodec": "mp3","preferredquality": "192"}],
            })
            with yt_dlp.YoutubeDL(o) as y: return y.extract_info(f"ytsearch1:{q}", download=True)
        info = await asyncio.get_event_loop().run_in_executor(None, _dl)
        if not info: return await safe_edit(st, "❌ Not found")
        v = info["entries"][0] if "entries" in info else info
        if not v: return await safe_edit(st, "❌ Empty")
        title = (v.get("title") or "Audio")[:200]; vid = v.get("id") or "a"
        dur = v.get("duration") or 0; art = v.get("uploader") or ""
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(str(vid)): fn = os.path.join(DOWNLOAD_DIR, f); break
        if not fn or not os.path.exists(fn):
            return await safe_edit(st, "❌ Fail")
        mb = os.path.getsize(fn) / (1024*1024)
        if mb > 25:
            try: os.remove(fn)
            except Exception: pass
            return await safe_edit(st, f"❌ Big ({mb:.1f}MB)")
        await safe_edit(st, f"📤 {mb:.1f}MB...")
        with open(fn, "rb") as a:
            await u.message.reply_audio(audio=a, title=title, performer=art,
                duration=int(dur) if dur else 0,
                caption=f"🎵 **{title}**\n🎤 {art}",
                parse_mode="Markdown")
        await safe_del(st)
    except yt_dlp.utils.DownloadError as e:
        err = str(e); logger.error(f"Song: {err[:200]}")
        if "Sign in to confirm" in err or "bot" in err.lower():
            await safe_edit(st, "🔄 **Cobalt try...**", parse_mode="Markdown")
            try:
                r = await cobalt_download(q, is_audio=True)
                if r and r.get("url"):
                    out = os.path.join(DOWNLOAD_DIR, f"cb_{int(time.time())}.mp3")
                    if await dl_from_url(r["url"], out) and os.path.exists(out):
                        mb = os.path.getsize(out) / (1024*1024)
                        if mb <= 25:
                            with open(out, "rb") as a:
                                await u.message.reply_audio(audio=a,
                                    title=(r.get("title") or q)[:200],
                                    caption="⚡ via Cobalt")
                            await safe_del(st)
                            try: os.remove(out)
                            except Exception: pass
                            return
                        else:
                            try: os.remove(out)
                            except Exception: pass
                await safe_edit(st, "❌ **Bot detection** — cookies set karo", parse_mode="Markdown")
            except Exception as fe:
                await safe_edit(st, f"⚠️ `{str(fe)[:150]}`", parse_mode="Markdown")
            return
        if "Video unavailable" in err: msg = "❌ Unavailable"
        else: msg = f"⚠️ `{err[:200]}`"
        await safe_edit(st, msg)
    except Exception as e:
        await safe_edit(st, f"⚠️ `{str(e)[:200]}`")
    finally:
        if fn and os.path.exists(fn):
            try: os.remove(fn)
            except Exception: pass

# ─── LOGO / FEM / CUSTMSTK / STK ─────────────────────

@dedup
async def logo_cmd(u, c):
    if not c.args: return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}logo <name> [boy/girl] [age]`")
    args = list(c.args); g = "boy"; a = 0
    if args and args[-1].isdigit():
        try:
            x = int(args[-1])
            if 1 <= x <= 120: a = x; args = args[:-1]
        except Exception: pass
    if args and args[-1].lower() in ("boy","girl","b","g","male","female","m","f"):
        l = args[-1].lower(); g = "boy" if l in ("boy","b","male","m") else "girl"
        args = args[:-1]
    name = " ".join(args).strip()
    if not name: return await safe_reply(u.message, "❌ Name missing")
    st = await safe_reply(u.message, f"🎨 {g} {name}")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    op = os.path.join(DOWNLOAD_DIR, f"l_{int(time.time())}.jpg")
    try:
        loop = asyncio.get_event_loop()
        _, d = await loop.run_in_executor(None, fetch_img, g, a)
        await loop.run_in_executor(None, create_logo, d, name, op, 0.65)
        with open(op, "rb") as p:
            cap = f"⚡ **ARYA LOGO**\n🔮 {name}\n🎭 {g.title()}"
            if a: cap += f"\n🎂 {a}"
            await u.message.reply_photo(photo=p, caption=cap, parse_mode="Markdown")
        await safe_del(st)
    except Exception as e:
        await safe_edit(st, f"⚠️ `{str(e)[:200]}`")
    finally:
        if os.path.exists(op):
            try: os.remove(op)
            except Exception: pass


@dedup
async def fem_cmd(u, c):
    if not c.args: return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}fem <search> | <name>`")
    full = " ".join(c.args)
    if "|" in full:
        p = full.split("|",1); s = p[0].strip(); w = p[1].strip()
    else: s = w = full.strip()
    if not s: return await safe_reply(u.message, "❌ Missing")
    if not w: w = s
    st = await safe_reply(u.message, f"🐾 {s} → {w}")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    op = os.path.join(DOWNLOAD_DIR, f"f_{int(time.time())}.jpg")
    try:
        loop = asyncio.get_event_loop()
        _, d = await loop.run_in_executor(None, fetch_famous, s)
        await loop.run_in_executor(None, create_logo, d, w, op, 0.60)
        with open(op, "rb") as p:
            await u.message.reply_photo(photo=p, caption=f"🐾 {s.title()}\n✍️ {w.title()}")
        await safe_del(st)
    except Exception as e:
        await safe_edit(st, f"⚠️ `{str(e)[:200]}`")
    finally:
        if os.path.exists(op):
            try: os.remove(op)
            except Exception: pass


@dedup
async def custmstk_cmd(u, c):
    msg = u.message
    if not msg.reply_to_message or not msg.reply_to_message.sticker:
        return await safe_reply(msg, f"❌ Reply to sticker + `{COMMAND_PREFIX}custmstk <name>`")
    if not c.args: return await safe_reply(msg, "❌ Name missing")
    naam = " ".join(c.args).strip()[:40]
    stk = msg.reply_to_message.sticker
    st = await safe_reply(msg, f"🎨 `{naam}`...")
    try:
        f = await c.bot.get_file(stk.file_id)
        d = await f.download_as_bytearray()
        loop = asyncio.get_event_loop()
        if stk.is_video: out = await loop.run_in_executor(None, proc_video_stk, bytes(d), naam)
        elif stk.is_animated: out = await loop.run_in_executor(None, proc_tgs, bytes(d), naam)
        else: out = await loop.run_in_executor(None, sticker_name, bytes(d), naam)
        await safe_edit(st, "📤...")
        await msg.reply_sticker(sticker=out)
        await safe_del(st)
    except Exception as e:
        await safe_edit(st, f"❌ `{str(e)[:150]}`", parse_mode="Markdown")


@dedup
async def stk_cmd(u, c):
    if not c.args:
        return await safe_reply(u.message, f"✨ `{COMMAND_PREFIX}stk <name> [color]`\n"
            f"Colors: blue pink mint gold purple cyan", parse_mode="Markdown")
    cmap = {"blue":(180,220,255),"pink":(255,180,220),"mint":(180,255,200),
            "gold":(255,220,150),"purple":(200,180,255),"cyan":(200,255,255),
            "rose":(255,160,180),"peach":(255,200,200),"yellow":(255,240,180)}
    args = list(c.args); col = None
    if len(args) >= 2 and args[-1].lower() in cmap:
        col = cmap[args[-1].lower()]; args = args[:-1]
    naam = " ".join(args).strip()[:30]
    if not naam: return await safe_reply(u.message, "❌ Name missing")
    st = await safe_reply(u.message, f"✨ `{naam}`...")
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, _create_stk, naam, col)
        await safe_edit(st, "📤...")
        await u.message.reply_sticker(sticker=out)
        await safe_del(st)
    except Exception as e:
        await safe_edit(st, f"❌ `{str(e)[:150]}`", parse_mode="Markdown")

# ─── FUN ─────────────────────────────────────────────

@dedup
async def roast_cmd(u, c):
    t = _tname(u) or (" ".join(c.args) if c.args else u.effective_user.first_name)
    await safe_reply(u.message, f"🔥 **{t}**\n\n{random.choice(ROASTS)}", parse_mode="Markdown")


@dedup
async def shayari_cmd(u, c):
    t = _tname(u); s = random.choice(SHAYARI)
    h = f"🌹 **Shayari for {t}** 🌹" if t else "🌹 **Shayari** 🌹"
    f = f"\n\n— **{u.effective_user.first_name}** 💌" if t else f"\n\n— **{u.effective_user.first_name}**"
    await safe_reply(u.message, f"{h}\n\n{s}{f}", parse_mode="Markdown")


@dedup
async def joke_cmd(u, c):
    t = _tname(u); j = random.choice(JOKES)
    h = f"😂 **Joke for {t}**" if t else "😂 **Joke**"
    await safe_reply(u.message, f"{h}\n\n{j}", parse_mode="Markdown")


@dedup
async def quote_cmd(u, c): await safe_reply(u.message, random.choice(QUOTES))


@dedup
async def qt_cmd(u, c):
    t = _tname(u); s = random.choice(FLIRT)
    h = f"💕 **Flirt for {t}**" if t else "💕 **Flirt**"
    await safe_reply(u.message, f"{h}\n\n{s}", parse_mode="Markdown")


@dedup
async def truth_cmd(u, c):
    await safe_reply(u.message, f"💭 **TRUTH**\n\n{random.choice(TRUTHS)}", parse_mode="Markdown")


@dedup
async def dare_cmd(u, c):
    await safe_reply(u.message, f"🎯 **DARE**\n\n{random.choice(DARES)}", parse_mode="Markdown")


@dedup
async def ship_cmd(u, c):
    names = []
    if u.message.reply_to_message and u.message.reply_to_message.from_user:
        names = [u.effective_user.first_name, u.message.reply_to_message.from_user.first_name]
    elif len(c.args) >= 2: names = c.args[:2]
    else: return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}ship <a> <b>`")
    pct = (sum(ord(x) for x in "".join(names).lower()) * 7) % 101
    bar = "❤️"*(pct//10) + "🖤"*(10-pct//10)
    msg = ("🔥 PERFECT 💍" if pct>=90 else "😍 Acha" if pct>=70 else
           "🙂 Theek" if pct>=50 else "😐 Hope mat" if pct>=30 else "💔 Bhool jao")
    await safe_reply(u.message, f"💘 {names[0]} + {names[1]}\n💗 {pct}%\n{bar}\n{msg}", parse_mode="Markdown")


@dedup
async def coin_cmd(u, c): await safe_reply(u.message, f"🪙 {random.choice(['HEADS','TAILS'])}")


@dedup
async def dice_cmd(u, c):
    try: n = max(2, min(int(c.args[0]) if c.args else 6, 1000))
    except Exception: n = 6
    await safe_reply(u.message, f"🎲 **{random.randint(1,n)}** (1-{n})", parse_mode="Markdown")


@dedup
async def eightball_cmd(u, c):
    if not c.args: return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}8ball <q>`")
    ans = ["✅ Haan","❌ Nahi","🤔 Shayad","💯 Pakka","🚫 Kabhi nahi","🎯 Try kar"]
    await safe_reply(u.message, f"🎱 **{random.choice(ans)}**", parse_mode="Markdown")


@dedup
async def rps_cmd(u, c):
    if not c.args or c.args[0].lower() not in ("rock","paper","scissor","scissors"):
        return await safe_reply(u.message, f"❌ `{COMMAND_PREFIX}rps rock/paper/scissor`")
    us = c.args[0].lower().replace("scissors","scissor"); bt = random.choice(["rock","paper","scissor"])
    e = {"rock":"🪨","paper":"📄","scissor":"✂️"}
    if us == bt: r = "🤝 TIE"
    elif (us=="rock" and bt=="scissor") or (us=="paper" and bt=="rock") or (us=="scissor" and bt=="paper"): r = "🎉 JEETE!"
    else: r = "😎 BOT JEETA"
    await safe_reply(u.message, f"👤 {e[us]} {us}\n🤖 {e[bt]} {bt}\n**{r}**", parse_mode="Markdown")


@dedup
async def cat_cmd(u, c):
    try:
        req = urllib.request.Request("https://api.thecatapi.com/v1/images/search", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r: d = json.loads(r.read())
        await u.message.reply_photo(d[0]["url"], caption="🐱 Meow!")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:100]}")


@dedup
async def dog_cmd(u, c):
    try:
        req = urllib.request.Request("https://dog.ceo/api/breeds/image/random", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r: d = json.loads(r.read())
        await u.message.reply_photo(d["message"], caption="🐶 Woof!")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:100]}")


@dedup
async def wasted_cmd(u, c):
    fid = None
    if u.message.reply_to_message and u.message.reply_to_message.photo:
        fid = u.message.reply_to_message.photo[-1].file_id
    else:
        try:
            ph = await c.bot.get_user_profile_photos(u.effective_user.id, limit=1)
            if ph.total_count > 0: fid = ph.photos[0][-1].file_id
        except Exception: pass
    if not fid: return await safe_reply(u.message, "❌ Photo pe reply karo")
    st = await safe_reply(u.message, "💀...")
    try:
        f = await c.bot.get_file(fid); d = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(bytes(d))).convert("RGB")
        W, H = img.size
        img = ImageEnhance.Color(img).enhance(0.3); img = ImageEnhance.Brightness(img).enhance(0.7)
        draw = ImageDraw.Draw(img, "RGBA"); font = _get_font(int(W*0.18)); text = "WASTED"
        bb = draw.textbbox((0,0), text, font=font, stroke_width=6)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
        x = (W-tw)//2 - bb[0]; y = (H-th)//2 - bb[1]
        draw.text((x+5,y+5), text, font=font, fill=(0,0,0,220))
        draw.text((x,y), text, font=font, fill=(255,30,30,255), stroke_width=6, stroke_fill=(0,0,0))
        out = io.BytesIO(); img.save(out, "JPEG", quality=92); out.seek(0)
        await u.message.reply_photo(out, caption="💀 **WASTED**", parse_mode="Markdown")
        await safe_del(st)
    except Exception as e: await safe_edit(st, f"❌ {str(e)[:180]}")

# ─── GROUP ADMIN ──────────────────────────────────────

@dedup
async def mute_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group","supergroup"): return await safe_reply(u.message, "❌ Group only")
    if not await is_group_admin(chat.id, u.effective_user.id, c):
        return await safe_reply(u.message, "❌ Admin only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    if t.id == OWNER_ID: return await safe_reply(u.message, "😂 Owner ko nahi")
    try:
        await c.bot.restrict_chat_member(chat.id, t.id, permissions=ChatPermissions(
            can_send_messages=False, can_send_media_messages=False, can_send_polls=False,
            can_send_other_messages=False, can_add_web_page_previews=False,
            can_change_info=False, can_invite_users=False, can_pin_messages=False))
        await safe_reply(u.message, f"🔇 Muted: {t.first_name}")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:150]}")


@dedup
async def unmute_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group","supergroup"): return await safe_reply(u.message, "❌ Group only")
    if not await is_group_admin(chat.id, u.effective_user.id, c): return await safe_reply(u.message, "❌ Admin only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    try:
        await c.bot.restrict_chat_member(chat.id, t.id, permissions=ChatPermissions(
            can_send_messages=True, can_send_media_messages=True, can_send_polls=True,
            can_send_other_messages=True, can_add_web_page_previews=True,
            can_change_info=False, can_invite_users=True, can_pin_messages=False))
        await safe_reply(u.message, f"🔊 Unmuted: {t.first_name}")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:150]}")


@dedup
async def prompt_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group","supergroup"): return await safe_reply(u.message, "❌ Group only")
    if not await is_group_admin(chat.id, u.effective_user.id, c): return await safe_reply(u.message, "❌ Admin only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    if t.is_bot: return await safe_reply(u.message, "❌ Bot ko nahi")
    try:
        await c.bot.promote_chat_member(chat.id, t.id, can_change_info=False,
            can_delete_messages=True, can_invite_users=True, can_restrict_members=True,
            can_pin_messages=True, can_promote_members=False, can_manage_video_chats=True,
            can_manage_chat=True, is_anonymous=False)
        await safe_reply(u.message, f"👑 Promoted: {t.first_name}")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:150]}")


@dedup
async def lock_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group","supergroup"): return await safe_reply(u.message, "❌ Group only")
    if not await is_group_admin(chat.id, u.effective_user.id, c): return await safe_reply(u.message, "❌ Admin only")
    if chat.id in LOCKED_CHATS: return await safe_reply(u.message, "🔒 Already")
    try:
        await c.bot.set_chat_permissions(chat.id, permissions=ChatPermissions(
            can_send_messages=False, can_send_media_messages=False, can_send_polls=False,
            can_send_other_messages=False, can_add_web_page_previews=False,
            can_change_info=False, can_invite_users=False, can_pin_messages=False))
        LOCKED_CHATS.add(chat.id); await save_locked()
        await safe_reply(u.message, "🔒 LOCKED")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:150]}")


@dedup
async def unlock_cmd(u, c):
    chat = u.effective_chat
    if chat.type not in ("group","supergroup"): return await safe_reply(u.message, "❌ Group only")
    if not await is_group_admin(chat.id, u.effective_user.id, c): return await safe_reply(u.message, "❌ Admin only")
    if chat.id not in LOCKED_CHATS: return await safe_reply(u.message, "🔓 Already")
    try:
        await c.bot.set_chat_permissions(chat.id, permissions=ChatPermissions(
            can_send_messages=True, can_send_media_messages=True, can_send_polls=True,
            can_send_other_messages=True, can_add_web_page_previews=True,
            can_change_info=False, can_invite_users=True, can_pin_messages=False))
        LOCKED_CHATS.discard(chat.id); await save_locked()
        await safe_reply(u.message, "🔓 UNLOCKED")
    except Exception as e: await safe_reply(u.message, f"❌ {str(e)[:150]}")

# ─── OWNER: BLOCK ─────────────────────────────────────

@dedup
async def block_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    if t.id == OWNER_ID: return await safe_reply(u.message, "😂 Khud ko nahi")
    BLOCKED_USERS.add(t.id); await save_blocked()
    await safe_reply(u.message, f"🚫 Blocked: {t.first_name}")


@dedup
async def unblock_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    if t.id in BLOCKED_USERS:
        BLOCKED_USERS.discard(t.id); await save_blocked()
        await safe_reply(u.message, f"✅ Unblocked: {t.first_name}")
    else: await safe_reply(u.message, "ℹ️ Nahi hai")


@dedup
async def blocklist_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if not BLOCKED_USERS: return await safe_reply(u.message, "📋 Khaali")
    lines = [f"🚫 {len(BLOCKED_USERS)}"]
    for uid in list(BLOCKED_USERS)[:30]: lines.append(f"• `{uid}`")
    await safe_reply(u.message, "\n".join(lines), parse_mode="Markdown")

# ─── OWNER: RR ────────────────────────────────────────

@dedup
async def rr_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if not u.message.reply_to_message or not u.message.reply_to_message.from_user:
        return await safe_reply(u.message, "❌ Reply karo")
    t = u.message.reply_to_message.from_user
    if t.id == OWNER_ID: return await safe_reply(u.message, "😂 Khud ko nahi")
    if t.is_bot: return await safe_reply(u.message, "❌ Bot ko nahi")
    custom = " ".join(c.args).strip() if c.args else ""
    RR_USERS[str(t.id)] = {"name": t.first_name or "U", "username": t.username or "", "custom": custom}
    await save_rr()
    m = f"@{t.username}" if t.username else t.first_name
    await safe_reply(u.message, f"🔔 RR ON: {m}")


@dedup
async def srr_cmd(u, c):
    if not is_owner(u.effective_user.id): return await safe_reply(u.message, "❌ Owner only")
    if u.message.reply_to_message and u.message.reply_to_message.from_user:
        t = u.message.reply_to_message.from_user; uid = str(t.id)
        if uid in RR_USERS:
            del RR_USERS[uid]; await save_rr()
            return await safe_reply(u.message, f"🛑 RR OFF: {t.first_name}")
        return await safe_reply(u.message, "ℹ️ Nahi hai RR me")
    if c.args and c.args[0].lower() in ("all","clear"):
        n = len(RR_USERS); RR_USERS.clear(); await save_rr()
        return await safe_reply(u.message, f"🛑 Cleared {n}")
    if not RR_USERS: return await safe_reply(u.message, "📋 Khaali")
    lines = [f"🔔 RR ({len(RR_USERS)})"]
    for uid, info in RR_USERS.items():
        u_ = info.get("username",""); n_ = info.get("name","U")
        m = f"@{u_}" if u_ else n_
        lines.append(f"• {m} — `{uid}`")
    await safe_reply(u.message, "\n".join(lines), parse_mode="Markdown")

# ─── INFO ─────────────────────────────────────────────

@dedup
async def info_cmd(u, c):
    m = u.message
    user = (m.reply_to_message.from_user if m.reply_to_message and m.reply_to_message.from_user else u.effective_user)
    await safe_reply(m, f"👤 **{user.first_name}**\n@{user.username or 'N/A'}\nID: `{user.id}`", parse_mode="Markdown")


@dedup
async def aryainfo_cmd(u, c):
    t = None; un = None
    if u.message.reply_to_message and u.message.reply_to_message.from_user:
        t = u.message.reply_to_message.from_user
    elif c.args: un = c.args[0].replace("@","").strip()
    else: return await safe_reply(u.message, "❌ Reply or @user")
    st = await safe_reply(u.message, "🔍...")
    try:
        if un and not t:
            try: t = await c.bot.get_chat(f"@{un}")
            except Exception: pass
        if not t: return await safe_edit(st, "❌ Not found")
        await safe_edit(st, f"🔥 ARYA INFO\nID: `{t.id}`\nName: {getattr(t,'first_name','N/A')}", parse_mode="Markdown")
    except Exception as e: await safe_edit(st, f"❌ {str(e)[:150]}")

# ═══════════════════════════════════════════════════════
# WELCOME
# ═══════════════════════════════════════════════════════

async def on_added(update, ctx):
    try:
        cmu = update.my_chat_member
        if not cmu: return
        ch = cmu.chat
        if ch.type not in ("group","supergroup"): return
        KNOWN_CHATS.add(ch.id); await save_chats()
        ns = cmu.new_chat_member.status; os_ = cmu.old_chat_member.status
        if os_ in ("left","kicked") and ns in ("member","administrator"):
            try:
                await ctx.bot.send_message(ch.id,
                    f"⚡ **ARYA BOT ACTIVE**\n\n`.help` dekho!",
                    parse_mode="Markdown")
            except Exception: pass
        elif os_ == "member" and ns == "administrator":
            try: await ctx.bot.send_message(ch.id, "👑 Admin!")
            except Exception: pass
    except Exception as e: logger.error(f"on_added: {e}")

# ═══════════════════════════════════════════════════════
# COMMAND MAP
# ═══════════════════════════════════════════════════════

CMD_MAP = {
    "start": start_cmd, "help": help_cmd, "ping": ping_cmd, "test": test_cmd,
    "check": check_cmd, "gc": gc_cmd,
    "yt": yt_cmd, "song": song_cmd,
    "logo": logo_cmd, "fem": fem_cmd,
    "custmstk": custmstk_cmd, "cs": custmstk_cmd, "stk": stk_cmd,
    "info": info_cmd, "aryainfo": aryainfo_cmd,
    "roast": roast_cmd, "shayari": shayari_cmd, "joke": joke_cmd,
    "quote": quote_cmd, "qt": qt_cmd, "truth": truth_cmd, "dare": dare_cmd,
    "ship": ship_cmd, "love": ship_cmd, "coin": coin_cmd, "flip": coin_cmd,
    "dice": dice_cmd, "roll": dice_cmd, "8ball": eightball_cmd, "rps": rps_cmd,
    "cat": cat_cmd, "dog": dog_cmd, "wasted": wasted_cmd,
    "mute": mute_cmd, "unmute": unmute_cmd, "prompt": prompt_cmd,
    "lock": lock_cmd, "unlock": unlock_cmd,
    "block": block_cmd, "unblock": unblock_cmd, "blocklist": blocklist_cmd,
    "rr": rr_cmd, "srr": srr_cmd,
    "host1": cmd_host1, "host2": cmd_host2,
    "stopfile": cmd_stopfile, "stophost": cmd_stopfile,
    "hoststat": cmd_hoststat, "hostlog": cmd_hostlog,
    "menufile1": cmd_menufile1, "menufile2": cmd_menufile2,
}

# ═══════════════════════════════════════════════════════
# MASTER HANDLER
# ═══════════════════════════════════════════════════════

async def master_handler(update, ctx):
    try:
        if not update.message: return
        sid = update.effective_user.id

        # RR
        if sid != OWNER_ID and str(sid) in RR_USERS:
            try:
                info = RR_USERS[str(sid)]
                un = info.get("username",""); name = info.get("name","U")
                mention = f"@{un}" if un else name
                custom = info.get("custom","")
                txt = f"{mention} — {custom}" if custom else f"{mention} — {random.choice(RR_REPLIES)}"
                await update.message.reply_text(txt)
            except Exception as e: logger.error(f"RR: {e}")
            return

        # Lock
        if update.effective_chat and update.effective_chat.id in LOCKED_CHATS:
            if sid != OWNER_ID:
                try:
                    m = await ctx.bot.get_chat_member(update.effective_chat.id, sid)
                    if m.status not in ("administrator","creator"):
                        try: await update.message.delete()
                        except Exception: pass
                        return
                except Exception: pass

        if not update.message.text: return
        raw = update.message.text

        if update.effective_chat and update.effective_chat.type in ("group","supergroup"):
            if update.effective_chat.id not in KNOWN_CHATS:
                KNOWN_CHATS.add(update.effective_chat.id); await save_chats()

        text = raw.strip()
        if not text.startswith(COMMAND_PREFIX): return
        body = text[len(COMMAND_PREFIX):]
        if not body: return
        parts = body.split(maxsplit=1)
        cmd = parts[0].lower().strip()
        if "@" in cmd: cmd = cmd.split("@")[0]
        ctx.args = parts[1].split() if len(parts) > 1 and parts[1] else []

        if sid in BLOCKED_USERS: return

        if FORCE_JOIN_ENABLED and FORCE_JOIN_CHAT_ID:
            if sid != OWNER_ID and sid not in VERIFIED_USERS:
                if not await is_joined(update, ctx):
                    await send_join_msg(update, ctx)
                    return

        # HOST OVERRIDE
        if _host_active(update.effective_chat.id) and cmd not in {
            "host1","host2","stopfile","stophost","hoststat","hostlog","menufile1","menufile2"}:
            return

        h = CMD_MAP.get(cmd)
        if h: await h(update, ctx)
    except Exception as e:
        logger.error(f"master: {e}\n{traceback.format_exc()}")

# ═══════════════════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════════════════

async def webhook_handler(request):
    try:
        data = await request.json()
        upd = Update.de_json(data, apps[0].bot)
        await apps[0].process_update(upd)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"wh: {e}")
        return web.Response(text="Err", status=500)


async def health_handler(request): return web.Response(text="ARYA ALIVE ✅")


async def self_ping():
    if not RENDER_EXTERNAL_URL: return
    url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
    print(f"🔄 Self-ping: {url}")
    while True:
        try:
            await asyncio.sleep(14 * 60)
            req = urllib.request.Request(url, headers={"User-Agent": "P/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                logger.info(f"🔄 ping {r.status}")
        except Exception as e: logger.warning(f"ping: {e}")


async def run_webhook():
    if not HAS_AIOHTTP:
        print("❌ aiohttp missing"); return
    wa = web.Application()
    wa.router.add_post(WEBHOOK_PATH, webhook_handler)
    wa.router.add_get("/health", health_handler)
    wa.router.add_get("/", health_handler)
    runner = web.AppRunner(wa); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT); await site.start()
    print(f"✅ Web server on {PORT}")

# ═══════════════════════════════════════════════════════
# BUILD + MAIN
# ═══════════════════════════════════════════════════════

def build_app(token):
    app = Application.builder().token(token).build()
    app.add_handler(ChatMemberHandler(on_added, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(check_join_cb, pattern="^check_join$"))
    app.add_handler(MessageHandler(filters.TEXT, master_handler))
    return app


async def run_all():
    global apps, bots
    failed = []
    print(f"\n🚀 Starting {len(TOKENS)} bot(s)...\n")
    await init_mongo()
    print(f"📋 Groups: {len(KNOWN_CHATS)}")
    print(f"✅ Verified: {len(VERIFIED_USERS)}")
    print(f"🚫 Blocked: {len(BLOCKED_USERS)}")
    print(f"🔔 RR: {len(RR_USERS)}")
    print(f"🔒 Locked: {len(LOCKED_CHATS)}")
    print(f"🎬 ffmpeg: {'✅' if HAS_FFMPEG else '❌'}")
    print(f"💾 Mongo: {'✅' if _use_mongo else '⚠️ mem'}")
    print(f"🔐 Force-join: {'✅' if FORCE_JOIN_ENABLED else '❌'}")
    print(f"🍪 Cookies: {'✅' if _COOKIES_B64 else '❌ (Cobalt fallback ON)'}")
    try: fp = load_fonts(); print(f"✅ Fonts: {len(fp)}")
    except Exception as e: print(f"⚠️ Fonts: {e}")

    for i, tk in enumerate(TOKENS, 1):
        tk = tk.strip()
        if not tk:
            print(f"⚠️ Bot{i}: empty"); failed.append(f"Bot{i}"); continue
        ok = False
        for at in range(3):
            try:
                app = build_app(tk)
                await app.initialize()
                me = await app.bot.get_me()
                if RENDER_EXTERNAL_URL:
                    wu = f"{RENDER_EXTERNAL_URL.rstrip('/')}{WEBHOOK_PATH}"
                    await app.bot.set_webhook(url=wu, drop_pending_updates=True,
                        allowed_updates=["message","edited_message","my_chat_member","chat_member","callback_query"])
                    print(f"✅ Webhook: {wu}")
                else:
                    await app.updater.start_polling(drop_pending_updates=True,
                        allowed_updates=["message","edited_message","my_chat_member","chat_member","callback_query"])
                    print(f"✅ Polling (local)")
                await app.start()
                apps.append(app); bots.append(app.bot); all_bot_instances.append(app.bot)
                print(f"✅ Bot {i}/{len(TOKENS)}: @{me.username}")
                ok = True; break
            except Exception as e:
                logger.warning(f"Bot{i} try{at+1}: {str(e)[:150]}")
                await asyncio.sleep(2)
        if not ok: failed.append(f"Bot{i}")

    print("\n" + "="*55)
    print("🎉 ARYA BOT READY")
    print(f"✅ {len(bots)}/{len(TOKENS)}  ❌ {len(failed)}")
    print(f"👑 Owner: {OWNER_ID}")
    print(f"🌐 Mode: {'WEBHOOK' if RENDER_EXTERNAL_URL else 'POLLING'}")
    print("="*55)
    print("\n🟢 Running...\n")

    if not bots: return

    if RENDER_EXTERNAL_URL:
        await run_webhook()
        asyncio.create_task(self_ping())

    await asyncio.Event().wait()


if __name__ == "__main__":
    try: asyncio.run(run_all())
    except KeyboardInterrupt: print("\n🛑 Stopped")
    except Exception as e:
        print(f"❌ {e}"); traceback.print_exc()