# bot.py
import os
import asyncio
from datetime import datetime, timedelta
import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
import aiosqlite
from flask import Flask
from threading import Thread

# ===================== FLASK KEEPALIVE =====================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive"

Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# ===================== BOT SETUP =====================
intents = nextcord.Intents.default()
bot = commands.Bot(intents=intents)

DB_PATH = "autopinger.db"

# ===================== DATABASE =====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS autopings (
                            message_id INTEGER PRIMARY KEY,
                            channel_id INTEGER,
                            guild_id INTEGER,
                            header TEXT,
                            points TEXT,
                            winner_id INTEGER,
                            emoji TEXT,
                            end_time TEXT
                            )""")
        await db.commit()

asyncio.get_event_loop().run_until_complete(init_db())

# ===================== PING TASK WITH FOOTER =====================
async def wait_and_ping(message_id: int, channel_id: int, winner_id: int, end_time: datetime):
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    while True:
        remaining = (end_time - datetime.utcnow()).total_seconds()
        if remaining <= 0:
            break

        # Update embed footer
        try:
            msg = await channel.fetch_message(message_id)
            embed = msg.embeds[0]
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            embed.set_footer(text=f"Time remaining: {hours}h {minutes}m {seconds}s")
            await msg.edit(embed=embed)
        except Exception:
            pass

        await asyncio.sleep(5)  # update every 5 seconds

    # Time's up, ping winner
    await channel.send(f"<@{winner_id}> You won! 🎉")

    # Remove from DB
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM autopings WHERE message_id = ?", (message_id,))
        await db.commit()

# ===================== /GIVEAWAY COMMAND =====================
@bot.slash_command(name="giveaway", description="Auto ping a selected user after duration")
async def giveaway(
    interaction: Interaction,
    header: str = SlashOption(description="Giveaway header"),
    points: str = SlashOption(description="Giveaway points/description"),
    winner: nextcord.Member = SlashOption(description="Who will win"),
    emoji: str = SlashOption(description="Emoji for reaction"),
    duration: str = SlashOption(description="Duration e.g., 1h, 30m, 10s")
):
    await interaction.response.defer(ephemeral=False)

    # Calculate end time
    unit = duration[-1].lower()
    amount = int(duration[:-1])
    now = datetime.utcnow()
    if unit == "s":
        end_time = now + timedelta(seconds=amount)
    elif unit == "m":
        end_time = now + timedelta(minutes=amount)
    elif unit == "h":
        end_time = now + timedelta(hours=amount)
    elif unit == "d":
        end_time = now + timedelta(days=amount)
    else:
        await interaction.followup.send("Invalid duration! Use s, m, h, d")
        return

    # Send embed with header and points
    embed = nextcord.Embed(title=header, description=points, color=0x00ff00)
    embed.add_field(name="React to enter :", value=emoji)
    embed.set_footer(text=f"Time remaining: {duration}")
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction(emoji)

    # Save to DB
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO autopings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg.id, interaction.channel.id, interaction.guild.id, header, points, winner.id, emoji, end_time.isoformat())
        )
        await db.commit()

    # Start async ping task
    bot.loop.create_task(wait_and_ping(msg.id, interaction.channel.id, winner.id, end_time))
    await interaction.followup.send(f"Auto ping scheduled for {winner.mention}!", ephemeral=True)

# ===================== RESTORE ON RESTART =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT message_id, channel_id, winner_id, end_time FROM autopings") as cursor:
            async for row in cursor:
                message_id, channel_id, winner_id, end_time_str = row
                end_time = datetime.fromisoformat(end_time_str)
                bot.loop.create_task(wait_and_ping(message_id, channel_id, winner_id, end_time))

# ===================== RUN BOT =====================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(DISCORD_TOKEN)
