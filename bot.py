import os
import asyncio
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta

# ================== CONFIG ==================
TOKEN = os.getenv("DISCORD_TOKEN")  # set in Render
GUILD_ID = 1418535300996530319      # your server
DB_FILE = "giveaways.db"

# ================== FLASK KEEP-ALIVE ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# ================== DISCORD BOT ==================
intents = discord.Intents.none()
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================== DATABASE ==================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS giveaways (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    winner_id INTEGER,
    end_time TEXT,
    emoji TEXT,
    active INTEGER
)
""")
conn.commit()

# ================== READY ==================
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f"✅ Logged in as {bot.user}")

    bot.loop.create_task(resume_giveaways())

# ================== TIME PARSER ==================
def parse_duration(value: int, unit: str):
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    return None

# ================== GIVEAWAY COMMAND ==================
@bot.tree.command(name="giveaway", description="Create a forced-winner giveaway", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    title="Giveaway title",
    points="Giveaway description / points",
    duration_value="Duration number",
    duration_unit="m / h / d",
    emoji="Emoji to enter",
    winners="Number of winners (display only)",
    winner="User who WILL win"
)
async def giveaway(
    interaction: discord.Interaction,
    title: str,
    points: str,
    duration_value: int,
    duration_unit: str,
    emoji: str,
    winners: int,
    winner: discord.Member
):
    await interaction.response.defer(ephemeral=True)

    delta = parse_duration(duration_value, duration_unit)
    if not delta:
        await interaction.followup.send("❌ Invalid duration unit (use m/h/d)", ephemeral=True)
        return

    end_time = datetime.utcnow() + delta

    embed = discord.Embed(
        title=title,
        description=f"{points}\n\n"
                    f"🏆 **Winners:** {winners}\n"
                    f"⏰ Ends <t:{int(end_time.timestamp())}:R>\n\n"
                    f"React with {emoji} to enter!",
        color=0x2F3136
    )

    try:
        message = await interaction.channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to send messages here.\n"
            "Give **Send Messages** + **Embed Links**.",
            ephemeral=True
        )
        return

    try:
        await message.add_reaction(emoji)
    except discord.Forbidden:
        pass

    cur.execute(
        "INSERT INTO giveaways VALUES (?, ?, ?, ?, ?, ?)",
        (
            message.id,
            interaction.channel.id,
            winner.id,
            end_time.isoformat(),
            emoji,
            1
        )
    )
    conn.commit()

    bot.loop.create_task(run_giveaway(message.id))
    await interaction.followup.send("✅ Giveaway created (winner locked).", ephemeral=True)

# ================== GIVEAWAY RUNNER ==================
async def run_giveaway(message_id: int):
    while True:
        cur.execute("SELECT channel_id, winner_id, end_time, emoji, active FROM giveaways WHERE message_id = ?", (message_id,))
        row = cur.fetchone()

        if not row:
            return

        channel_id, winner_id, end_time, emoji, active = row
        if not active:
            return

        remaining = datetime.fromisoformat(end_time) - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            break

        await asyncio.sleep(30)

    # END GIVEAWAY
    cur.execute("UPDATE giveaways SET active = 0 WHERE message_id = ?", (message_id,))
    conn.commit()

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    try:
        winner_user = await bot.fetch_user(winner_id)
        await channel.send(f"🎉 Congratulations {winner_user.mention}! You won the giveaway!")
    except:
        pass

# ================== RESUME ON RESTART ==================
async def resume_giveaways():
    await bot.wait_until_ready()
    cur.execute("SELECT message_id FROM giveaways WHERE active = 1")
    rows = cur.fetchall()

    for (message_id,) in rows:
        bot.loop.create_task(run_giveaway(message_id))

# ================== RUN ==================
bot.run(TOKEN)
