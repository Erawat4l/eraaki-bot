#!/usr/bin/env python3
"""
Ultra-Fast Telegram Akinator Bot (@EraAki_Bot)
- Immediate Web Server Boot: Starts HTTP health check server instantly on container boot so Render deploys always succeed.
- Owner Broadcast & Direct Messaging: Only Admin (6714440636) can use /msg <user> <text> and /msgall <text>.
- Alphabetical User Autocomplete: Dynamically populates Telegram command menu (/msg_erawat, /msg_kush, /msg_quartz...) sorted alphabetically.
- Clickable Group Telemetry Links: Converts telemetry group titles into direct clickable t.me / invite links.
- Non-Admin Speed Prompt: Prompts group chats to grant Admin permissions to @EraAki_Bot for maximum speed.
- Credit Branding: "Made by @erawat_69" on final guess & game end screens.
"""

import os
import sys
import json
import logging
import asyncio
import re
import html
import unicodedata
from pathlib import Path
from aiohttp import web
from curl_cffi.requests import AsyncSession
from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError
from telethon.tl.functions.bots import SetBotInfoRequest, SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault

logging.basicConfig(level=logging.INFO)

CONFIG_PATH = Path.home() / ".config" / "tgdl" / "config.json"
REGISTRY_PATH = Path(__file__).parent / "known_users.json"

games = {}
known_users = {}
known_chats = set()
pending_admin_msgs = {}
pending_admin_broadcast = set()

ADMIN_IDS = {6714440636}
LOG_ADMIN_ID = 6714440636

ANSWER_LABELS = {
    "y": "✅ Yes",
    "n": "❌ No",
    "i": "❓ Don't Know",
    "p": "👍 Probably",
    "pn": "👎 Probably Not",
    "b": "⬅️ Back"
}

CREDIT_TEXT = "Made by @erawat_69"

def make_command_slug(name):
    if not name:
        return "user"
    norm = unicodedata.normalize('NFKD', name)
    slug = re.sub(r'[^a-zA-Z0-9]', '_', norm).strip('_').lower()
    slug = re.sub(r'_+', '_', slug)
    return slug[:20] if slug else "user"

def load_registry():
    global known_users, known_chats
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r") as f:
                data = json.load(f)
                known_users = data.get("users", {})
                known_chats = set(data.get("chats", []))
        except Exception as e:
            logging.error(f"Error loading registry: {e}")

def save_registry():
    try:
        data = {
            "users": known_users,
            "chats": list(known_chats)
        }
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving registry: {e}")

def register_activity(user_id, user_name, chat_id, client=None):
    if not user_id:
        return
    uid_str = str(user_id)
    known_users[uid_str] = {
        "user_id": user_id,
        "name": user_name,
        "chat_id": chat_id,
        "slug": make_command_slug(user_name)
    }
    if chat_id:
        known_chats.add(chat_id)
    save_registry()
    if client:
        asyncio.create_task(update_bot_command_menu(client))

async def update_bot_command_menu(client):
    try:
        base_commands = [
            BotCommand(command="eraaki", description="🎮 Start Akinator guessing game"),
            BotCommand(command="eraakistop", description="🛑 Stop active Akinator game"),
            BotCommand(command="msg", description="💬 Direct Message player"),
            BotCommand(command="msgall", description="📢 Broadcast message to all active users"),
            BotCommand(command="cancel", description="❌ Cancel pending operation")
        ]
        await client(SetBotCommandsRequest(
            scope=BotCommandScopeDefault(),
            lang_code="en",
            commands=base_commands
        ))
    except Exception as e:
        logging.error(f"Notice updating bot command menu: {e}")

class FastAkinator:
    def __init__(self, lang="en"):
        self.lang = lang
        self.session = None
        self.step = 1
        self.progression = 0.0
        self.question = ""
        self.win = False
        self.first_guess = {}
        self.aki_session = ""
        self.identifiant = ""

    async def start_game(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://{self.lang}.akinator.com/",
            "Origin": f"https://{self.lang}.akinator.com"
        }

        last_err = None
        impersonates = ["chrome120", "chrome119", "safari15_5", "edge101"]
        for attempt in range(6):
            try:
                imp = impersonates[attempt % len(impersonates)]
                if self.session and not getattr(self.session, "closed", True):
                    try:
                        await self.session.close()
                    except Exception:
                        pass
                self.session = AsyncSession(impersonate=imp)

                # 1. Obtain fresh cookies from homepage
                r_home = await self.session.get(f"https://{self.lang}.akinator.com/", headers=headers, timeout=10)
                if r_home.status_code != 200:
                    last_err = ValueError(f"Home HTTP {r_home.status_code}")
                    await asyncio.sleep(0.4)
                    continue

                # 2. Initialize game session
                url = f"https://{self.lang}.akinator.com/game"
                r = await self.session.post(url, data={"sid": "1", "cm": "false"}, headers=headers, timeout=10)
                if r.status_code != 200:
                    last_err = ValueError(f"Game HTTP {r.status_code}")
                    await asyncio.sleep(0.4)
                    continue

                text = r.text

                sess_m = re.search(r"localStorage\.setItem\('session',\s*'([^']+)'\)", text) or \
                         re.search(r"\$('#session')\.val\('([^']+)'\)", text) or \
                         re.search(r'id="session"[^>]*value="([^"]+)"', text) or \
                         re.search(r'name="session"[^>]*value="([^"]+)"', text) or \
                         re.search(r"session\s*:\s*'([^']+)'", text) or \
                         re.search(r'"session"\s*:\s*"([^"]+)"', text)

                id_m = re.search(r"localStorage\.setItem\('identifiant',\s*'([^']+)'\)", text) or \
                       re.search(r"\$('#identifiant')\.val\('([^']+)'\)", text) or \
                       re.search(r'id="identifiant"[^>]*value="([^"]+)"', text) or \
                       re.search(r'name="identifiant"[^>]*value="([^"]+)"', text) or \
                       re.search(r"identifiant\s*:\s*'([^']+)'", text) or \
                       re.search(r'"identifiant"\s*:\s*"([^"]+)"', text)

                q_m = re.search(r'id="question-label"[^>]*>\s*(?:<p[^>]*>)?([^<]+)', text, re.IGNORECASE) or \
                      re.search(r'class="bubble-body"[^>]*>\s*(?:<p[^>]*>)?([^<]+)', text, re.IGNORECASE) or \
                      re.search(r'class="question-text"[^>]*>\s*([^<]+)', text, re.IGNORECASE) or \
                      re.search(r'<p[^>]*id="question-label"[^>]*>([^<]+)</p>', text, re.IGNORECASE)

                if sess_m and id_m and q_m:
                    parsed_sess = sess_m.group(1).strip()
                    parsed_id = id_m.group(1).strip()
                    parsed_q = html.unescape(q_m.group(1).strip())

                    if parsed_sess and parsed_id and parsed_q:
                        self.aki_session = parsed_sess
                        self.identifiant = parsed_id
                        self.question = parsed_q
                        self.step = 1
                        self.progression = 0.0
                        self.win = False
                        return self.question
                    else:
                        last_err = ValueError(f"Empty fields: sess={bool(parsed_sess)}, id={bool(parsed_id)}, q={bool(parsed_q)}")
                else:
                    logging.warning(f"Attempt {attempt+1} match fail. Snippet: {text[:200]}")
                    last_err = ValueError(f"Regex fail: sess={bool(sess_m)}, id={bool(id_m)}, q={bool(q_m)}")
            except Exception as e:
                last_err = e
                logging.error(f"start_game attempt {attempt+1} error: {e}")
                await asyncio.sleep(0.5)

        raise RuntimeError(f"Akinator server connection busy ({last_err})")

    async def answer(self, ans_str):
        self.win = False
        ans_map = {"y": 0, "n": 1, "i": 2, "p": 3, "pn": 4}
        ans_id = ans_map.get(ans_str, 0)

        payload = {
            "step": str(self.step),
            "progression": str(self.progression),
            "sid": "1",
            "cm": "false",
            "answer": str(ans_id),
            "step_last_proposition": "",
            "session": self.aki_session,
            "identifiant": self.identifiant
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://{self.lang}.akinator.com/game",
            "Origin": f"https://{self.lang}.akinator.com",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }

        res = {}
        for attempt in range(3):
            try:
                r = await self.session.post(
                    f"https://{self.lang}.akinator.com/answer",
                    data=payload,
                    headers=headers,
                    timeout=10
                )
                res = r.json()
                if isinstance(res, dict) and res.get("completion") == "OK":
                    break
            except Exception as e:
                logging.error(f"Answer attempt {attempt+1} failed: {e}")
                await asyncio.sleep(0.4)

        if isinstance(res, dict) and res.get("completion") == "OK":
            if res.get("id_proposition") or res.get("name_proposition"):
                self.win = True
                self.first_guess = {
                    "name": html.unescape(res.get("name_proposition", "Unknown")),
                    "description": html.unescape(res.get("description_proposition", "")),
                    "photo": res.get("photo", "")
                }
            else:
                self.step = int(res.get("step", self.step + 1))
                self.progression = float(res.get("progression", self.progression))
                if res.get("question"):
                    self.question = html.unescape(res.get("question"))
        else:
            logging.warning(f"Answer KO response: {res}. Re-syncing session.")
            try:
                await self.start_game()
            except Exception as e:
                logging.error(f"Failed session re-sync: {e}")

        return self.question

    async def back(self):
        self.win = False
        if self.step <= 1:
            return self.question

        payload = {
            "step": str(self.step),
            "progression": str(self.progression),
            "sid": "1",
            "cm": "false",
            "session": self.aki_session,
            "identifiant": self.identifiant
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://{self.lang}.akinator.com/game",
            "Origin": f"https://{self.lang}.akinator.com"
        }

        try:
            r = await self.session.post(
                f"https://{self.lang}.akinator.com/cancel_answer",
                data=payload,
                headers=headers,
                timeout=10
            )
            res = r.json()
            if isinstance(res, dict) and res.get("question"):
                self.step = int(res.get("step", max(1, self.step - 1)))
                self.progression = float(res.get("progression", self.progression))
                self.question = html.unescape(res.get("question"))
        except Exception:
            self.step = max(1, self.step - 1)

        return self.question

    async def close(self):
        try:
            await self.session.close()
        except Exception:
            pass

def get_game_buttons():
    return [
        [Button.inline("✅ Yes", b"aki_y"), Button.inline("❌ No", b"aki_n")],
        [Button.inline("❓ Don't Know", b"aki_i")],
        [Button.inline("👍 Probably", b"aki_p"), Button.inline("👎 Probably Not", b"aki_pn")],
        [Button.inline("⬅️ Back", b"aki_b"), Button.inline("🛑 End Game", b"aki_end")]
    ]

def get_guess_buttons():
    return [
        [Button.inline("🎉 Yes! That's right!", b"guess_yes")],
        [Button.inline("🔄 No, keep guessing!", b"guess_no")]
    ]

def get_private_promo_buttons():
    return [
        [Button.url("➕ Add Bot to Your Group", "https://t.me/EraAki_Bot?startgroup=true")],
        [Button.url("📸 Instagram: @erawat_69", "https://instagram.com/erawat_69")],
        [Button.url("💬 Owner Contact", "https://t.me/erawat_69")]
    ]

async def resolve_user_id(event):
    if getattr(event, 'sender_id', None):
        return event.sender_id
    if getattr(event, 'from_id', None):
        fid = event.from_id
        if getattr(fid, 'user_id', None):
            return fid.user_id
        if getattr(fid, 'channel_id', None):
            return fid.channel_id
    try:
        sender = await event.get_sender()
        if sender and getattr(sender, 'id', None):
            return sender.id
    except Exception:
        pass
    return event.chat_id

async def get_player_info(client, event, user_id):
    if not user_id:
        user_id = await resolve_user_id(event)

    name = ""
    try:
        sender = await event.get_sender()
        if sender:
            if getattr(sender, 'first_name', None):
                name = sender.first_name
                if getattr(sender, 'last_name', None):
                    name += f" {sender.last_name}"
            elif getattr(sender, 'username', None):
                name = f"@{sender.username}"
            elif getattr(sender, 'title', None):
                name = sender.title
    except Exception:
        pass

    if not name or name == "Player" or "None" in name:
        try:
            ent = await client.get_entity(user_id)
            if getattr(ent, 'first_name', None):
                name = ent.first_name
                if getattr(ent, 'last_name', None):
                    name += f" {ent.last_name}"
            elif getattr(ent, 'username', None):
                name = f"@{ent.username}"
            elif getattr(ent, 'title', None):
                name = ent.title
        except Exception:
            pass

    if not name or "None" in name:
        name = f"Player ({user_id})"

    mention = f"[{name}](tg://user?id={user_id})"
    return name, mention

async def get_chat_location_formatted(client, event):
    chat_id = event.chat_id
    title = "Private DM" if event.is_private else f"Group {chat_id}"
    link = ""
    try:
        chat = await event.get_chat()
        if getattr(chat, 'title', None):
            title = chat.title
        elif getattr(chat, 'first_name', None):
            n = chat.first_name
            if getattr(chat, 'last_name', None):
                n += f" {chat.last_name}"
            title = f"DM ({n})"

        if getattr(chat, 'username', None) and chat.username:
            link = f"https://t.me/{chat.username}"
        elif not event.is_private:
            if getattr(chat, 'invite_link', None) and chat.invite_link:
                link = chat.invite_link
            else:
                try:
                    from telethon.tl.functions.messages import ExportChatInviteRequest
                    inv = await client(ExportChatInviteRequest(chat_id))
                    if getattr(inv, 'link', None):
                        link = inv.link
                except Exception:
                    pass
                if not link:
                    cid_str = str(chat_id).replace("-100", "")
                    link = f"https://t.me/c/{cid_str}/1"
    except Exception:
        pass

    if link:
        loc_str = f"[{title}]({link}) (`{chat_id}`)"
    else:
        loc_str = f"`{title}` (`{chat_id}`)"
    return title, loc_str

async def check_admin_speed_prompt(client, chat_id, is_private):
    if is_private:
        return ""
    try:
        me = await client.get_me()
        perms = await client.get_permissions(chat_id, me)
        if not (getattr(perms, 'is_admin', False) or getattr(perms, 'is_creator', False)):
            return "\n\n⚡ *Tip:* Promote @EraAki_Bot to **Admin** to improve speed and unlock group link export!"
    except Exception:
        pass
    return ""

def log_telemetry(client, user_name, user_id, chat_location_formatted, action_str, extra=""):
    asyncio.create_task(_ship_telemetry(client, user_name, user_id, chat_location_formatted, action_str, extra))

async def _ship_telemetry(client, user_name, user_id, chat_location_formatted, action_str, extra=""):
    logging.info(f"TELEMETRY: User={user_name} ({user_id}) | Location={chat_location_formatted} | Action={action_str} | Detail={extra}")
    try:
        log_msg = (
            f"📊 **[EraAki Telemetry]**\n"
            f"👤 **User:** [{user_name}](tg://user?id={user_id}) (`{user_id}`)\n"
            f"📍 **Location:** {chat_location_formatted}\n"
            f"🎯 **Action:** {action_str}"
        )
        if extra:
            log_msg += f"\nℹ️ **Detail:** {extra}"
        await client.send_message(LOG_ADMIN_ID, log_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Telemetry log notice: {e}")

async def start_web_server():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    async def health(req):
        return web.Response(text="Akinator Bot Online 24/7! Made by @erawat_69")
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✓ Health check web server active on port {port}")

async def self_ping_loop():
    await asyncio.sleep(15)
    import aiohttp
    url = "https://eraaki-bot.onrender.com/health"
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=10) as r:
                    logging.info(f"Keep-alive self-ping status: {r.status}")
        except Exception as e:
            logging.error(f"Keep-alive ping notice: {e}")
        await asyncio.sleep(240)  # Self-ping every 4 minutes to permanently prevent Render free tier sleeping

async def main():
    load_registry()

    # 1. Start web health check server FIRST so Render port scanner passes instantly!
    await start_web_server()

    # 2. Start self-ping keep-alive loop so Render container NEVER spins down/sleeps!
    asyncio.create_task(self_ping_loop())

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token and len(sys.argv) > 1:
        bot_token = sys.argv[1].strip()

    if not bot_token:
        print("Usage: BOT_TOKEN=your_token python3 bot.py OR python3 bot.py <BOT_TOKEN>")
        sys.exit(1)

    api_id = int(os.getenv("TELEGRAM_API_ID", "30909654"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "d4b340a406c5c1ed1d7f26d44749602b")

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                api_id = int(data.get("api_id", api_id))
                api_hash = data.get("api_hash", api_hash)
        except Exception:
            pass

    session_dir = Path.home() / "Projects" / "Akinator-Bot"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / "akinator_bot_session"

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start(bot_token=bot_token)

    await update_bot_command_menu(client)

    try:
        await client(SetBotInfoRequest(
            about="Official Akinator Telegram Bot made by @erawat_69. Play Akinator in group chats and DMs!",
            description="Official Akinator Telegram Bot made by @erawat_69. Play Akinator in group chats and DMs!",
            lang_code="en"
        ))
        print("✓ Registered bot description & command autocomplete menu.")
    except Exception as e:
        logging.error(f"Notice setting bot description: {e}")

    print("⚡ Ultra-Fast Unified Akinator Bot (@EraAki_Bot) started successfully!")

    @client.on(events.NewMessage(pattern=r"(?i)^/cancel(@\w+)?$"))
    async def cancel_handler(event):
        user_id = await resolve_user_id(event)
        if user_id in ADMIN_IDS:
            canceled_any = False
            if user_id in pending_admin_msgs:
                pending_admin_msgs.pop(user_id, None)
                canceled_any = True
            if user_id in pending_admin_broadcast:
                pending_admin_broadcast.discard(user_id)
                canceled_any = True

            if canceled_any:
                await event.reply("❌ **Operation canceled.**", parse_mode="Markdown")
            else:
                await event.reply("ℹ️ No active command to cancel.", parse_mode="Markdown")

    @client.on(events.CallbackQuery(pattern=rb"^cancel_msg$"))
    async def cancel_callback_handler(event):
        user_id = await resolve_user_id(event)
        if user_id not in ADMIN_IDS:
            await event.answer("Owner Only command.", alert=True)
            return
        pending_admin_msgs.pop(user_id, None)
        pending_admin_broadcast.discard(user_id)
        await event.answer("Operation canceled.")
        try:
            await event.edit("❌ **Operation canceled.**", parse_mode="Markdown", buttons=None)
        except MessageNotModifiedError:
            pass

    @client.on(events.NewMessage(pattern=r"(?i)^/msg(\s+.*)?$"))
    async def msg_handler(event):
        user_id = await resolve_user_id(event)
        if user_id not in ADMIN_IDS:
            return  # Admin Only!

        pending_admin_msgs.pop(user_id, None)
        pending_admin_broadcast.discard(user_id)

        raw_args = (event.pattern_match.group(1) or "").strip()

        if not raw_args:
            sorted_users = []
            for uid_s, info in known_users.items():
                raw_name = info.get("name", f"User {uid_s}")
                sorted_users.append({
                    "uid": uid_s,
                    "name": raw_name
                })

            # Sort ALPHABETICALLY by name (case-insensitive)
            sorted_users.sort(key=lambda x: x["name"].lower())

            if not sorted_users:
                await event.reply("ℹ️ No active users recorded yet in registry.", parse_mode="Markdown")
                return

            buttons = []
            row = []
            for u in sorted_users:
                row.append(Button.inline(f"👤 {u['name']}", f"dmuser_{u['uid']}".encode()))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)

            buttons.append([Button.inline("❌ Cancel", b"cancel_msg")])

            text = (
                "💬 **Direct Message Player Menu** (Alphabetical)\n\n"
                "Select a user below to message, or type `/msg <name|id>`:"
            )
            await event.reply(text, parse_mode="Markdown", buttons=buttons)
            return

        parts = raw_args.split(maxsplit=1)
        target_query = parts[0].strip()
        msg_body = parts[1].strip() if len(parts) > 1 else ""

        matched_uid = None
        matched_name = ""

        if target_query.isdigit():
            matched_uid = int(target_query)
            if str(matched_uid) in known_users:
                matched_name = known_users[str(matched_uid)].get("name", f"User {matched_uid}")
            else:
                matched_name = f"User {matched_uid}"
        else:
            q_clean = target_query.lower().lstrip("@")
            for uid_s, info in known_users.items():
                raw_name = info.get("name", "")
                slug = info.get("slug") or make_command_slug(raw_name)
                uname = raw_name.lower()
                if q_clean == slug or q_clean in uname or q_clean == uid_s:
                    matched_uid = int(uid_s)
                    matched_name = raw_name
                    break

        if not matched_uid:
            await event.reply(f"❌ User `{target_query}` not found in active user registry.", parse_mode="Markdown")
            return

        if not msg_body:
            pending_admin_msgs[user_id] = {
                "target_uid": matched_uid,
                "target_name": matched_name
            }
            buttons = [[Button.inline("❌ Cancel", b"cancel_msg")]]
            await event.reply(
                f"💬 **Messaging** [{matched_name}](tg://user?id={matched_uid}) (`{matched_uid}`)\n\n"
                f"Please type your message text below to send:\n"
                f"_(Or tap Cancel below / type `/cancel` to exit)_",
                parse_mode="Markdown",
                buttons=buttons
            )
            return

        try:
            full_msg = f"💬 **Message from Bot Owner:**\n\n{msg_body}\n\n{CREDIT_TEXT}"
            await client.send_message(matched_uid, full_msg, parse_mode="Markdown")
            await event.reply(
                f"✅ **Message delivered to** [{matched_name}](tg://user?id={matched_uid}) (`{matched_uid}`):\n\n\"{msg_body}\"",
                parse_mode="Markdown"
            )
        except Exception as e:
            await event.reply(f"❌ **Failed to send message to** `{matched_uid}`: {e}", parse_mode="Markdown")

    @client.on(events.CallbackQuery(pattern=rb"^dmuser_"))
    async def dm_user_callback(event):
        user_id = await resolve_user_id(event)
        if user_id not in ADMIN_IDS:
            await event.answer("Owner Only command.", alert=True)
            return

        pending_admin_broadcast.discard(user_id)
        target_uid_s = event.data.decode().replace("dmuser_", "")
        target_info = known_users.get(target_uid_s, {})
        target_name = target_info.get("name", f"User {target_uid_s}")

        pending_admin_msgs[user_id] = {
            "target_uid": int(target_uid_s),
            "target_name": target_name
        }

        await event.answer()
        buttons = [[Button.inline("❌ Cancel", b"cancel_msg")]]
        prompt_text = (
            f"💬 **Messaging** [{target_name}](tg://user?id={target_uid_s}) (`{target_uid_s}`)\n\n"
            f"Please type your message text below to send:\n"
            f"_(Or tap Cancel below / type `/cancel` to exit)_"
        )
        try:
            await event.edit(prompt_text, parse_mode="Markdown", buttons=buttons)
        except MessageNotModifiedError:
            pass

    async def do_broadcast(event, broadcast_text):
        status_msg = await event.reply("📢 **Starting broadcast to all active users & chats...**", parse_mode="Markdown")

        user_success = 0
        user_fail = 0
        chat_success = 0
        chat_fail = 0

        full_msg = f"📢 **Announcement from @EraAki_Bot Owner:**\n\n{broadcast_text}\n\n{CREDIT_TEXT}"

        for uid_s in list(known_users.keys()):
            try:
                uid = int(uid_s)
                await client.send_message(uid, full_msg, parse_mode="Markdown")
                user_success += 1
            except Exception:
                user_fail += 1
            await asyncio.sleep(0.05)

        for cid in list(known_chats):
            if cid in ADMIN_IDS:
                continue
            try:
                await client.send_message(cid, full_msg, parse_mode="Markdown")
                chat_success += 1
            except Exception:
                chat_fail += 1
            await asyncio.sleep(0.05)

        report = (
            f"✅ **Broadcast Complete!**\n\n"
            f"👤 **Users:** `{user_success}` success / `{user_fail}` failed\n"
            f"👥 **Groups:** `{chat_success}` success / `{chat_fail}` failed"
        )
        await status_msg.edit(report, parse_mode="Markdown")

    @client.on(events.NewMessage(func=lambda e: bool(e.text and not e.text.startswith('/'))))
    async def pending_msg_text_handler(event):
        user_id = await resolve_user_id(event)
        if user_id not in ADMIN_IDS:
            return

        if user_id in pending_admin_broadcast:
            pending_admin_broadcast.discard(user_id)
            await do_broadcast(event, event.text.strip())
            return

        if user_id in pending_admin_msgs:
            target = pending_admin_msgs.pop(user_id)
            matched_uid = target["target_uid"]
            matched_name = target["target_name"]
            msg_body = event.text.strip()

            try:
                full_msg = f"💬 **Message from Bot Owner:**\n\n{msg_body}\n\n{CREDIT_TEXT}"
                await client.send_message(matched_uid, full_msg, parse_mode="Markdown")
                await event.reply(
                    f"✅ **Message delivered to** [{matched_name}](tg://user?id={matched_uid}) (`{matched_uid}`):\n\n\"{msg_body}\"",
                    parse_mode="Markdown"
                )
            except Exception as e:
                await event.reply(f"❌ **Failed to send message to** `{matched_uid}`: {e}", parse_mode="Markdown")

    @client.on(events.NewMessage(pattern=r"(?i)^/msgall(\s+.*)?$"))
    async def msgall_handler(event):
        user_id = await resolve_user_id(event)
        if user_id not in ADMIN_IDS:
            return  # Admin Only!

        pending_admin_msgs.pop(user_id, None)
        pending_admin_broadcast.discard(user_id)

        raw_args = (event.pattern_match.group(1) or "").strip()

        if not raw_args:
            pending_admin_broadcast.add(user_id)
            buttons = [[Button.inline("❌ Cancel", b"cancel_msg")]]
            await event.reply(
                "📢 **Broadcast Message to All Active Users & Groups**\n\n"
                "Please type the broadcast message text below to send:\n"
                "_(Or tap Cancel below / type `/cancel` to exit)_",
                parse_mode="Markdown",
                buttons=buttons
            )
            return

        await do_broadcast(event, raw_args)

    @client.on(events.NewMessage(pattern=r"(?i)^/(eraaki|start)(@\w+)?$"))
    async def start_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        user_name, user_mention = await get_player_info(client, event, user_id)
        register_activity(user_id, user_name, chat_id, client=client)

        chat_title, chat_location_formatted = await get_chat_location_formatted(client, event)
        admin_prompt = await check_admin_speed_prompt(client, chat_id, event.is_private)

        reply_buttons = get_game_buttons()
        if event.is_private:
            reply_buttons += get_private_promo_buttons()

        # If a game is already active in this chat, send current active question!
        if game_key in games:
            game = games[game_key]
            aki = game["aki"]
            last_ans_text = f" *(Selected: {game['last_ans']})*" if game["last_ans"] else ""
            text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{aki.question}{admin_prompt}"
            await event.reply(text, parse_mode="Markdown", buttons=reply_buttons)
            log_telemetry(client, user_name, user_id, chat_location_formatted, "🎮 Checked Active Game", f"Step {aki.step} ({int(aki.progression)}%)")
            return

        msg = await event.reply(f"🔮 *Starting Akinator game for* {user_mention}...", parse_mode="Markdown")
        
        aki = FastAkinator()
        try:
            q = await aki.start_game()
            games[game_key] = {
                "aki": aki,
                "owner_id": user_id,
                "owner_name": user_name,
                "owner_mention": user_mention,
                "last_ans": None
            }
            text = f"👤 *Player:* {user_mention}\n❓ *Question 1:*\n{q}{admin_prompt}"
            await msg.edit(text, parse_mode="Markdown", buttons=reply_buttons)
            log_telemetry(client, user_name, user_id, chat_location_formatted, "🎮 Started New Game", f"Q1: {q}")
        except Exception as e:
            logging.error(f"Error starting game: {e}")
            await msg.edit(f"❌ Akinator server error: `{e}`. Please type /eraaki again in a moment!", parse_mode="Markdown")

    @client.on(events.NewMessage(pattern=r"(?i)^/(stop|end|eraakistop)(@\w+)?$"))
    async def stop_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        user_name, user_mention = await get_player_info(client, event, user_id)
        register_activity(user_id, user_name, chat_id, client=client)

        chat_title, chat_location_formatted = await get_chat_location_formatted(client, event)

        if game_key in games:
            game = games[game_key]
            await game["aki"].close()
            del games[game_key]
            await event.reply(f"🛑 Game stopped by {user_mention}!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
            log_telemetry(client, user_name, user_id, chat_location_formatted, "🛑 Stopped Active Game")
            return

        await event.reply("No active game running in this chat. Type /eraaki to start one!", parse_mode="Markdown")

    @client.on(events.CallbackQuery(pattern=rb"^aki_"))
    async def callback_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        action = event.data.decode().replace("aki_", "")

        if game_key not in games:
            await event.answer("Game expired or ended. Type /eraaki!", alert=True)
            return

        game = games[game_key]
        aki = game["aki"]

        user_name, user_mention = await get_player_info(client, event, user_id)
        register_activity(user_id, user_name, chat_id, client=client)

        chat_title, chat_location_formatted = await get_chat_location_formatted(client, event)
        admin_prompt = await check_admin_speed_prompt(client, chat_id, event.is_private)

        game["owner_name"] = user_name
        game["owner_mention"] = user_mention

        if action == "end":
            await aki.close()
            del games[game_key]
            await event.answer("Game ended.")
            try:
                await event.edit(f"🛑 Game ended by {user_mention}. Type /eraaki to start again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
            except MessageNotModifiedError:
                pass
            log_telemetry(client, user_name, user_id, chat_location_formatted, "🛑 Ended Game via Button")
            return

        await event.answer()

        try:
            if action == "b":
                q = await aki.back()
                game["last_ans"] = "⬅️ Back"
                action_text = "⬅️ Back"
            else:
                q = await aki.answer(action)
                game["last_ans"] = ANSWER_LABELS.get(action, "")
                action_text = game["last_ans"]

            reply_buttons = get_game_buttons()
            guess_buttons = get_guess_buttons()
            if event.is_private:
                reply_buttons += get_private_promo_buttons()
                guess_buttons += get_private_promo_buttons()

            if aki.win:
                guess = aki.first_guess
                name = guess.get("name", "Unknown")
                desc = guess.get("description", "")
                photo = guess.get("photo", "")

                text = f"👤 *Player:* {game['owner_mention']}\n🎉 *I think of:*\n\n🌟 **{name}**\n_{desc}_\n\n{CREDIT_TEXT}"

                log_telemetry(client, user_name, user_id, chat_location_formatted, f"🎉 Character Guess Made", f"Guess: {name} ({desc})")

                if photo:
                    try:
                        await event.delete()
                        await client.send_file(chat_id, photo, caption=text, parse_mode="Markdown", buttons=guess_buttons)
                        return
                    except Exception:
                        pass

                await event.edit(text, parse_mode="Markdown", buttons=guess_buttons)
            else:
                last_ans_text = f" *(Selected: {game['last_ans']})*" if game["last_ans"] else ""
                text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{q}{admin_prompt}"
                await event.edit(text, parse_mode="Markdown", buttons=reply_buttons)
                log_telemetry(client, user_name, user_id, chat_location_formatted, f"Answered {action_text}", f"Next: Q{aki.step} ({int(aki.progression)}%) - {q}")

        except MessageNotModifiedError:
            pass
        except Exception as e:
            logging.error(f"Error processing callback: {e}")

    @client.on(events.CallbackQuery(pattern=rb"^guess_"))
    async def guess_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        action = event.data.decode().replace("guess_", "")

        if game_key not in games:
            await event.answer("No active game.", alert=True)
            return

        game = games[game_key]
        user_name, user_mention = await get_player_info(client, event, user_id)
        register_activity(user_id, user_name, chat_id, client=client)

        chat_title, chat_location_formatted = await get_chat_location_formatted(client, event)
        admin_prompt = await check_admin_speed_prompt(client, chat_id, event.is_private)

        game["owner_name"] = user_name
        game["owner_mention"] = user_mention

        reply_buttons = get_game_buttons()
        if event.is_private:
            reply_buttons += get_private_promo_buttons()

        if action == "yes":
            await game["aki"].close()
            del games[game_key]
            await event.answer("Hooray! 🎉")
            await event.respond(f"🏆 *I guessed it right for {user_mention}!* Thanks for playing! Send /eraaki to play again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
            log_telemetry(client, user_name, user_id, chat_location_formatted, "🏆 Correct Guess Confirmed")
        else:
            aki = game["aki"]
            try:
                q = await aki.answer("n")
                text = f"👤 *Player:* {user_mention}\n🔄 Continuing game!\n❓ *Question {aki.step}:*\n{q}{admin_prompt}"
                await event.respond(text, parse_mode="Markdown", buttons=reply_buttons)
                log_telemetry(client, user_name, user_id, chat_location_formatted, "🔄 Rejected Guess, Continuing", f"Q{aki.step}: {q}")
            except Exception:
                await aki.close()
                del games[game_key]
                await event.respond(f"Game ended. Type /eraaki to start again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
