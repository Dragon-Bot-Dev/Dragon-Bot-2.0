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

def connect_db():
    # Priority 1: Railway TCP Proxy (Public/Stable gateway)
    # Priority 2: Standard Railway MySQL Variables
    # Priority 3: Localhost defaults
    host = os.getenv("RAILWAY_TCP_PROXY_DOMAIN", os.getenv("MYSQLHOST", "localhost"))
    user = os.getenv("MYSQLUSER", "root")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")
    
    port = os.getenv("RAILWAY_TCP_PROXY_PORT", os.getenv("MYSQLPORT", "3306"))
    
    print(f"Attempting connection to {host}:{port}...")

    return mysql.connector.connect(
        host=host, 
        user=user, 
        password=password, 
        database=database, 
        port=int(port), 
        autocommit=True,
        buffered=True
    )

db_connection = None
def get_db_cursor():
    global db_connection
    try:
        # 1. Check connection health
        if db_connection is None or not db_connection.is_connected():
            db_connection = connect_db()
            # Explicitly set buffered=True here
            return db_connection.cursor(buffered=True)

        # 2. Ping to keep Railway from killing the connection
        db_connection.ping(reconnect=True, attempts=3, delay=2)
        
        # 3. Return a buffered cursor
        return db_connection.cursor(buffered=True)

    except Exception as e:
        print(f"⚠️ Database Reconnect Triggered: {e}")
        db_connection = connect_db()
        return db_connection.cursor(buffered=True)
        
def get_db_connection(): # Return the connection itself For Upadting DB
    global db_connection
    try:
        if db_connection is None or not db_connection.is_connected():
            db_connection = connect_db()
        else:
            # Lower the delay to 0 or 1 to stay under Discord's 3s limit
            db_connection.ping(reconnect=True, attempts=2, delay=0) 
        return db_connection
    except Exception as e:
        db_connection = connect_db()
        return db_connection
    
async def get_safe_cursor(retries=3, delay=3): # For reminders
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