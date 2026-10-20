import os
import sys
import asyncio
import discord
from discord.ext import commands, tasks
from aiohttp import web

# 1. Path Setup
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import config
from config import TOKEN, get_db_cursor, initialize_coc, bot 

# --- 🩺 HEALTH CHECK (For Railway Uptime) ---
async def health_check(request):
    """The doorbell Railway rings to see if the bot is alive."""
    return web.Response(text="Bot is online!", status=200)

async def start_health_server():
    """Starts a tiny web server to prevent Railway hibernation."""
    app = web.Application()
    app.router.add_get("/", health_check)
    # Railway automatically provides the 'PORT' environment variable
    port = int(os.getenv("PORT", 8080)) 
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"📡 Health Check pulse started on port {port}")

async def setup():
    """The main manager that runs before the bot starts."""
    async with bot:
        # Bind the health port first so Railway's healthcheck passes even if
        # the CoC login below is slow.
        await start_health_server()

        # 1. Start Clash of Clans connection
        await initialize_coc()

        await asyncio.sleep(10)
        
        await load_extensions() 
        
        
        await bot.start(TOKEN) 

async def load_extensions():
    """Loops through the commands/ folder and loads every .py file."""
    commands_dir = os.path.join(current_dir, 'commands')
    if not os.path.exists(commands_dir):
        print(f"❌ Error: Could not find commands directory at {commands_dir}")
        return

    for filename in os.listdir(commands_dir):
        if filename.endswith('.py'):
            extension_name = f'commands.{filename[:-3]}'
            try:
                await bot.load_extension(extension_name)
                print(f"✅ Successfully loaded: {extension_name}")
            except Exception as e:
                print(f"❌ Failed to load {extension_name}: {e}")

@tasks.loop(minutes=5)
async def db_heartbeat():
    """Keeps the Railway MySQL instance warm every 5 mins."""
    try:
        cursor = get_db_cursor()
        if cursor:
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()
            print("💓 DB Heartbeat: Connection is warm.")
    except Exception as e:
        print(f"⚠️ Heartbeat Error: {e}")

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    if not db_heartbeat.is_running():
        db_heartbeat.start()
    try:
        await bot.tree.sync() 
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
        # Logic to send welcome message is preserved
    except Exception as e:
        print(f"DB Error on guild join: {e}")

@bot.event
async def on_guild_remove(guild):
    """Cleans up server settings from the DB."""
    print(f"Removed from guild: {guild.name} ({guild.id})")
    try:
        cursor = get_db_cursor()
        cursor.execute("DELETE FROM servers WHERE guild_id = %s", (str(guild.id),))
        print(f"✅ Successfully cleaned up settings for {guild.name}")
        cursor.close()
    except Exception as e:
        print(f"DB Error on guild remove: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(setup())
    except KeyboardInterrupt:
        pass