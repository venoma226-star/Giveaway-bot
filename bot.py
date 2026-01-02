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
        await db.execute("""
        CREATE TABLE IF NOT EXISTS autopings (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            guild_id INTEGER,
            header TEXT,
            points TEXT,
            winner_id INTEGER,
            emoji TEXT,
            end_time TEXT,
            ended INTEGER DEFAULT 0
        )
        """)
        await db.commit()

asyncio.get_event_loop().run_until_complete(init_db())

# ===================== GIVEAWAY TIMER (RUNS ONCE) =====================
async def wait_and_ping(message_id: int, channel_id: int, winner_id: int, end_time: datetime):
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    # wait until giveaway ends
    remaining = (end_time - datetime.utcnow()).total_seconds()
    if remaining > 0:
        await asyncio.sleep(remaining)

    # prevent duplicate wins
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT ended FROM autopings WHERE message_id = ?",
            (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] == 1:
                return

        await db.execute(
            "UPDATE autopings SET ended = 1 WHERE message_id = ?",
            (message_id,)
        )
        await db.commit()

    # announce winner ONCE
    await channel.send(f"🎉 <@{winner_id}> won the giveaway!")

    # cleanup
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM autopings WHERE message_id = ?",
            (message_id,)
        )
        await db.commit()

# ===================== /GIVEAWAY COMMAND =====================
@bot.slash_command(name="giveaway", description="Rigged giveaway (chosen winner)")
async def giveaway(
    interaction: Interaction,
    header: str = SlashOption(description="Giveaway header"),
    points: str = SlashOption(description="Giveaway points"),
    winner: nextcord.Member = SlashOption(description="Who will win"),
    emoji: str = SlashOption(description="Reaction emoji"),
    duration: str = SlashOption(description="Duration e.g. 10m, 1h, 30s")
):
    await interaction.response.defer()

    # parse duration
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
        await interaction.followup.send("Invalid duration. Use s/m/h/d", ephemeral=True)
        return

    # giveaway embed ONLY
    embed = nextcord.Embed(
        title=header,
        description=points,
        color=0x00ff00
    )
    embed.add_field(name="React to enter:", value=emoji)
    embed.set_footer(text=f"Ends in {duration}")

    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction(emoji)

    # save giveaway
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO autopings VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                msg.id,
                interaction.channel.id,
                interaction.guild.id,
                header,
                points,
                winner.id,
                emoji,
                end_time.isoformat()
            )
        )
        await db.commit()

    # start timer (ONCE)
    bot.loop.create_task(
        wait_and_ping(msg.id, interaction.channel.id, winner.id, end_time)
    )

# ===================== RESTORE ON RESTART =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id, channel_id, winner_id, end_time FROM autopings WHERE ended = 0"
        ) as cursor:
            async for message_id, channel_id, winner_id, end_time_str in cursor:
                end_time = datetime.fromisoformat(end_time_str)
                bot.loop.create_task(
                    wait_and_ping(message_id, channel_id, winner_id, end_time)
                )

# ===================== /USE_AFTER_GIVEAWAY COMMAND =====================
@bot.slash_command(
    name="use_after_giveaway",
    description="Nuke the channel after a giveaway"
)
async def use_after_giveaway(interaction: Interaction):

    # Permission check
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            "❌ You need **Manage Messages** permission to use this command.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "💣 Nuking channel...", ephemeral=True
    )

    channel = interaction.channel

    # Delete all messages
    async for message in channel.history(limit=None):
        try:
            await message.delete()
            await asyncio.sleep(0.25)  # prevent rate limits
        except:
            pass

    # Send nuke embed
    embed = nextcord.Embed(
        title="💥 Channel Nuked",
        description=f"This channel has been nuked by {interaction.user.mention}",
        color=nextcord.Color.from_rgb(0, 0, 0)  # black
    )

    await channel.send(embed=embed)
    
# ===================== RUN BOT =====================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(DISCORD_TOKEN)
