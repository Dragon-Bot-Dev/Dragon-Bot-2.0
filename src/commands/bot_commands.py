from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands, Embed, ui, Interaction
import random
import time
import coc
import praw
import os

# INITIALIZE REDDIT AT THE TOP (Global Scope)
client_id = os.getenv('client_id')
client_secret = os.getenv('client_secret')
user_agent = os.getenv('user_agent')

reddit = praw.Reddit(
    client_id=client_id,
    client_secret=client_secret, 
    user_agent=user_agent,
    check_for_async=False # Recommended for use within discord.py
)

# Import helpers from config and utils
from config import get_db_connection, get_db_cursor, coc_client
from utils import (
    fetch_clan_from_db, fetch_player_from_DB, get_clan_data, 
    check_coc_clan_tag, check_coc_player_tag, get_player_data,
    ClanNotSetError, PlayerNotLinkedError, MissingPlayerTagError
)


# 1. Define the Button View (Keep this outside the class)
class HelpView(ui.View):
    def __init__(self, summary_embed, full_embed):
        super().__init__(timeout=120)
        self.summary_embed = summary_embed
        self.full_embed = full_embed
        self.showing_all = False

    @ui.button(label="Show All Commands", style=discord.ButtonStyle.blurple)
    async def toggle_help(self, interaction: discord.Interaction, button: ui.Button):
        if not self.showing_all:
            button.label = "Show Less"
            button.style = discord.ButtonStyle.gray # Change color for "Show Less"
            self.showing_all = True
            await interaction.response.edit_message(embed=self.full_embed, view=self)
            
        else:
            button.label = "Show All Commands"
            button.style = discord.ButtonStyle.blurple
            self.showing_all = False
            await interaction.response.edit_message(embed=self.summary_embed, view=self)
           

class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Displays command guide")
    async def help_command(self, interaction: discord.Interaction):
        """Sends a toggleable command menu."""
        
        # VERSION A: Summary (Only the most important ones)
        summary_embed = discord.Embed(
            title="🐉 Dragon Bot | Quick Guide",
            description="Essential commands for daily usage. Click the button for the full list!",
            color=0x00FF00
        )
        summary_embed.add_field(name="🛡️ Clan Core", 
            value=(
                "> `/claninfo` — General clan overview\n"
                "> `/clanmembers` — Members ranked by leagues\n"
                "> `/currentwar` — Stats & Info for War/CWL\n"
                "> `/capitalraid` — Current Raid Weekend progress\n"
                "> `/cwlprep` — Scout matchup levels for current CWL\n"

        ), inline=True
        )

        summary_embed.add_field(name="⚔️ Player Core",
           value=(
                "> `/playerinfo` — General stats and clan-related info\n"
                "> `/playerheroes` — Check heroes, pets and equipment levels\n"
                "> `/searchmember` — Find a player in your current clan"
            ),
            inline=False)
        summary_embed.add_field(name="⚙️ Settings",
            value=(
                "> `/setclantag` — Link clan and set reminder channels\n"
                "> `/botstatus` — View current server config\n"
                "> `/link` / `/unlink` — Connect/disconnect CoC tag to Discord"
            ),
            inline=False
        )

        # VERSION B: Full (The master list)
            # 🛡️ Clan Management
        full_embed = discord.Embed(
            title="🐉 Dragon Bot | Master Command List",
            description="Complete list of all available tools and utilities.",
            color=0x00FF00
        )
        full_embed.add_field(
            name="🛡️ **Clan Management**",
            value=(
                "> `/claninfo` — General clan overview\n"
                "> `/clanmembers` — Members ranked by leagues\n"
                "> `/clansearch` — Search for a clan by name\n"
                "> `/capitalraid` — Current Raid Weekend progress\n"
                "> `/previousraids` — History of past Raid seasons\n"
                "> `/currentwar` — Stats & Info for War/CWL\n"
                "> `/warlog` — Check recent war history\n"
                "> `/cwlprep` — Scout matchup levels for current CWL\n"
                "> `/cwlschedule` — View CWL rounds and opponents\n"
                "> `/cwlclansearch` — Search opponent rosters and levels"
            ),
            inline=False
        )

        # ⚔️ Player Tools
        full_embed.add_field(
            name="⚔️ **Player Tools**",
            value=(
                "> `/playerinfo` — General stats and clan-related info\n"
                "> `/playerlevels` — Troops & Siege levels\n"
                "> `/playerheroes` — Check heroes, pets and equipment levels\n"
                "> `/searchmember` — Find a player in your current clan"
            ),
            inline=False
        )

        # ⚙️ Settings & Admin
        full_embed.add_field(
            name="⚙️ **Settings & Admin**",
            value=(
                "> `/setclantag` — Link clan and set reminder channels\n"
                "> `/disable_reminders` — Mute War or Raid pings (Admins)\n"
                "> `/botstatus` — View current server config\n"
                "> `/link` / `/unlink` — Connect/disconnect CoC tag to Discord"
            ),
            inline=False
        )
        full_embed.add_field(
            name="**Extras**",
            value=(
                "> `/flipcoin`\n"
                "> `/announce` — Make an announcement with the Dragon Bot\n"
                "> `/receiveposts` — Receive posts from Reddit; default subreddit is ClashOfClansLeaks\n"
                "> `/help` — This command"
            ),
            inline=False
        )

        full_embed.set_footer(text="Tip: Start with /setclantag and use /botstatus to setup your server!")

        view = HelpView(summary_embed, full_embed)
        await interaction.response.send_message(embed=summary_embed, view=view, ephemeral=True)

    # ... (rest of your commands like receive_posts, flipcoin, etc., stay below here) ...
    @app_commands.command(name="receiveposts", description="Receive posts from Reddit")
    @app_commands.describe(
        subreddit_name="The subreddit to check (Default: ClashOfClansLeaks)", 
        post_type="Choose: hot, new, or top", 
        limit="Number of posts (Max: 5)"
    )
    @app_commands.choices(post_type=[
        app_commands.Choice(name="Hot", value="hot"),
        app_commands.Choice(name="New", value="new"),
        app_commands.Choice(name="Top", value="top")
    ])
    # Set the default here in the argument list
    async def receive_posts(self, interaction: discord.Interaction, subreddit_name: str = "ClashOfClansLeaks", post_type: str = 'hot', limit: int = 3):
        await interaction.response.defer()
        
        try:
            subreddit = reddit.subreddit(subreddit_name) 
            
            # This triggers a check to see if the subreddit exists/is accessible
            try:
                subreddit.id 
            except Exception:
                return await interaction.followup.send(f"❌ Subreddit `r/{subreddit_name}` is private or does not exist.")

            limit = min(limit, 5) 

            # Fetching data
            if post_type == 'new':
                posts = subreddit.new(limit=12)
            elif post_type == 'top':
                posts = subreddit.top(limit=12)
            else:
                posts = subreddit.hot(limit=12)

            # Filter pinned and NSFW (optional but recommended for clan safety)
            non_pinned_posts = [post for post in posts if not post.stickied and not post.over_18][:limit]

            if not non_pinned_posts:
                return await interaction.followup.send(f"No suitable posts found in r/{subreddit_name}.")

            await interaction.followup.send(f"**{post_type.capitalize()} posts from r/{subreddit_name}:**")

            for post in non_pinned_posts: 
                # Convert Reddit Unix timestamp to a Discord-friendly integer
                post_time = int(post.created_utc)
                
                embed = discord.Embed(
                    title=post.title[:250],
                    url=f"https://reddit.com{post.permalink}", 
                    # Adding the relative timestamp to the description
                    description=f"Posted: <t:{post_time}:R>",
                    color=0xFF4500,
                    # This puts the exact date/time in the footer area
                    timestamp=datetime.fromtimestamp(post.created_utc)
                )
                
                # Image Logic
                if any(post.url.endswith(ext) for ext in ['.jpg', '.png', '.gif', '.jpeg']):
                    embed.set_image(url=post.url)
                elif post.thumbnail and post.thumbnail.startswith("http"):
                    embed.set_thumbnail(url=post.thumbnail)
                
                embed.set_footer(text=f"r/{subreddit_name} • 👍 {post.score} | 💬 {post.num_comments}")
                await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"⚠️ An unexpected error occurred: `{e}`")

    @app_commands.command(name="announce", description="Make an announcement")
    async def announce(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message(message)

    @app_commands.command(name="flipcoin", description="Flip coin (heads or tails)")
    async def flip(self, interaction: discord.Interaction):
        result = "Heads!!!" if random.randint(1, 2) == 1 else "Tails!!!"
        await interaction.response.send_message(f"The coin flips to... {result}")

    @app_commands.command(name="about", description="Information about Dragon Bot 2.0")
    async def about(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="About Dragon Bot 2.0",
            description="The ultimate companion for Clash of Clans leaders and players.",
            color=0x00ff00 # Or your brand color
        )

        # Main Info
        embed.add_field(name="Developer", value="Keepas", inline=True)
        embed.add_field(name="Website", value="[Visit Dashboard](https://dragon-bot-website.vercel.app/)", inline=True)

        
        embed.add_field(
            name="Legal",
            value=(
                "Dragon Bot 2.0 is an independent fan-made tool. "
                "It is not affiliated with, endorsed, or sponsored by Supercell. "
                "All game assets and trademarks belong to Supercell."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botstatus", description="Get the server configuration and status")
    async def server_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(buffered=True)
            guild_id = str(interaction.guild.id)
            
            cursor.execute("SELECT clan_tag, war_channel_id, raid_channel_id FROM servers WHERE guild_id = %s", (guild_id,))
            row = cursor.fetchone()
            
            # 1. Improved Safely check if row exists
            if row:
                clan_tag = f"`{row[0]}`" if row[0] else "`❌ Not Set`"
                war_mention = f"<#{row[1]}>" if row[1] else "`❌ Not Configured`"
                raid_mention = f"<#{row[2]}>" if row[2] else "`❌ Not Configured`"
            else:
                clan_tag = "`❌ Run /setclantag to configure`"
                war_mention = "`❌ Not Configured`"
                raid_mention = "`❌ Not Configured`"

            # 2. Fetch Linked Players
            cursor.execute("SELECT discord_username, player_tag FROM players WHERE guild_id = %s", (guild_id,))
            players = cursor.fetchall()
            player_info = "\n".join([f"• @{u} (`{t}`)" for u, t in players]) if players else "` No Linked Members `"

            # 3. Build the Polished Embed
            embed = discord.Embed(
                title=f"🛡️ {interaction.guild.name} Configuration",
                color=0x3498db,
                timestamp=interaction.created_at
            )
            
            embed.add_field(name="Current Clan", value=f"`{clan_tag}`", inline=False)
            embed.add_field(name="⚔️ War Reminders", value=war_mention, inline=True)
            embed.add_field(name="🏰 Raid Reminders", value=raid_mention, inline=True)
            

            embed.add_field(name="Linked Members", value=player_info, inline=False)
            
            embed.set_footer(text=f"Serving {len(self.bot.guilds)} servers | {len(self.bot.users)} users")
            
            await interaction.followup.send(embed=embed)

            cursor.close()
        except Exception as e:
            print(f"Error in botstatus: {e}")
            await interaction.followup.send(f"❌ Error fetching status: `{e}`")

    @app_commands.command(name='setclantag', description="Set the clan tag and optional reminder channels")
    @app_commands.describe(
        new_tag="The #ClanTag", 
        war_channel="Optional: Channel for war reminders",
        raid_channel="Optional: Channel for capital raid reminders"
    )
    async def set_clan_tag(
        self, 
        interaction: discord.Interaction, 
        new_tag: str, 
        war_channel: discord.TextChannel = None,
        raid_channel: discord.TextChannel = None
    ):
        clean_tag = new_tag.strip().upper()
        if not clean_tag.startswith("#"): 
            clean_tag = f"#{clean_tag}"
        
        # 1. Validate the Tag with CoC API
        if not await check_coc_clan_tag(clean_tag):
            return await interaction.response.send_message("❌ Invalid Clan Tag. Please check the tag in-game.", ephemeral=True)

        cursor = get_db_cursor()
        guild_id = str(interaction.guild.id)
        
        # 2. Advanced Upsert Logic
        # We use COALESCE in the UPDATE section. 
        # This says: "If the new value is NULL, keep the old value that's already in the table."
        
        sql = """
            INSERT INTO servers (guild_id, guild_name, clan_tag, war_channel_id, raid_channel_id)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                clan_tag = VALUES(clan_tag),
                guild_name = VALUES(guild_name),
                war_channel_id = COALESCE(VALUES(war_channel_id), war_channel_id),
                raid_channel_id = COALESCE(VALUES(raid_channel_id), raid_channel_id)
        """
        
        # Convert objects to string IDs only if they were provided
        war_id = str(war_channel.id) if war_channel else None
        raid_id = str(raid_channel.id) if raid_channel else None
        
        cursor.execute(sql, (guild_id, interaction.guild.name, clean_tag, war_id, raid_id))

        # 3. Build a nice confirmation message
        msg = f"✅ **Clan Linked:** `{clean_tag}`\n"
        if war_channel:
            msg += f"⚔️ War Reminders: {war_channel.mention}\n"
        if raid_channel:
            msg += f"🏰 Raid Reminders: {raid_channel.mention}\n"
        
        if not war_channel and not raid_channel:
            msg += "*(Reminder channels were not changed)*"

        await interaction.response.send_message(msg)

    @app_commands.command(name='link', description="Link your CoC account")
    async def link(self, interaction: discord.Interaction, player_tag: str):
    # 1. Defer immediately to give your DB ping and CoC API time to breathe
        await interaction.response.defer(ephemeral=True) 

        clean_tag = player_tag.strip().upper()
        if not clean_tag.startswith("#"): clean_tag = f"#{clean_tag}"
        
        if await check_coc_player_tag(clean_tag):
            try:
                conn = get_db_connection() # Get connection
                cursor = conn.cursor(buffered=True) # Get cursor
                
                cursor.execute("""
                    INSERT INTO players (discord_id, discord_username, guild_id, guild_name, player_tag, is_premium)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        player_tag = VALUES(player_tag),
                        discord_username = VALUES(discord_username)
                """, (
                    str(interaction.user.id), 
                    interaction.user.display_name, 
                    str(interaction.guild.id), 
                    interaction.guild.name,
                    clean_tag, 
                    0
                ))
                

                conn.commit() 
                cursor.close()
                
                await interaction.followup.send(f"✅ Linked to **{clean_tag}**!")
            except Exception as e:
                print(f"DB Error: {e}")
                await interaction.followup.send("❌ Database error occurred.")
        else:
            await interaction.followup.send("❌ Invalid player tag.", ephemeral=True)

    @app_commands.command(name='unlink', description="Unlink your CoC account")
    async def unlink(self, interaction: discord.Interaction):
        # ALWAYS defer if you're hitting the DB. 
        await interaction.response.defer(ephemeral=True)

        try:
            conn = get_db_connection()
            cursor = conn.cursor(buffered=True)
            
            
            cursor.execute(
                "DELETE FROM players WHERE discord_id = %s AND guild_id = %s", 
                (str(interaction.user.id), str(interaction.guild.id))
            )
            
            conn.commit()
            
            if cursor.rowcount > 0:
                await interaction.followup.send("✅ Your Clash of Clans account has been unlinked from this server.")
            else:
                await interaction.followup.send("❌ You don't have an account linked in this server.")
            
            cursor.close()
        except Exception as e:
            print(f"DB Error in Unlink: {e}")
            await interaction.followup.send("❌ An error occurred while unlinking.")


    
    @app_commands.command(name="disable_reminders", description="Turn off specific background reminders")
    @app_commands.describe(type="Choose which reminder to disable")
    @app_commands.choices(type=[
        app_commands.Choice(name="⚔️ War Reminders", value="war"),
        app_commands.Choice(name="🏰 Raid Reminders", value="raid"),
        app_commands.Choice(name="🚫 Both", value="both")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def disable_reminders(self, interaction: discord.Interaction, type: str):
        await interaction.response.defer(ephemeral=True)
        
        cursor = get_db_cursor()
        guild_id = str(interaction.guild.id)
        
        if type == "war":
            sql = "UPDATE servers SET war_channel_id = NULL WHERE guild_id = %s"
            label = "⚔️ War Reminders"
        elif type == "raid":
            sql = "UPDATE servers SET raid_channel_id = NULL WHERE guild_id = %s"
            label = "🏰 Raid Reminders"
        else:
            sql = "UPDATE servers SET war_channel_id = NULL, raid_channel_id = NULL WHERE guild_id = %s"
            label = "⚔️ War and 🏰 Raid Reminders"

        try:
            cursor.execute(sql, (guild_id,))
            # commit is usually handled inside get_db_cursor or at the end of execution
            
            await interaction.followup.send(f"✅ {label} have been disabled for this server.")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update settings: {e}")

    # Ensure you have 'import praw' at the top of your file!
    # The reddit instance should be initialized in your __init__ or globally
    
async def setup(bot):
    await bot.add_cog(BotCommands(bot))