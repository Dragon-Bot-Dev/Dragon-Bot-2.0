import os
import sys
import asyncio
import discord
from discord.ext import commands, tasks

# 1. Path Setup
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 2. Import bot and other setups from your config file

import config
from config import TOKEN, get_db_cursor, initialize_coc, bot 

async def load_extensions():
    """Loops through the commands/ folder and loads every .py file."""
    commands_dir = os.path.join(current_dir, 'commands')
    
    if not os.path.exists(commands_dir):
        print(f"❌ Error: Could not find commands directory at {commands_dir}")
        return

    for filename in os.listdir(commands_dir):
        if filename.endswith('.py'):
            # Convert filename to extension syntax: 'commands.war_commands'
            extension_name = f'commands.{filename[:-3]}'
            try:
                # This call triggers the 'setup(bot)' function in each command file
                await bot.load_extension(extension_name)
                print(f"✅ Successfully loaded: {extension_name}")
            except Exception as e:
                print(f"❌ Failed to load {extension_name}: {e}")

async def setup():
    """The main manager that runs before the bot starts."""
    async with bot:
        # 1. Start the Clash of Clans connection FIRST.
        # This populates config.coc_client so it's no longer None.
        await initialize_coc() 
        
        # Give it a small heartbeat to ensure the login is registered
        await asyncio.sleep(2)
        # When 'setup(bot)' runs in your command files, config.coc_client will be ready.
        await load_extensions() 
        
        await bot.start(TOKEN) 

@tasks.loop(minutes=9)
async def db_heartbeat(): # Removed 'self'
    """Keeps the Railway MySQL instance warm every 9 mins"""
    try:
        # will just try again in 9 minutes if it fails once.
        cursor = get_db_cursor()
        if cursor:
            # We MUST execute a query to keep the connection alive
            cursor.execute("SELECT 1")
            cursor.close()
            print("💓 DB Heartbeat: Connection is warm.")
    except Exception as e:
        print(f"⚠️ Heartbeat: Database is likely rebooting or timed out... {e}")

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    """Triggered when the bot is officially connected to Discord."""
    # 1. Start the DB Heartbeat
    if not db_heartbeat.is_running():
        db_heartbeat.start()
        print("💓 Database heartbeat started.")

    try:
        await bot.tree.sync() 
        
        # Specific Guild Sync (Instant - Use for testing!)
        # Replace 123456789 with your test server ID
        # test_guild = discord.Object(id=123456789)
        # bot.tree.copy_global_to(guild=test_guild)
        # await bot.tree.sync(guild=test_guild)

        print(f'🚀 Logged in as {bot.user} and commands synced!')
    except Exception as e:
        print(f"Error syncing tree: {e}")
        
    await bot.change_presence(activity=discord.Game(name='Playing with Fire'))
@bot.event
async def on_guild_join(guild):
    print(f"Joined new guild: {guild.name} ({guild.id})")
    try:
        cursor = get_db_cursor()
        cursor.execute("""
            INSERT IGNORE INTO servers (guild_id, guild_name) 
            VALUES (%s, %s)
        """, (str(guild.id), guild.name))
        if guild.system_channel:
            await guild.system_channel.send("Dragon Bot 2.0 has arrived! Use `/setclantag` to get started and `/help` for more information.")
    except Exception as e:
        print(f"DB Error on guild join: {e}")

@bot.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} ({guild.id})")
    try:
        cursor = get_db_cursor()
        cursor.execute("DELETE FROM servers WHERE guild_id = %s", (str(guild.id),))
        cursor.execute("DELETE FROM players WHERE guild_id = %s", (str(guild.id),))
    except Exception as e:
        print(f"DB Error on guild remove: {e}")

if __name__ == "__main__":
    # Helps prevent loop errors on local Windows machines
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(setup())
    except KeyboardInterrupt:
        pass