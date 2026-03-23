import asyncio
import os
import mysql.connector
import coc
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Credentials
TOKEN = os.getenv('DISCORD_TOKEN2')
COC_EMAIL = os.getenv('COC_EMAIL')
COC_PASSWORD = os.getenv('COC_PASSWORD')


coc_client = None

intents = discord.Intents.default()
intents.message_content = True  # Required for prefix commands
intents.members = True          # Useful for tracking joins/leaves

bot = commands.Bot(command_prefix="!", intents=intents)

# 2. Asynchronous CoC Initialization
async def initialize_coc():
    """Handles the async login process and assigns the global client."""
    global coc_client # CRITICAL: This tells Python to update the shared variable
    try:
        # Create the client INSIDE the function so it catches the current loop
        new_client = coc.Client(key_names="Railway Bot")
        await new_client.login(COC_EMAIL, COC_PASSWORD)
        
        # Now assign it to the global variable
        coc_client = new_client
        
        print("✅ CoC Client logged in and global reference updated.")
    except Exception as e:
        print(f"❌ CoC Login Failed: {e}")

# 3. Robust Database logic
def connect_db():
    # Railway provides these variables automatically if you use their MySQL service
    host = os.getenv("MYSQLHOST", "localhost")
    user = os.getenv("MYSQLUSER", "root")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")
    port = os.getenv("MYSQLPORT", "3306")
    
    return mysql.connector.connect(
        host=host, 
        user=user, 
        password=password, 
        database=database, 
        port=port, 
        autocommit=True,
        buffered=True
    )

db_connection = None
def get_db_cursor():
    global db_connection
    try:
        # 1. Check if it's None first
        if db_connection is None:
            db_connection = connect_db()
            return db_connection.cursor()

        # 2. Ping the database.
        # reconnect=True will automatically try to fix a dropped connection.
        # attempts=3 gives it a few tries if the network is jittery on Railway.
        db_connection.ping(reconnect=True, attempts=3, delay=2)
        
        return db_connection.cursor()

    except Exception as e:
        print(f"⚠️ Database Ping/Reconnect failed: {e}")
        try:
            # 3. Last Resort: Force a completely new connection
            print("🔄 Attempting full database reset...")
            db_connection = connect_db()
            return db_connection.cursor()
        except Exception as final_e:
            print(f"❌ CRITICAL DATABASE FAILURE: {final_e}")
            raise final_e
        
async def get_safe_cursor(retries=3, delay=3):
    """
    Attempts to connect to the DB multiple times before failing.
    Perfect for handling Railway 'cold starts' or brief network blips.
    """
    for attempt in range(retries):
        try:
            # Call your original cursor function
            cursor = get_db_cursor()
            if cursor:
                return cursor
        except Exception as e:
            if attempt < retries - 1:
                print(f"⚠️ DB Connection failed (Attempt {attempt + 1}). Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                print(f"❌ DB Connection failed after {retries} attempts: {e}")
                raise e