#!/usr/bin/env python3
"""
Ultra-Fast Telegram Akinator Bot (@EraAki_Bot)
- Host-Locked Gameplay: Only the user who initiated /eraaki can click the buttons in group chats.
- Public Visibility: Displays player's name and last selected answer to the entire group.
- Direct Question Display: Shows the active question directly when /eraaki is called during an ongoing game.
- Credit Branding: "Made by Erawat"
- Bot Description & Info set automatically on startup.
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

ANSWER_LABELS = {
    "y": "✅ Yes",
    "n": "❌ No",
    "i": "❓ Don't Know",
    "p": "👍 Probably",
    "pn": "👎 Probably Not",
    "b": "⬅️ Back"
}

CREDIT_TEXT = "Made by @Erawat4l"

class FastAkinator:
    def __init__(self, lang="en"):
        self.lang = lang
        self.session = AsyncSession(impersonate="chrome120")
        self.step = 1
        self.progression = 0.0
        self.question = ""
        self.win = False
        self.first_guess = {}
        self.aki_session = ""
        self.identifiant = ""

    async def start_game(self):
        try:
            await self.session.get(f"https://{self.lang}.akinator.com/")
        except Exception:
            pass

        url = f"https://{self.lang}.akinator.com/game"
        r = await self.session.post(url, data={"sid": "1", "cm": "false"})
        text = r.text

        sess_m = re.search(r"localStorage\.setItem\('session',\s*'([^']+)'\)", text)
        if not sess_m:
            sess_m = re.search(r"session\s*:\s*'([^']+)'", text)
        if not sess_m:
            sess_m = re.search(r'id="session"\s+value="([^"]+)"', text)

        id_m = re.search(r"localStorage\.setItem\('identifiant',\s*'([^']+)'\)", text)
        if not id_m:
            id_m = re.search(r"identifiant\s*:\s*'([^']+)'", text)

        self.aki_session = sess_m.group(1) if sess_m else ""
        self.identifiant = id_m.group(1) if id_m else ""

        q_match = re.search(r'id="question-label">([^<]+)</p>', text)
        if q_match:
            self.question = html.unescape(q_match.group(1).strip())
        else:
            self.question = "Is your character real?"

        self.step = 1
        self.progression = 0.0
        self.win = False
        return self.question

    async def answer(self, ans_str):
        ans_map = {"y": 0, "n": 1, "i": 2, "p": 3, "pn": 4}
        ans_id = ans_map.get(ans_str, 0)

        payload = {
            "step": str(self.step),
            "progression": str(self.progression),
            "sid": "1",
            "cm": "false",
            "answer": str(ans_id),
            "step_last_proposition": "",
            "session": self.aki_session
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://{self.lang}.akinator.com/game",
            "Origin": f"https://{self.lang}.akinator.com"
        }

        r = await self.session.post(f"https://{self.lang}.akinator.com/answer", data=payload, headers=headers)
        
        try:
            res = r.json()
        except Exception:
            self.step += 1
            self.progression = min(99.0, self.progression + 5.0)
            return self.question

        if isinstance(res, dict) and res.get("completion") == "OK":
            if "id_proposition" in res:
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
            self.step += 1
            self.progression = min(99.0, self.progression + 5.0)

        return self.question

    async def back(self):
        if self.step <= 1:
            return self.question

        payload = {
            "step": str(self.step),
            "progression": str(self.progression),
            "sid": "1",
            "cm": "false",
            "session": self.aki_session,
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://{self.lang}.akinator.com/game",
            "Origin": f"https://{self.lang}.akinator.com"
        }

        r = await self.session.post(f"https://{self.lang}.akinator.com/cancel_answer", data=payload, headers=headers)
        try:
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

async def start_web_server():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    async def health(req):
        return web.Response(text="Akinator Bot Online 24/7! Made by Erawat")
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✓ Health check web server active on port {port}")

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token and len(sys.argv) > 1:
        bot_token = sys.argv[1]

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

    # Start lightweight web server for Render Free Web Service
    asyncio.create_task(start_web_server())

    # Register bot commands menu autocomplete & description
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
            about="Official Akinator Telegram Bot made by Erawat. Play Akinator in group chats and DMs!",
            description="Official Akinator Telegram Bot made by Erawat. Play Akinator in group chats and DMs!",
            lang_code="en"
        ))
        print("✓ Registered bot description & command autocomplete menu.")
    except Exception as e:
        logging.error(f"Notice setting bot description: {e}")

    print("⚡ Ultra-Fast Host-Locked Akinator Bot (@EraAki_Bot) started successfully!")

    @client.on(events.NewMessage(pattern=r"(?i)^/eraaki(@\w+)?"))
    async def start_handler(event):
        chat_id = event.chat_id
        sender = await event.get_sender()
        owner_id = event.sender_id
        owner_name = (sender.first_name if (sender and sender.first_name) else "Player")
        owner_mention = f"[{owner_name}](tg://user?id={owner_id})"

        # If a game is active, display the current active question directly with its buttons!
        if chat_id in games:
            game = games[chat_id]
            aki = game["aki"]
            last_ans_text = f" *(Selected: {game['last_ans']})*" if game["last_ans"] else ""
            text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{aki.question}\n\n{CREDIT_TEXT}"
            await event.reply(text, parse_mode="Markdown", buttons=get_game_buttons())
            return

        msg = await event.reply(f"🔮 *Starting Akinator game for* {owner_mention}...\n\n{CREDIT_TEXT}", parse_mode="Markdown")
        
        aki = FastAkinator()
        try:
            q = await aki.start_game()
            games[chat_id] = {
                "aki": aki,
                "owner_id": owner_id,
                "owner_name": owner_name,
                "owner_mention": owner_mention,
                "last_ans": None
            }
            text = f"👤 *Player:* {owner_mention}\n❓ *Question 1:*\n{q}\n\n{CREDIT_TEXT}"
            await msg.edit(text, parse_mode="Markdown", buttons=get_game_buttons())
        except Exception as e:
            logging.error(f"Error starting game: {e}")
            await msg.edit(f"❌ Failed to start Akinator: {e}")

    @client.on(events.NewMessage(pattern=r"(?i)^/(stop|end|eraakistop)(@\w+)?"))
    async def stop_handler(event):
        chat_id = event.chat_id
        if chat_id in games:
            game = games[chat_id]
            if event.sender_id != game["owner_id"]:
                await event.reply(f"⚠️ Only {game['owner_name']} who started the game can stop it!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
                return

            await game["aki"].close()
            del games[chat_id]
            await event.reply(f"🛑 Game stopped by {game['owner_mention']}!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
        else:
            await event.reply(f"No game active. Type /eraaki to start one!\n\n{CREDIT_TEXT}", parse_mode="Markdown")

    @client.on(events.CallbackQuery(pattern=rb"^aki_"))
    async def callback_handler(event):
        chat_id = event.chat_id
        action = event.data.decode().split("_")[1]

        if chat_id not in games:
            await event.answer("No active game in this chat. Type /eraaki!", alert=True)
            return

        game = games[chat_id]

        if event.sender_id != game["owner_id"]:
            await event.answer(f"⚠️ Only {game['owner_name']} can answer this game!\nSend /eraaki to start your own game.", alert=True)
            return

        aki = game["aki"]

        if action == "end":
            await aki.close()
            del games[chat_id]
            await event.answer("Game ended.")
            try:
                await event.edit(f"🛑 Game ended by {game['owner_mention']}. Type /eraaki to start again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
            except MessageNotModifiedError:
                pass
            return

        await event.answer()

        try:
            if action == "b":
                q = await aki.back()
                game["last_ans"] = "⬅️ Back"
            else:
                q = await aki.answer(action)
                game["last_ans"] = ANSWER_LABELS.get(action, "")

            if aki.win:
                guess = aki.first_guess
                name = guess.get("name", "Unknown")
                desc = guess.get("description", "")
                photo = guess.get("photo", "")

                text = f"👤 *Player:* {game['owner_mention']}\n🎉 *I think of:*\n\n🌟 **{name}**\n_{desc}_\n\n{CREDIT_TEXT}"

                if photo:
                    try:
                        await event.delete()
                        await client.send_file(chat_id, photo, caption=text, parse_mode="Markdown", buttons=get_guess_buttons())
                        return
                    except Exception:
                        pass

                await event.edit(text, parse_mode="Markdown", buttons=get_guess_buttons())
            else:
                last_ans_text = f" *(Selected: {game['last_ans']})*" if game["last_ans"] else ""
                text = f"👤 *Player:* {game['owner_mention']}{last_ans_text}\n❓ *Question {aki.step}:* (Progress: {int(aki.progression)}%)\n{q}\n\n{CREDIT_TEXT}"
                await event.edit(text, parse_mode="Markdown", buttons=get_game_buttons())

        except MessageNotModifiedError:
            pass
        except Exception as e:
            logging.error(f"Error processing callback: {e}")

    @client.on(events.CallbackQuery(pattern=rb"^guess_"))
    async def guess_handler(event):
        chat_id = event.chat_id
        action = event.data.decode().split("_")[1]

        if chat_id not in games:
            await event.answer("No active game in this chat.", alert=True)
            return

        game = games[chat_id]

        if event.sender_id != game["owner_id"]:
            await event.answer(f"⚠️ Only {game['owner_name']} can respond to this guess!", alert=True)
            return

        if action == "yes":
            await game["aki"].close()
            del games[chat_id]
            await event.answer("Hooray! 🎉")
            await event.respond(f"🏆 *I guessed it right for {game['owner_mention']}!* Thanks for playing! Send /eraaki to play again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")
        else:
            aki = game["aki"]
            try:
                q = await aki.answer("n")
                text = f"👤 *Player:* {game['owner_mention']}\n🔄 Continuing game!\n❓ *Question {aki.step}:*\n{q}\n\n{CREDIT_TEXT}"
                await event.respond(text, parse_mode="Markdown", buttons=get_game_buttons())
            except Exception:
                await aki.close()
                del games[chat_id]
                await event.respond(f"Game ended. Type /eraaki to start again!\n\n{CREDIT_TEXT}", parse_mode="Markdown")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
