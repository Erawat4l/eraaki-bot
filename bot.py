#!/usr/bin/env python3
"""
Ultra-Fast Telegram Akinator Bot (@EraAki_Bot)
- Immediate Web Server Boot: Starts HTTP health check server instantly on container boot so Render deploys always succeed.
- Non-Interactive Startup Safety: Validates BOT_TOKEN environment variable to prevent console hanging on cloud hosts.
- Robust Entity Resolution: Guarantees full names and mentions for all group chat players (e.g. QUARTZ, Kush).
- Strict Token Validation: Validates session, identifiant, and initial question extraction so broken sessions are never created.
- Non-Blocking Background Telemetry Logging: Ships user choices and locations instantly without slowing button clicks.
- Credit Branding: "Made by @erawat_69" on final guess & game end screens.
"""

import os
import sys
import json
import logging
import asyncio
import re
import html
from pathlib import Path
from aiohttp import web
from curl_cffi.requests import AsyncSession
from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError
from telethon.tl.functions.bots import SetBotInfoRequest, SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault

logging.basicConfig(level=logging.INFO)

CONFIG_PATH = Path.home() / ".config" / "tgdl" / "config.json"
games = {}

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
        for attempt in range(4):
            try:
                if self.session and not getattr(self.session, "closed", True):
                    try:
                        await self.session.close()
                    except Exception:
                        pass
                self.session = AsyncSession(impersonate="chrome120")

                # 1. Obtain fresh cookies from homepage
                await self.session.get(f"https://{self.lang}.akinator.com/", headers=headers, timeout=10)

                # 2. Initialize game session
                url = f"https://{self.lang}.akinator.com/game"
                r = await self.session.post(url, data={"sid": "1", "cm": "false"}, headers=headers, timeout=10)
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
                    last_err = ValueError(f"Regex match failed: sess={bool(sess_m)}, id={bool(id_m)}, q={bool(q_m)}")
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

async def get_chat_title(event):
    try:
        chat = await event.get_chat()
        if getattr(chat, 'title', None):
            return chat.title
        elif getattr(chat, 'first_name', None):
            n = chat.first_name
            if getattr(chat, 'last_name', None):
                n += f" {chat.last_name}"
            return f"DM ({n})"
    except Exception:
        pass
    return "Private DM" if event.is_private else f"Group {event.chat_id}"

def log_telemetry(client, user_name, user_id, chat_title, chat_id, action_str, extra=""):
    asyncio.create_task(_ship_telemetry(client, user_name, user_id, chat_title, chat_id, action_str, extra))

async def _ship_telemetry(client, user_name, user_id, chat_title, chat_id, action_str, extra=""):
    logging.info(f"TELEMETRY: User={user_name} ({user_id}) | Location={chat_title} ({chat_id}) | Action={action_str} | Detail={extra}")
    try:
        log_msg = (
            f"📊 **[EraAki Telemetry]**\n"
            f"👤 **User:** [{user_name}](tg://user?id={user_id}) (`{user_id}`)\n"
            f"📍 **Location:** `{chat_title}` (`{chat_id}`)\n"
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

async def main():
    # 1. Start web health check server FIRST so Render port scanner passes instantly!
    await start_web_server()

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

    try:
        await client(SetBotCommandsRequest(
            scope=BotCommandScopeDefault(),
            lang_code="en",
            commands=[
                BotCommand(command="eraaki", description="🎮 Start Akinator guessing game"),
                BotCommand(command="eraakistop", description="🛑 Stop active Akinator game")
            ]
        ))
        await client(SetBotInfoRequest(
            about="Official Akinator Telegram Bot made by @erawat_69. Play Akinator in group chats and DMs!",
            description="Official Akinator Telegram Bot made by @erawat_69. Play Akinator in group chats and DMs!",
            lang_code="en"
        ))
        print("✓ Registered bot description & command autocomplete menu.")
    except Exception as e:
        logging.error(f"Notice setting bot description: {e}")

    print("⚡ Ultra-Fast Unified Akinator Bot (@EraAki_Bot) started successfully!")

    @client.on(events.NewMessage(pattern=r"(?i)^/(eraaki|start)(@\w+)?$"))
    async def start_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        user_name, user_mention = await get_player_info(client, event, user_id)
        chat_title = await get_chat_title(event)

        reply_buttons = get_game_buttons()
        if event.is_private:
            reply_buttons += get_private_promo_buttons()

        # If a game is already active in this chat, send current active question!
        if game_key in games:
            game = games[game_key]
            aki = game["aki"]
            last_ans_text = f" *(Selected: {game['last_ans']})*" if game["last_ans"] else ""
            text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{aki.question}"
            await event.reply(text, parse_mode="Markdown", buttons=reply_buttons)
            log_telemetry(client, user_name, user_id, chat_title, chat_id, "🎮 Checked Active Game", f"Step {aki.step} ({int(aki.progression)}%)")
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
            text = f"👤 *Player:* {user_mention}\n❓ *Question 1:*\n{q}"
            await msg.edit(text, parse_mode="Markdown", buttons=reply_buttons)
            log_telemetry(client, user_name, user_id, chat_title, chat_id, "🎮 Started New Game", f"Q1: {q}")
        except Exception as e:
            logging.error(f"Error starting game: {e}")
            await msg.edit(f"❌ Akinator servers are currently busy. Please type /eraaki again in a moment!", parse_mode="Markdown")

    @client.on(events.NewMessage(pattern=r"(?i)^/(stop|end|eraakistop)(@\w+)?$"))
    async def stop_handler(event):
        chat_id = event.chat_id
        user_id = await resolve_user_id(event)
        game_key = chat_id if not event.is_private else user_id

        user_name, user_mention = await get_player_info(client, event, user_id)
        chat_title = await get_chat_title(event)

        # 1. Stop game for this chat
        if game_key in games:
            game = games[game_key]
            await game["aki"].close()
            del games[game_key]
            await event.reply(f"🛑 Game stopped by {user_mention}!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
            log_telemetry(client, user_name, user_id, chat_title, chat_id, "🛑 Stopped Active Game")
            return

        # 2. Otherwise notify sender
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
        chat_title = await get_chat_title(event)

        # Update active player info to whoever clicked the button
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
            log_telemetry(client, user_name, user_id, chat_title, chat_id, "🛑 Ended Game via Button")
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

                log_telemetry(client, user_name, user_id, chat_title, chat_id, f"🎉 Character Guess Made", f"Guess: {name} ({desc})")

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
                text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{q}"
                await event.edit(text, parse_mode="Markdown", buttons=reply_buttons)
                log_telemetry(client, user_name, user_id, chat_title, chat_id, f"Answered {action_text}", f"Next: Q{aki.step} ({int(aki.progression)}%) - {q}")

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
        chat_title = await get_chat_title(event)

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
            log_telemetry(client, user_name, user_id, chat_title, chat_id, "🏆 Correct Guess Confirmed")
        else:
            aki = game["aki"]
            try:
                q = await aki.answer("n")
                text = f"👤 *Player:* {user_mention}\n🔄 Continuing game!\n❓ *Question {aki.step}:*\n{q}"
                await event.respond(text, parse_mode="Markdown", buttons=reply_buttons)
                log_telemetry(client, user_name, user_id, chat_title, chat_id, "🔄 Rejected Guess, Continuing", f"Q{aki.step}: {q}")
            except Exception:
                await aki.close()
                del games[game_key]
                await event.respond(f"Game ended. Type /eraaki to start again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
