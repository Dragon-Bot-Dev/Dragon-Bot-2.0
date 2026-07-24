from datetime import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands, Embed, ui, Interaction
import random
import time
import coc
import praw
import os
import json
import asyncio
from services.coc_worker import run_mission_worker

# INITIALIZE REDDIT AT THE TOP (Global Scope)
client_id = os.getenv('client_id')
client_secret = os.getenv('client_secret')
user_agent = os.getenv('user_agent')

reddit = praw.Reddit(
    client_id=client_id,
    client_secret=client_secret, 
    user_agent=user_agent,
    check_for_async=False 
)

# Import helpers from config and utils
from config import get_db_connection, get_db_cursor, coc_client
from utils import (
    fetch_clan_from_db, fetch_player_from_DB, get_clan_data, 
    check_coc_clan_tag, check_coc_player_tag, get_player_data,
    ClanNotSetError, PlayerNotLinkedError, MissingPlayerTagError
)


class HelpView(ui.View):
    def __init__(self, summary_embed, full_embed):
        super().__init__(timeout=300)
        self.message = None
        self.summary_embed = summary_embed
        self.full_embed = full_embed
        self.showing_all = False
        
    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
    
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass # Message might have been deleted already
                
    @ui.button(label="Show All Commands", style=discord.ButtonStyle.blurple)
    async def toggle_help(self, interaction: discord.Interaction, button: ui.Button):
        if not self.showing_all:
            button.label = "Show Less"
            button.style = discord.ButtonStyle.gray 
            self.showing_all = True
            await interaction.response.edit_message(embed=self.full_embed, view=self)
            
        else:
            button.label = "Show All Commands"
            button.style = discord.ButtonStyle.blurple
            self.showing_all = False
            await interaction.response.edit_message(embed=self.summary_embed, view=self)
# --- 🏰 UPDATED GLOBAL VERIFIED MODAL ---
class CoCLinkModal(discord.ui.Modal, title="Link Clash of Clans Account"):
    player_tag = discord.ui.TextInput(
        label="Player Tag",
        placeholder="#2PP92G2Y",
        required=True,
        max_length=15
    )
    
    api_token = discord.ui.TextInput(
        label="API Token / Verification Token",
        placeholder="Enter your 8-digit in-game API Token",
        required=True,
        min_length=8,
        max_length=8
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        clean_tag = self.player_tag.value.strip().upper()
        if not clean_tag.startswith("#"): 
            clean_tag = f"#{clean_tag}"
            
        token = self.api_token.value.strip()

        # Check tag validity
        if await check_coc_player_tag(clean_tag):
            try:
                # 1. Verify token with Supercell
                is_verified = await coc_client.verify_player_token(clean_tag, token)
                
                if not is_verified:
                    await interaction.followup.send(
                        "❌ **Verification Failed!** The API Token you entered does not match this player tag.\n\n"
                        "**How to find your token:**\n"
                        "1. Open Clash of Clans -> Settings -> More Settings.\n"
                        "2. Scroll to the bottom and click 'API Token'.\n"
                        "3. Re-run `/link` and enter your fresh token.",
                        ephemeral=True
                    )
                    return

                # 2. Save globally (No guild_id or guild_name needed!)
                conn = get_db_connection() 
                cursor = conn.cursor(buffered=True) 
                
                cursor.execute("""
                    INSERT INTO players (discord_id, discord_username, player_tag, is_premium)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        player_tag = VALUES(player_tag),
                        discord_username = VALUES(discord_username)
                """, (
                    str(interaction.user.id), 
                    interaction.user.display_name, 
                    clean_tag, 
                    0
                ))
                conn.commit() 
                cursor.close()
                conn.close()
                
                await interaction.followup.send(f"✅ **Account Verified!** You have successfully linked **{clean_tag}** globally to your Discord profile!")
                
            except Exception as e:
                print(f"💥 DB/API Error during Link: {e}")
                await interaction.followup.send("❌ A system error occurred while saving your profile.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Invalid player tag format.", ephemeral=True)


class LinkMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)# 5-minute timeout for security
        self.cog = cog

    @discord.ui.button(label="Link CoC Account", style=discord.ButtonStyle.primary)
    async def link_coc(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Clean & Simple: Opens the modal globally.
        await interaction.response.send_modal(CoCLinkModal(self.cog))

    @discord.ui.button(label="Link Store (Cookies)", style=discord.ButtonStyle.success)
    async def link_store(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_dm = interaction.guild is None

        guide_embed = discord.Embed(
            title="Supercell Store Cookie Link Guide",
            description=(
                "Follow these simple steps on your computer to securely register your web store session. "
                "This allows the bot to automatically claim your weekly rewards!\n\n"
                "**⏳ I am waiting for your cookie text or .json file (expires in 2 minutes)...**"
            ),
            color=discord.Color.green()
        )
        
        guide_embed.add_field(
            name="Step 1: Install a Cookie Exporter",
            value="Install a [Copy Cookies](https://cookie-editor.com/) browser extension",
            inline=False
        )
        guide_embed.add_field(
            name="Step 2: Log Into Supercell Store",
            value="Go to the official [Clash of Clans Store](https://store.supercell.com/clashofclans) and sign in.",
            inline=False
        )
        guide_embed.add_field(
            name="Step 3: Export Your Cookies",
            value="Click on browser extension to copy the cookies to your clipboard.",
            inline=False
        )
        guide_embed.add_field(
            name="Step 4: Upload or Paste Here",
            value="Paste the JSON text or upload the `.json` file directly in this DM.",
            inline=False
        )

        if is_dm:
            # Removed ephemeral=True because DMs do not support ephemeral responses
            await interaction.response.send_message(embed=guide_embed)
            asyncio.create_task(self.cog.handle_cookie_upload(interaction, interaction.user.id, interaction.channel))
        else:
            try:
                dm_channel = await interaction.user.create_dm()
                await dm_channel.send(embed=guide_embed)
                
                status_embed = discord.Embed(
                    title="🔒 Security Check Sent!",
                    description=(
                        "To protect your web cookies, I have sent you a private direct message with step-by-step instructions.\n\n"
                        "**Please check your DMs to complete the registration!**"
                    ),
                    color=discord.Color.blue()
                )
                status_embed.set_footer(text="Ensure your server DM privacy settings are enabled!")
                
                await interaction.response.send_message(embed=status_embed, ephemeral=True)
                asyncio.create_task(self.cog.handle_cookie_upload(interaction, interaction.user.id, dm_channel))
                
            except discord.Forbidden:
                fail_embed = discord.Embed(
                    title="❌ DM Delivery Failed",
                    description=(
                        "I was unable to send you a Direct Message.\n\n"
                        "**How to fix this:**\n"
                        "1. Go to your **Discord User Settings**.\n"
                        "2. Select **Privacy & Safety**.\n"
                        "3. Turn ON **'Allow direct messages from server members'**.\n"
                        "4. Click the **Link Store** button again!"
                    ),
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=fail_embed, ephemeral=True)

class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    # def cog_load(self):
    #     # Start the loop when the Cog is loaded
    #     if not self.sunday_worker.is_running():
    #         self.sunday_worker.start()
    #         print("✅ Sunday Autoclaim task started.")

    # def cog_unload(self):
    #     # Stop the loop if the Cog is unloaded (prevents duplicate loops)
    #     self.sunday_worker.cancel()
    #     print("🛑 Sunday Autoclaim task stopped.")

    # @tasks.loop(hours=1)
    # async def sunday_worker(self):
    #     now = datetime.datetime.now()
        
    #     # weekday() == 6 is Sunday. hour == 10 is 10:00 AM
    #     if now.weekday() == 6 and now.hour == 10:
    #         print("🚀 [Background] Sunday Autoclaim loop triggered!")
            
    #         try:
    #             conn = get_db_connection()
    #             cursor = conn.cursor(buffered=True)
                
    #             # Fetch all premium users who have enabled the toggle
    #             # We JOIN with coc_sessions to make sure they actually have cookies linked
    #             cursor.execute("""
    #                 SELECT p.discord_id, s.cookies_json 
    #                 FROM players p
    #                 JOIN coc_sessions s ON p.discord_id = s.discord_id
    #                 WHERE p.is_premium = 1 AND p.autoclaim_enabled = 1
    #             """)
    #             targets = cursor.fetchall()
                
    #             for discord_id, cookies_str in targets:
    #                 print(f"🤖 [Background] Autoclaiming for {discord_id}...")
                    
    #                 try:
    #                     data = await run_mission_worker(discord_id, cookies_str)
                        
    #                     # 2. Notify the user via DM
    #                     user = await self.bot.fetch_user(int(discord_id))
    #                     if data.get("success"):
    #                         claimed = data.get("claimed", 0)
    #                         await user.send(f"✅ **Sunday Autoclaim:** I've checked the store and claimed **{claimed}** rewards for you!")
    #                     else:
    #                         # If it failed (expired cookies), let them know so they can fix it
    #                         await user.send(f"⚠️ **Autoclaim Failed:** Your session might have expired. Please update your cookies using `/link`.\nError: `{data.get('error')}`")
                        
    #                     # Wait 15 seconds between users to stay under Railway RAM limits
    #                     await asyncio.sleep(15)

    #                 except Exception as worker_err:
    #                     print(f"❌ Worker Error for {discord_id}: {worker_err}")
                
    #             cursor.close()
    #             conn.close()
    #         except Exception as e:
    #             print(f"💥 [Background] Sunday loop critical error: {e}")

    @app_commands.command(name="help", description="Displays command guide")
    async def help_command(self, interaction: discord.Interaction):
        """Sends a toggleable command menu."""
        
      
        summary_embed = discord.Embed(
            title="🐉 Dragon Bot | Quick Guide",
            description="**[G]** Global | **[C]** Clan/Server Only\nClick the button for the description of commands!",
            color=0x00FF00
        )
        
        summary_embed.add_field(
            name="🛡️ Clan Core", 
            value=(
                "> `[C]` `/claninfo` · `/clanmembers` · `/capitalraid` · `/previousraids` \n"
                "> `[C]` `/currentwar` · `/warlog` · `/cwlprep` · `/cwlclansearch` · `/cwlschedule` \n"
                "> `[G]` `/clansearch`"
            ),
            inline=False
        )

        summary_embed.add_field(
            name="⚔️ Player Core",
             value=(
                "> `[G]` `/playerinfo` · `/playerlevels` · `/playerheroes` \n"
                "> `[C]` `/searchmember` (Find player in clan)"
            ),
            inline=False
        )
        
        summary_embed.add_field(
            name="⚙️ Settings",
            value=(
                "> `[C]` `/setclantag` · `/adjust_reminders` · `/serverstatus` \n"
                "> `[G]` `/link` · `/unlink` (Connect CoC or Store account)"
            ),
            inline=False
        )
        summary_embed.add_field(
            name="**Extras**",
            value=(
                "> `[G]` `/flipcoin` · `/help` · `/about` · `/receiveposts` (Reddit Leaks) \n"
                
            ),
            inline=False
        )

        full_embed = discord.Embed(
            title="🐉 Dragon Bot | Master Command List",
            description="Complete list of all available commands.\n**[G]** Global | **[C]** Commands only work in clans/servers",
            color=0x00FF00
        )

        full_embed.add_field(
            name="🛡️ Clan Management",
            value=(
                "> [C] `/claninfo` — General clan overview\n"
                "> [C] `/clanmembers` — Members ranked by leagues\n"
                "> [G] `/clansearch` — Search for a clan by name\n"
                "> [C] `/capitalraid` — Current Raid Weekend progress\n"
                "> [C] `/previousraids` — History of past Raid seasons\n"
                "> [C] `/currentwar` — Stats & Info for War/CWL\n"
                "> [C] `/warlog` — Check recent war history\n"
                "> [C] `/cwlprep` — Scout matchup levels for current CWL\n"
                "> [C] `/cwlschedule` — View CWL rounds and opponents\n"
                "> [C] `/cwlclansearch` — Search opponent rosters and levels"
            ),
            inline=False
        )

        full_embed.add_field(
            name="⚔️ Player Tools",
            value=(
                "> [G] `/playerinfo` — General stats and clan-related info\n"
                "> [G] `/playerlevels` — Troops & Siege levels\n"
                "> [G] `/playerheroes` — Check heroes, pets and equipment levels\n"
                "> [C] `/searchmember` — Find a player in your current clan"
            ),
            inline=False
        )

        full_embed.add_field(
            name="⚙️ Settings & Admin",
            value=(
                "> [C] `/setclantag` — Link clan and set reminder channels\n"
                "> [C] `/adjust_reminders` — Mute War or Raid pings (Admins)\n"
                "> [C] `/serverstatus` — View current server config\n"
                "> [G] `/link` / `/unlink` — Connect/disconnect CoC tag to Discord"
            ),
            inline=False
        )

        full_embed.add_field(
            name="**Extras**",
            value=(
                "> [G] `/flipcoin` — Flips a coin \n"
                "> [G] `/about` — Displays info about Dragon Bot \n"
                "> [G] `/receiveposts` — Receive posts from Reddit; default subreddit is ClashOfClansLeaks\n"
                "> [G] `/help` — This command"
                
            ),
            inline=False
        )

        full_embed.set_footer(text="Tip: Use /setclantag to setup your server | /link to connect your account.")

        # Re-using your HelpView logic to toggle between them
        view = HelpView(summary_embed, full_embed)
        await interaction.response.send_message(embed=summary_embed, view=view)
        view.message = await interaction.original_response()

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

    @app_commands.command(name="serverstatus", description="Get the server configuration and status")
    async def server_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(buffered=True)
            guild_id = str(interaction.guild.id)
            
            # Updated to fetch the new custom interval values from the database
            cursor.execute(
                "SELECT clan_tag, war_channel_id, raid_channel_id, war_reminder_1, war_reminder_2 FROM servers WHERE guild_id = %s", 
                (guild_id,)
            )
            row = cursor.fetchone()
            
            if row:
                # Keep the formatting clean, but show raw text if empty
                raw_clan_tag = row[0]
                clan_tag = f"`{raw_clan_tag}`" if raw_clan_tag else "`❌ Not Set`"
                war_mention = f"<#{row[1]}>" if row[1] else "`❌ Not Configured`"
                raid_mention = f"<#{row[2]}>" if row[2] else "`❌ Not Configured`"
                
                # Assign custom intervals, mapping to defaults if somehow missing
                t1_hours = row[3] if row[3] is not None else 4
                t2_hours = row[4] if row[4] is not None else 1
                
                timer_details = f"• Timer 1: `{t1_hours}h left`"
                if t2_hours > 0:
                    timer_details += f"\n• Timer 2: `{t2_hours}h left` (Ping Active)"
                else:
                    timer_details += "\n• Timer 2: `Disabled`"
            else:
                clan_tag = "`❌ Run /setclantag to configure`"
                war_mention = "`❌ Not Configured`"
                raid_mention = "`❌ Not Configured`"
                timer_details = "`❌ Not Configured`"

            # 2. Fetch Linked Players
            # 2. Fetch All Globally Linked Players
            cursor.execute("SELECT discord_username, player_tag, discord_id FROM players")
            all_linked_players = cursor.fetchall()
            
            # Filter to only show players who are actually members of this server
            server_players = []
            for username, player_tag, discord_id in all_linked_players:
                if interaction.guild.get_member(int(discord_id)) is not None:
                    server_players.append(f"• @{username} (`{player_tag}`)")
            
            player_info = "\n".join(server_players) if server_players else "` No Linked Members in this Server `"

            # 3. Build the Polished Embed
            embed = discord.Embed(
                title=f"🛡️ {interaction.guild.name} Configuration",
                color=0x3498db,
                timestamp=interaction.created_at
            )
            
            embed.add_field(name="Current Clan", value=f"{clan_tag}", inline=False)
            embed.add_field(name="⚔️ War Reminders Channel", value=war_mention, inline=True)
            embed.add_field(name="🏰 Raid Reminders Channel", value=raid_mention, inline=True)
            
            # Clear new field displaying custom configuration states
            embed.add_field(name="⏱️ Custom War Intervals", value=timer_details, inline=False)

            embed.add_field(name="Linked Members", value=player_info, inline=False)
            
            embed.set_footer(text=f"Serving {len(self.bot.guilds)} servers | {len(self.bot.users)} users")
            
            await interaction.followup.send(embed=embed)

            cursor.close()
            conn.close() # Always close the connection too!
        except Exception as e:
            print(f"Error in serverstatus: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error fetching status: `{e}`")
    @app_commands.command(name='setclantag', description="Set the clan tag and custom reminder channels/times")
    @app_commands.describe(
        new_tag="The #ClanTag", 
        war_channel="Optional: Channel for war reminders",
        raid_channel="Optional: Channel for capital raid reminders",
        reminder_hours_1="Optional: Primary war reminder time (e.g. 6 for 6h left)",
        reminder_hours_2="Optional: Secondary war reminder time (e.g. 2 for 2h left. Set 0 to disable)"
    )
    async def set_clan_tag(
        self, 
        interaction: discord.Interaction, 
        new_tag: str, 
        war_channel: discord.TextChannel = None,
        raid_channel: discord.TextChannel = None,
        reminder_hours_1: int = None,
        reminder_hours_2: int = None
    ):
        clean_tag = new_tag.strip().upper()
        if not clean_tag.startswith("#"): 
            clean_tag = f"#{clean_tag}"
        
        if not await check_coc_clan_tag(clean_tag):
            return await interaction.response.send_message("❌ Invalid Clan Tag. Please check the tag in-game.", ephemeral=True)

        cursor = get_db_cursor()
        guild_id = str(interaction.guild.id)
        
        # SQL Updated to handle upserts for the new configuration columns
        sql = """
            INSERT INTO servers (guild_id, guild_name, clan_tag, war_channel_id, raid_channel_id, war_reminder_1, war_reminder_2)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                clan_tag = VALUES(clan_tag),
                guild_name = VALUES(guild_name),
                war_channel_id = COALESCE(VALUES(war_channel_id), war_channel_id),
                raid_channel_id = COALESCE(VALUES(raid_channel_id), raid_channel_id),
                war_reminder_1 = COALESCE(VALUES(war_reminder_1), war_reminder_1),
                war_reminder_2 = COALESCE(VALUES(war_reminder_2), war_reminder_2)
        """
        
        war_id = str(war_channel.id) if war_channel else None
        raid_id = str(raid_channel.id) if raid_channel else None
        
        cursor.execute(sql, (guild_id, interaction.guild.name, clean_tag, war_id, raid_id, reminder_hours_1, reminder_hours_2))

        get_db_connection().commit() 
        cursor.close()
        msg = f"✅ **Clan Linked:** `{clean_tag}`\n"
        if war_channel: msg += f"War Reminders: {war_channel.mention}\n"
        if raid_channel: msg += f"Raid Reminders: {raid_channel.mention}\n"
        if reminder_hours_1 is not None: msg += f"Custom Timer 1: Set to **{reminder_hours_1} hours** remaining.\n"
        if reminder_hours_2 is not None: 
            msg += f"Custom Timer 2: Set to **{reminder_hours_2} hours** remaining.\n" if reminder_hours_2 > 0 else "⏱️ Custom Timer 2: **Disabled**.\n"
        
        await interaction.response.send_message(msg)

    # --- STORE SESSION DATABASE HELPERS ---
    def _get_user_session(self, discord_id: str):
        """Fetches the registered Supercell Store cookie session for a Discord user."""
        # Reuses your existing get_db_connection helper!
        conn = get_db_connection()
        cursor = conn.cursor(buffered=True)
        try:
            cursor.execute(
                "SELECT cookies_json FROM coc_sessions WHERE discord_id = %s", 
                (discord_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close()
            conn.close()

    def _save_user_session(self, discord_id: str, cookies_json: str):
        """Saves or updates a Discord user's cookie session."""
        # Reuses your existing get_db_connection helper!
        conn = get_db_connection()
        cursor = conn.cursor(buffered=True)
        try:
            query = """
                INSERT INTO coc_sessions (discord_id, cookies_json)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE 
                    cookies_json = VALUES(cookies_json)
            """
            cursor.execute(query, (discord_id, cookies_json))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    # --- UNIFIED INTERACTIVE LINK COMMAND ---
    @app_commands.command(name='link', description="Link your Clash of Clans account or Supercell Store.")
    async def link(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚔️ Clash of Clans Integration Menu",
            description=(
                "Choose an integration method below to link your profiles to the bot:\n\n"
                "**Link CoC Account:** Links your in-game profile to your Discord Account (requires playertag and API)\n"
                "**Link SuperCell Store :**Register your Supercell Store session for automatic reward collection!"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Manage your active profiles easily!")
        await interaction.response.send_message(embed=embed, view=LinkMenuView(self), ephemeral=True)

    # --- SECURE BACKGROUND COOKIE PROCESSOR ---
    async def handle_cookie_upload(self, interaction, user_id, target_channel=None):
        """Background listener waiting for the user to paste cookies or upload a file in DMs."""
        def check(m):
            # Matches any DM message sent by the target user
            return m.author.id == user_id and m.guild is None

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120.0)
            
            # Extract content from attachment OR text message
            if len(msg.attachments) > 0:
                attachment = msg.attachments[0]
                file_bytes = await attachment.read()
                file_str = file_bytes.decode("utf-8")
            else:
                file_str = msg.content.strip()

            # Clean markdown code blocks if user sends ```json ... ```
            if file_str.startswith("```"):
                lines = file_str.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                file_str = "\n".join(lines).strip()

            # Validate JSON format
            parsed_cookies = json.loads(file_str)
            if not isinstance(parsed_cookies, list):
                raise ValueError("Cookie format must be a JSON array/list.")

            # Save session to DB
            self._save_user_session(str(user_id), json.dumps(parsed_cookies))

            success_text = "🎉 **Success!** Your Supercell Store session cookies are verified and linked securely. You can now type `/claim` in any server channel!"
            await msg.channel.send(success_text)

        except asyncio.TimeoutError:
            timeout_text = "⏰ **Timed Out:** You didn't send your cookies within 2 minutes. Click 'Link Store' in the server menu to try again!"
            if target_channel:
                await target_channel.send(timeout_text)
        except (json.JSONDecodeError, ValueError) as err:
            err_text = f"❌ **Registration Failed:** Invalid cookie JSON format. Make sure you paste the full JSON array or upload the `.json` file!\n\n`Error: {err}`"
            if target_channel:
                await target_channel.send(err_text)
        except Exception as e:
            print(f"💥 System/DB Error loading session: {e}")
            err_text = f"❌ **System Error:** Failed to link your store profile: `{e}`"
            if target_channel:
                await target_channel.send(err_text)
                
    # --- UNIFIED GLOBAL UNLINK COMMAND ---
    @app_commands.command(name='unlink', description="Unlink your Clash of Clans account globally from the bot.")
    async def unlink(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            conn = get_db_connection()
            cursor = conn.cursor(buffered=True)
            
            # Deletes their global link mapping
            cursor.execute(
                "DELETE FROM players WHERE discord_id = %s", 
                (str(interaction.user.id),)
            )
            conn.commit()
            
            if cursor.rowcount > 0:
                await interaction.followup.send("✅ Your Clash of Clans account has been cleanly unlinked from the bot.")
            else:
                await interaction.followup.send("❌ You do not have an account linked to the bot.")
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"DB Error in Unlink: {e}")
            await interaction.followup.send("❌ An error occurred while unlinking.")

    @app_commands.command(
        name="claim", 
        description="Manually claims rewards and checks mission progress for your registered account."
    )
    async def claim(self, interaction: discord.Interaction):
        print(f"\n📥 [Discord] /claim command triggered by {interaction.user.name}!")
        await interaction.response.defer(thinking=True)

        try:
            cookies_json_str = self._get_user_session(str(interaction.user.id))
            
            if not cookies_json_str:
                print(f"❌ [Discord] {interaction.user.name} is not registered.")
                embed = discord.Embed(
                    title="⚠️ Registration Required",
                    description=(
                        "You haven't linked a Supercell Store session to your Discord account yet!\n\n"
                        "**How to register:**\n"
                        "1. Run `/link` and click **Link Store (Cookies)**.\n"
                        "2. Drop your exported cookie file into your secure DM channel!"
                    ),
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return

            print(f"🚀 [Discord] Running Playwright worker for {interaction.user.name}...")
            data = await run_mission_worker(str(interaction.user.id), cookies_json_str)
            print("🛰️ [Discord] Playwright worker finished execution.")

            if not data.get("success", False):
                error_msg = data.get("error", "Unknown Error")
                print(f"❌ [Discord] Worker failed: {error_msg}")
                embed = discord.Embed(
                    title="⚠️ Claim Failed",
                    description=f"Reason: `{error_msg}`\n\nIf your session expired, run `/link` and update your store cookies again.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

            claimed_rewards = data["claimed"]
            embed = discord.Embed(
                title="Store Claim Status",
                description=f"Successfully claimed **{claimed_rewards}** reward(s)!",
                color=discord.Color.green() if claimed_rewards > 0 else discord.Color.gold()
            )

            if data.get("next_reward"):
                embed.add_field(
                    name="Next Item Progress", 
                    value=f"{data['next_reward']}", 
                    inline=False
                )

            if data.get("missions"):
                all_completed = True
                
                for mission in data["missions"]:
                    # Checks if the scraper flagged it as completed
                    is_completed = "COMPLETED" in mission["progress"].upper()
                    if not is_completed:
                        all_completed = False
                        
                    status_emoji = "✅" if is_completed else "⏳"
                    
                    embed.add_field(
                        name=f"{status_emoji} {mission['title']}",
                        value=f"Progress: `{mission['progress']}` | Reward: `{mission['reward']}`",
                        inline=False
                    )
                
                # Dynamic congrats message
                if all_completed:
                    embed.description = f"Successfully claimed **{claimed_rewards}** reward(s)!\n\n🎉 **You have completed all active missions!**"
            else:
                embed.add_field(
                    name="✅ All Missions Completed!",
                    value="No active missions found. You've likely finished them all for this week!",
                    inline=False
                )

            # --- Inject the Live Store Timer ---
            if data.get("season_timer"):
                embed.set_footer(text=f"⏳ Store Missions Reset In: {data['season_timer']}")
            else:
                embed.set_footer(text="Missions on the store reset every Monday.")
                
            await interaction.followup.send(embed=embed)

            embed.set_footer(text="Missions on the store reset every Monday.")
            await interaction.followup.send(embed=embed)
            print("✅ [Discord] Embed successfully sent to user.")

        except Exception as e:
            print(f"💥 [Discord] CRITICAL ERROR in slash command execution: {e}")
            try:
                await interaction.followup.send(f"⚠️ A critical error occurred inside the bot: `{e}`")
            except Exception:
                pass

    # @app_commands.command(name="autoclaim", description="Toggle automatic reward claiming on Sundays.")
    # @app_commands.describe(status="Turn autoclaim ON or OFF")
    # @app_commands.choices(status=[
    #     app_commands.Choice(name="On", value=1),
    #     app_commands.Choice(name="Off", value=0)
    # ])
    # async def autoclaim_toggle(self, interaction: discord.Interaction, status: app_commands.Choice[int]):
    #     await interaction.response.defer(ephemeral=True)
        
    #     user_id = str(interaction.user.id)
    #     requested_val = status.value  # 1 for On, 0 for Off
        
    #     conn = None
    #     cursor = None
        
    #     try:
    #         conn = get_db_connection()
    #         cursor = conn.cursor(buffered=True)
            
    #         # Fetch Current Toggle State
    #         cursor.execute("SELECT autoclaim_enabled FROM players WHERE discord_id = %s", (user_id,))
    #         result = cursor.fetchone()
            
    #         # Check if user actually exists in the database
    #         if not result:
    #             await interaction.followup.send(
    #                 "❌ You must link your account using `/link` before you can toggle autoclaim.", ephemeral=True
    #             )
    #             return

    #         current_val = result[0] # Current DB value (0 or 1)

    #         # Check for Redundancy
    #         if requested_val == current_val:
    #             state_text = "enabled ✅" if current_val == 1 else "disabled ❌"
    #             await interaction.followup.send(f"Your autoclaim is already {state_text}.")
    #             return

    #         # Update the Toggle
    #         cursor.execute(
    #             "UPDATE players SET autoclaim_enabled = %s WHERE discord_id = %s",
    #             (requested_val, user_id)
    #         )
    #         conn.commit()
            
    #         if requested_val == 1:
    #             await interaction.followup.send(
    #                 "Autoclaim ENABLED ✅\nYour missions will now be checked automatically every Sunday at 10 AM."
    #             )
    #         else:
    #             await interaction.followup.send(
    #                 "Autoclaim DISABLED ❌\nAutomatic Sunday checks have been turned off for your account."
    #             )
                
    #     except Exception as e:
    #         print(f"Error in autoclaim_toggle: {e}")
    #         await interaction.followup.send(f"❌ Error updating settings: `{e}`")
    #     finally:
    #         # ✅ GUARANTEED CLEANUP: This runs even if we hit a 'return' statement above!
    #         if cursor: cursor.close()
    #         if conn: conn.close()
    
    @app_commands.command(name="adjust_reminders", description="Set or disable background reminders and custom times")
    @app_commands.describe(
        war_channel="Set a new channel for war reminders",
        raid_channel="Set a new channel for capital raid reminders",
        disable="Select a reminder type to disable completely",
        reminder_hours_1="Primary war reminder time (e.g. 6 for 6h left)",
        reminder_hours_2="Secondary war reminder time (e.g. 2 for 2h left. Set 0 to disable)"
    )
    @app_commands.choices(disable=[
        app_commands.Choice(name="⚔️ Disable War Reminders", value="war"),
        app_commands.Choice(name="🏰 Disable Raid Reminders", value="raid"),
        app_commands.Choice(name="🚫 Disable Both", value="both")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def adjust_reminders(
        self, 
        interaction: discord.Interaction, 
        war_channel: discord.TextChannel = None,
        raid_channel: discord.TextChannel = None,
        disable: app_commands.Choice[str] = None,
        reminder_hours_1: int = None,
        reminder_hours_2: int = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        conn = get_db_connection()
        cursor = conn.cursor(buffered=True)
        guild_id = str(interaction.guild.id)
        
        # 1. Check if the server is linked first
        cursor.execute("SELECT clan_tag FROM servers WHERE guild_id = %s", (guild_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return await interaction.followup.send("❌ Please link a clan using `/setclantag` before adjusting reminders.")

        updates = []
        params = []
        msg_parts = []
        
        # 2. Handle Disable Arguments
        if disable:
            if disable.value in ("war", "both"):
                updates.append("war_channel_id = NULL")
                msg_parts.append("⚔️ War reminders disabled.")
            if disable.value in ("raid", "both"):
                updates.append("raid_channel_id = NULL")
                msg_parts.append("🏰 Raid reminders disabled.")
                
        # 3. Handle Channel Updates (Overrides if you try to set AND disable at the same time)
        if war_channel and not (disable and disable.value in ("war", "both")):
            updates.append("war_channel_id = %s")
            params.append(str(war_channel.id))
            msg_parts.append(f"⚔️ War reminders set to {war_channel.mention}.")
            
        if raid_channel and not (disable and disable.value in ("raid", "both")):
            updates.append("raid_channel_id = %s")
            params.append(str(raid_channel.id))
            msg_parts.append(f"🏰 Raid reminders set to {raid_channel.mention}.")
            
        # 4. Handle Custom Timers
        if reminder_hours_1 is not None:
            updates.append("war_reminder_1 = %s")
            params.append(reminder_hours_1)
            msg_parts.append(f"⏱️ Timer 1 set to **{reminder_hours_1} hours** remaining.")
            
        if reminder_hours_2 is not None:
            updates.append("war_reminder_2 = %s")
            params.append(reminder_hours_2)
            if reminder_hours_2 > 0:
                msg_parts.append(f"⏱️ Timer 2 set to **{reminder_hours_2} hours** remaining.")
            else:
                msg_parts.append("⏱️ Timer 2 **disabled**.")

        # 5. Stop if no options were selected
        if not updates:
            cursor.close()
            conn.close()
            return await interaction.followup.send("⚠️ You didn't provide any changes to make! Please select a channel to set, an option to disable, or a timer to update.")

        # 6. Execute Dynamic SQL
        try:
            sql = f"UPDATE servers SET {', '.join(updates)} WHERE guild_id = %s"
            params.append(guild_id)
            
            cursor.execute(sql, tuple(params))
            conn.commit()
            
            await interaction.followup.send("✅ **Reminders Updated Successfully:**\n- " + "\n- ".join(msg_parts))
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update settings: {e}")
        finally:
            cursor.close()
            conn.close()
    
async def setup(bot):
    await bot.add_cog(BotCommands(bot))
