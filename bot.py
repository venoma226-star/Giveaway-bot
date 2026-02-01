import os
import asyncio
from datetime import datetime, timedelta
import nextcord
from nextcord.ext import commands
import aiosqlite
from flask import Flask
import threading

# ===================== BOT SETUP =====================
intents = nextcord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
DB_PATH = "giveaways.db"

NEON = nextcord.Color.from_rgb(138, 43, 226)  # neon purple

# ===================== DATABASE =====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            timer_message_id INTEGER,
            channel_id INTEGER,
            winner_ids TEXT,
            emoji TEXT,
            start_time TEXT,
            end_time TEXT,
            ended INTEGER DEFAULT 0
        )
        """)
        await db.commit()

asyncio.get_event_loop().run_until_complete(init_db())

# ===================== UTILS =====================
def parse_duration(text: str):
    unit = text[-1].lower()
    value = int(text[:-1])
    return {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value)
    }.get(unit)

def progress_bar(percent, size=14):
    filled = int(size * percent)
    return "█" * filled + "░" * (size - filled)

def format_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

# ===================== GIVEAWAY TIMER =====================
async def giveaway_timer(gid, tid, cid, winners, emoji, start, end):
    channel = bot.get_channel(cid)
    if not channel:
        return

    total = (end - start).total_seconds()

    while True:
        now = datetime.utcnow()
        remaining = int((end - now).total_seconds())
        if remaining <= 0:
            break

        percent = 1 - (remaining / total)
        bar = progress_bar(percent)

        # Count entries from reactions
        try:
            gmsg = await channel.fetch_message(gid)
            reaction = next((r for r in gmsg.reactions if str(r.emoji) == emoji), None)
            entries = max(0, reaction.count - 1) if reaction else 0
        except:
            entries = 0

        embed = nextcord.Embed(
            title="⚡ Giveaway Timer",
            description=(
                f"⏳ **Time Left:** `{format_time(remaining)}`\n"
                f"👥 **Entries:** `{entries}`\n\n"
                f"`{bar}`\n\n"
                f"🎯 React with {emoji} to enter"
            ),
            color=NEON
        )
        embed.set_footer(text="Powered by Jordan Bot ⚡")

        try:
            tmsg = await channel.fetch_message(tid)
            await tmsg.edit(embed=embed)
        except:
            pass

        await asyncio.sleep(5)

    # ===================== END =====================
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE giveaways SET ended = 1 WHERE message_id = ?", (gid,))
        await db.commit()

    # Update original giveaway embed footer to Ended
    try:
        gmsg = await channel.fetch_message(gid)
        ended_embed = gmsg.embeds[0]
        ended_embed.set_footer(text="Ended • Powered by Jordan Bot ⚡")
        await gmsg.edit(embed=ended_embed)
    except:
        pass

    # Send end message as plain text (no embed)
    mentions = ", ".join(f"<@{w}>" for w in winners)
    await channel.send(f"🎉 Giveaway Ended!\n🏆 Winner(s): {mentions}\n⚡ Powered by Jordan Bot")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM giveaways WHERE message_id = ?", (gid,))
        await db.commit()

# ===================== GIVEAWAY COMMAND =====================
@bot.command(name="giveawaystart")
@commands.has_permissions(manage_messages=True)
async def giveawaystart(ctx, time: str, *, data: str):
    parts = [p.strip() for p in data.split("|")]

    if len(parts) < 3:
        await ctx.send("❌ Invalid format.")
        return

    *description, emoji, _ = parts
    winners = [m.id for m in ctx.message.mentions]

    if not winners:
        await ctx.send("❌ You must mention at least one winner.")
        return

    duration = parse_duration(time)
    if not duration:
        await ctx.send("❌ Invalid time. Use s/m/h/d")
        return

    start = datetime.utcnow()
    end = start + duration

    embed = nextcord.Embed(
        title="⚡ Giveaway",
        description="\n".join(description),
        color=NEON
    )
    embed.add_field(name="How to Enter", value=f"React with {emoji}")
    embed.set_footer(text="Powered by Jordan Bot ⚡")

    gmsg = await ctx.send(embed=embed)
    await gmsg.add_reaction(emoji)

    tembed = nextcord.Embed(
        title="⏳ Giveaway Timer",
        description="Starting...",
        color=NEON
    )
    tembed.set_footer(text="Powered by Jordan Bot ⚡")

    tmsg = await ctx.send(embed=tembed)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO giveaways VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (
                gmsg.id,
                tmsg.id,
                ctx.channel.id,
                ",".join(map(str, winners)),
                emoji,
                start.isoformat(),
                end.isoformat()
            )
        )
        await db.commit()

    bot.loop.create_task(
        giveaway_timer(gmsg.id, tmsg.id, ctx.channel.id, winners, emoji, start, end)
    )

# ===================== RESTORE ON RESTART =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id, timer_message_id, channel_id, winner_ids, emoji, start_time, end_time FROM giveaways WHERE ended = 0"
        ) as cursor:
            async for mid, tid, cid, wids, emoji, s, e in cursor:
                bot.loop.create_task(
                    giveaway_timer(
                        mid,
                        tid,
                        cid,
                        list(map(int, wids.split(","))),
                        emoji,
                        datetime.fromisoformat(s),
                        datetime.fromisoformat(e)
                    )
                )

# ===================== FLASK KEEP-ALIVE =====================
app = Flask(__name__)

@app.route("/")
def home():
    return "Discord Giveaway Bot is running! ⚡"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# Start Flask server in background thread
threading.Thread(target=run_flask, daemon=True).start()

# ===================== RUN BOT =====================
bot.run(os.environ["DISCORD_TOKEN"])
