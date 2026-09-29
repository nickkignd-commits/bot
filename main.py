import os
import sqlite3
import random
import asyncio
import requests
import json
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask

import discord
from discord import app_commands
from discord.ext import commands

# --- KEEP ALIVE WEB SERVER (For Render Free Service) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# CONFIGURATION (Replace with your actual Staff Log Channel ID)
LOG_CHANNEL_ID = 123456789012345678

# --- SECURITY ROLE CONFIGURATION ---
STAFF_ROLE_ID = 1516046338154823830

ALLOWED_MOD_ROLES = [
    1554028560266690590,  # Ultra Perms
    1554530013750235136,  # Owner
    1554010338951962665,  # Admin
    1534230206032642058,  # Girl Owner
    1516047233978466334,  # Co Owner
    1529006187759140975,  # Manager
    1526950737026875412,  # Head Mod
    1516046808252682291,  # Mod
    1531686180511551568   # Role Mod
]

# --- DATABASE SETUP (SQLite for permanent storage) ---
conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()

# Staff Data Table
cursor.execute('''CREATE TABLE IF NOT EXISTS staff (
    mod_id TEXT PRIMARY KEY,
    recruited_count INTEGER DEFAULT 0
)''')

# Role Hunt Table
cursor.execute('''CREATE TABLE IF NOT EXISTS role_hunts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id TEXT,
    defender_id TEXT,
    gamemode TEXT,
    challenge_time TIMESTAMP,
    status TEXT DEFAULT 'PENDING'
)''')

# Role Hunt Wins Tracker
cursor.execute('''CREATE TABLE IF NOT EXISTS hunt_wins (
    challenger_id TEXT,
    defender_id TEXT,
    gamemode TEXT,
    PRIMARY KEY (challenger_id, defender_id, gamemode)
)''')

conn.commit()

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot Online: {bot.user.name}")

# ==========================================
# 1. STAFF RECRUITMENT SYSTEM (SECURED)
# ==========================================

@bot.tree.command(name="addstaff", description="Promote a user to staff and log recruitment.")
async def addstaff(interaction: discord.Interaction, target: discord.Member):
    # Security Check: Verifies if command executor holds an allowed management role
    executor_role_ids = [role.id for role in interaction.user.roles]
    has_permission = any(mod_role_id in executor_role_ids for mod_role_id in ALLOWED_MOD_ROLES)

    if not has_permission:
        await interaction.response.send_message("❌ You do not have permission to execute this command!", ephemeral=True)
        return

    # Fetch and validate the target Staff Role
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    if not staff_role:
        await interaction.response.send_message("❌ Staff role not found in this server. Please check the Role ID.", ephemeral=True)
        return

    # Assign only the fixed Staff Role
    await target.add_roles(staff_role)
    mod_id = str(interaction.user.id)
    
    cursor.execute("INSERT INTO staff (mod_id, recruited_count) VALUES (?, 1) ON CONFLICT(mod_id) DO UPDATE SET recruited_count = recruited_count + 1", (mod_id,))
    conn.commit()
    
    cursor.execute("SELECT recruited_count FROM staff WHERE mod_id = ?", (mod_id,))
    total_recruited = cursor.fetchone()[0]
    
    embed = discord.Embed(title="🛡️ Staff Recruitment Log", color=discord.Color.green(), timestamp=datetime.utcnow())
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="New Staff Member", value=target.mention, inline=True)
    embed.add_field(name="Role Assigned", value=staff_role.mention, inline=False)
    embed.add_field(name="Total Recruited by Mod", value=f"**{total_recruited}** users", inline=False)
    
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(embed=embed)
        
    await interaction.response.send_message(f"✅ Successfully assigned {staff_role.mention} to {target.mention}! Total Recruited: **{total_recruited}**", ephemeral=True)

@bot.tree.command(name="staffstats", description="Check staff recruitment stats of a moderator.")
async def staffstats(interaction: discord.Interaction, moderator: discord.Member = None):
    mod = moderator or interaction.user
    cursor.execute("SELECT recruited_count FROM staff WHERE mod_id = ?", (str(mod.id),))
    row = cursor.fetchone()
    count = row[0] if row else 0
    
    embed = discord.Embed(
        title="📊 Staff Recruitment Stats", 
        description=f"{mod.mention} has recruited a total of **{count}** staff members.", 
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)

# ==========================================
# 2. MINECRAFT ROLE HUNT TRACKER
# ==========================================

@bot.tree.command(name="challenge-role", description="Challenge a Role Holder for a PvP Role Hunt.")
@app_commands.choices(gamemode=[
    app_commands.Choice(name="Elytra Mace", value="Elytra Mace"),
    app_commands.Choice(name="Nethpot", value="Nethpot"),
    app_commands.Choice(name="Tank", value="Tank"),
    app_commands.Choice(name="CPVP", value="CPVP")
])
async def challenge_role(interaction: discord.Interaction, defender: discord.Member, gamemode: app_commands.Choice[str]):
    deadline = datetime.utcnow() + timedelta(days=7)
    timestamp_unix = int(deadline.timestamp())
    
    cursor.execute("INSERT INTO role_hunts (challenger_id, defender_id, gamemode, challenge_time) VALUES (?, ?, ?, ?)",
                   (str(interaction.user.id), str(defender.id), gamemode.value, datetime.utcnow()))
    conn.commit()
    
    embed = discord.Embed(title="⚔️ Role Hunt Challenge Issued!", color=discord.Color.red())
    embed.add_field(name="Challenger", value=interaction.user.mention, inline=True)
    embed.add_field(name="Defender (Role Holder)", value=defender.mention, inline=True)
    embed.add_field(name="Gamemode", value=f"**{gamemode.value}**", inline=False)
    embed.add_field(name="Deadline (1 Week)", value=f" ()", inline=False)
    embed.set_footer(text="You have 1 week to complete this challenge match!")
    
    await interaction.response.send_message(content=f"{defender.mention} you have been challenged!", embed=embed)

@bot.tree.command(name="log-hunt-match", description="Log a Role Hunt match result (Admin/Staff only).")
async def log_hunt_match(interaction: discord.Interaction, challenger: discord.Member, defender: discord.Member, gamemode: str, winner: discord.Member, proof: str):
    executor_role_ids = [role.id for role in interaction.user.roles]
    has_permission = any(mod_role_id in executor_role_ids for mod_role_id in ALLOWED_MOD_ROLES)

    if not has_permission:
        await interaction.response.send_message("❌ You do not have permission to log match results!", ephemeral=True)
        return

    if winner.id == challenger.id:
        cursor.execute("INSERT OR IGNORE INTO hunt_wins (challenger_id, defender_id, gamemode) VALUES (?, ?, ?)",
                       (str(challenger.id), str(defender.id), gamemode))
        conn.commit()
        
    cursor.execute("SELECT COUNT(*) FROM hunt_wins WHERE challenger_id = ? AND defender_id = ?", (str(challenger.id), str(defender.id)))
    wins = cursor.fetchone()[0]
    
    embed = discord.Embed(title="⚔️ Role Hunt Match Logged", color=discord.Color.gold())
    embed.add_field(name="Challenger", value=challenger.mention, inline=True)
    embed.add_field(name="Defender", value=defender.mention, inline=True)
    embed.add_field(name="Gamemode", value=gamemode, inline=True)
    embed.add_field(name="Winner", value=f"🏆 {winner.mention}", inline=False)
    embed.add_field(name="Challenger Total Wins Against Defender", value=f"**{wins}/3** needed for Role", inline=False)
    embed.add_field(name="Proof Link", value=proof, inline=False)
    
    if wins >= 3:
        embed.add_field(name="🎉 ROLE UNLOCKED!", value=f"{challenger.mention} has won 3/4 gamemodes! Staff, please assign the role.", inline=False)
        
    await interaction.response.send_message(embed=embed)

# ==========================================
# 3. UNIVERSAL EVENT & TOURNAMENT ENGINE
# ==========================================

class EventRegistrationModal(discord.ui.Modal):
    def __init__(self, question_text, view_ref):
        super().__init__(title="Event Registration")
        self.view_ref = view_ref
        self.answer = discord.ui.TextInput(label=question_text[:45], placeholder="Enter your response here...", required=True)
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id in self.view_ref.registered_users:
            await interaction.response.send_message("❌ You are already registered for this event!", ephemeral=True)
            return

        if len(self.view_ref.registered_users) >= self.view_ref.max_slots:
            await interaction.response.send_message("❌ Registration closed! All slots are full.", ephemeral=True)
            return

        self.view_ref.registered_users.append(interaction.user.id)
        self.view_ref.user_data[interaction.user.id] = self.answer.value
        await self.view_ref.update_embed(interaction)
        await interaction.response.send_message(f"✅ Registration successful! Your details: **{self.answer.value}**", ephemeral=True)

class EventRegistrationView(discord.ui.View):
    def __init__(self, title, max_slots, question=None):
        super().__init__(timeout=None)
        self.title = title
        self.max_slots = max_slots
        self.question = question
        self.registered_users = []
        self.user_data = {}

    @discord.ui.button(label="📝 Register Now", style=discord.ButtonStyle.success)
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.registered_users) >= self.max_slots:
            button.disabled = True
            button.label = "🚫 Event Full"
            await interaction.response.edit_message(view=self)
            return

        if interaction.user.id in self.registered_users:
            await interaction.response.send_message("❌ You are already registered for this event!", ephemeral=True)
            return

        if self.question:
            await interaction.response.send_modal(EventRegistrationModal(self.question, self))
        else:
            self.registered_users.append(interaction.user.id)
            await self.update_embed(interaction)
            await interaction.response.send_message("✅ You have successfully registered!", ephemeral=True)

    async def update_embed(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Slots", value=f"**{len(self.registered_users)} / {self.max_slots}**", inline=True)
        if len(self.registered_users) >= self.max_slots:
            self.children[0].disabled = True
            self.children[0].label = "🚫 Event Full"
        await interaction.message.edit(embed=embed, view=self)

@bot.tree.command(name="create-event", description="Create a tournament or drawing contest registration post.")
async def create_event(interaction: discord.Interaction, title: str, slots: int, question: str = None):
    executor_role_ids = [role.id for role in interaction.user.roles]
    has_permission = any(mod_role_id in executor_role_ids for mod_role_id in ALLOWED_MOD_ROLES)

    if not has_permission:
        await interaction.response.send_message("❌ You do not have permission to create events!", ephemeral=True)
        return

    view = EventRegistrationView(title, slots, question)
    embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.purple())
    embed.add_field(name="Slots", value=f"**0 / {slots}**", inline=True)
    if question:
        embed.add_field(name="Required Info", value=f"`{question}`", inline=True)
    embed.description = "Click **Register Now** below to join the event!"
    
    await interaction.response.send_message(embed=embed, view=view)

# ==========================================
# 4. NITRO EMOTE & REACT BYPASS
# ==========================================

@bot.tree.command(name="say", description="Send a message with animated/custom emojis without Nitro.")
async def say(interaction: discord.Interaction, message: str):
    await interaction.response.send_message("Sending message...", ephemeral=True)
    await interaction.channel.send(message)

@bot.tree.command(name="react", description="React to any message with custom/animated emojis.")
async def react(interaction: discord.Interaction, message_id: str, emoji: str):
    try:
        msg = await interaction.channel.fetch_message(int(message_id))
        await msg.add_reaction(emoji)
        await interaction.response.send_message(f"✅ Reacted with {emoji}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: Invalid Message ID or Emoji! ({e})", ephemeral=True)

# ==========================================
# 5. WHEEL SPINNER / PICKER
# ==========================================

@bot.tree.command(name="spin", description="Randomly pick names from a list.")
async def spin(interaction: discord.Interaction, names: str, winners: int = 1):
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if len(name_list) < 2 or winners > len(name_list):
        await interaction.response.send_message("❌ Please provide at least 2 candidates and ensure winner count is valid!", ephemeral=True)
        return

    embed = discord.Embed(title="🎡 Spinning the Wheel...", description="🎰 *Selecting winners...*", color=discord.Color.gold())
    embed.add_field(name="Candidates", value=", ".join(name_list))
    await interaction.response.send_message(embed=embed)

    await asyncio.sleep(3)
    selected = random.sample(name_list, winners)

    res_embed = discord.Embed(title="🎉 Wheel Result!", color=discord.Color.green())
    res_embed.description = "\n".join([f"🥇 **Winner {i+1}:** {name}" for i, name in enumerate(selected)])
    await interaction.edit_original_response(embed=res_embed)

# ==========================================
# 6. ART SHOWCASE & MINECRAFT UTILITIES
# ==========================================

@bot.tree.command(name="artshowcase", description="Post artwork with feedback buttons.")
async def artshowcase(interaction: discord.Interaction, title: str, image_url: str):
    embed = discord.Embed(title=f"🎨 {title}", color=discord.Color.magenta())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_image(url=image_url)
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="🔥 Fire", style=discord.ButtonStyle.primary, custom_id="art_fire"))
    view.add_item(discord.ui.Button(label="🎨 Insane", style=discord.ButtonStyle.success, custom_id="art_insane"))
    
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="mcskin", description="Get 3D render and skin of a Minecraft player.")
async def mcskin(interaction: discord.Interaction, username: str):
    res = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}")
    if res.status_code != 200:
        await interaction.response.send_message("❌ Minecraft player not found!", ephemeral=True)
        return
        
    uuid = res.json()['id']
    embed = discord.Embed(title=f"🎮 Minecraft Skin: {username}", color=discord.Color.green())
    embed.set_image(url=f"https://visage.surgeplay.com/full/512/{uuid}")
    embed.set_thumbnail(url=f"https://visage.surgeplay.com/face/128/{uuid}")
    await interaction.response.send_message(embed=embed)

# --- SAFE BOT STARTUP WITH KEEP ALIVE ---
keep_alive()  # Starts the web server to keep Render active
BOT_TOKEN = os.getenv("BOT_TOKEN")

if BOT_TOKEN:
    bot.run(BOT_TOKEN)
else:
    print("❌ BOT_TOKEN environment variable missing! Please set BOT_TOKEN in your hosting dashboard.")
