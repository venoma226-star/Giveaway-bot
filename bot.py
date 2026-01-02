import os
import asyncio
import time
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands

import aiosqlite
from flask import Flask
from threading import Thread

# ===================== CONFIG =====================
TOKEN = os.getenv("DISCORD_TOKEN")
DB_NAME = "giveaways.db"

intents = discord.Intents.default()
intents.message_content = False
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== FLASK (RENDER KEEPALIVE) =====================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

Thread(target=run_flask).start()

# ===================== DATABASE =====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            message_id INTEGER,
            forced_winner_id INTEGER,
            end_time INTEGER,
            emoji TEXT
        )
        """)
        await db.commit()

# ===================== GIVEAWAY TASK =====================
async def giveaway_task(giveaway_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT channel_id, message_id, forced_winner_id, end_time, emoji FROM giveaways WHERE giveaway_id = ?",
            (giveaway_id,)
        )
        data = await cursor.fetchone()

    if not data:
        return

    channel_id, message_id, forced_winner_id, end_time, emoji = data
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(message_id)
    except:
        return

    while time.time() < end_time:
        remaining = int(end_time - time.time())
        hours, rem = divmod(remaining, 3600)
        mins, _ = divmod(rem, 60)

        embed = message.embeds[0]
        embed.set_footer(text=f"⏳ Ends in: {hours}h {mins}m")
        await message.edit(embed=embed)

        await asyncio.sleep(60)

    # FINAL — FORCED WINNER ONLY
    winner = channel.guild.get_member(forced_winner_id)
    if not winner:
        await channel.send("❌ Giveaway cancelled (forced winner not found).")
        return

    await channel.send(f"🎉 **Winner:** {winner.mention}")

# ===================== SLASH COMMAND =====================
@bot.tree.command(name="giveaway", description="Create a forced-winner giveaway")
@app_commands.describe(
    header="Giveaway title",
    duration="Duration (e.g. 10m / 2h / 1d)",
    emoji="Entry emoji",
    winner="Forced winner (REQUIRED)"
)
async def giveaway(
    interaction: discord.Interaction,
    header: str,
    duration: str,
    emoji: str,
    winner: discord.Member
):
    await interaction.response.send_message("🎉 Giveaway created!", ephemeral=True)

    unit = duration[-1]
    value = int(duration[:-1])

    seconds = {"m": 60, "h": 3600, "d": 86400}[unit] * value
    end_time = int(time.time() + seconds)

    embed = discord.Embed(
        title=header,
        description=(
            f"• **Winner:** {winner.mention} (FIXED)\n"
            f"• React with {emoji} to enter\n\n"
            f"🏆 **Winners:** 1"
        ),
        color=0x2f3136
    )
    embed.set_footer(text="⏳ Calculating...")

    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction(emoji)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO giveaways (channel_id, message_id, forced_winner_id, end_time, emoji) VALUES (?, ?, ?, ?, ?)",
            (interaction.channel.id, msg.id, winner.id, end_time, emoji)
        )
        giveaway_id = cursor.lastrowid
        await db.commit()

    asyncio.create_task(giveaway_task(giveaway_id))

# ===================== READY =====================
@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
