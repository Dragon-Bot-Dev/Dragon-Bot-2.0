
import discord
import time
import asyncio
from discord.ext import commands, tasks
from discord import app_commands, Embed

# Import helpers from your toolbox
from config import get_db_cursor, coc_client, get_safe_cursor
from utils import (
    fetch_clan_from_db, get_clan_data, get_war_log_data,
    get_capital_raid_data, calculate_raid_season_stats, 
    calculate_medals, format_month_day_year, ClanNotSetError,
    fetch_player_from_DB, PlayerNotLinkedError, MissingPlayerTagError
)

def add_spaces(text):
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', text)


class ClanCommands(commands.Cog):
    def __init__(self, bot, coc_client): #
        self.bot = bot
        self.coc_client = coc_client 

    # --- CLAN INFO & LOOKUP ---

    @app_commands.command(name="claninfo", description="Retrieve information about the clan")
    async def clan_info(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            tag = fetch_clan_from_db(interaction.guild.id)
            clan_data = await get_clan_data(tag)
            description = clan_data.description or "No description provided."
            timestamp   = int(time.time() // 60 * 60)  # Round to minute
            embed = Embed(
                title="Clan Information",
                description=f"Last updated: <t:{timestamp}:R>",
                color=0x3498db
            )
            
            embed.set_thumbnail(url=clan_data.badge.url)
            embed.add_field(name="Name", value=clan_data.name, inline=True)
            embed.add_field(name="Tag", value=clan_data.tag, inline=True)

            # Use .member_count for the number of members
            embed.add_field(name="Members", value=f":bust_in_silhouette: {clan_data.member_count} / 50", inline=False)

            # Update field names to match coc.py object attributes
            embed.add_field(name="Level", value=clan_data.level, inline=True)
            
            # War frequency is accessed via .war_frequency
            freq_text = add_spaces(str(clan_data.war_frequency))
            embed.add_field(name="War Frequency", value=freq_text, inline=True)

            embed.add_field(name="Description", value=clan_data.description, inline=False)
            embed.add_field(name="Min. TH Level", value=str(clan_data.required_townhall), inline=True)
            embed.add_field(name="Req. Trophies", value=f":trophy: {clan_data.required_trophies}", inline=True)
            embed.add_field(name="Req. Builder Base Trophies", value=f":trophy: {clan_data.required_builder_base_trophies}", inline=True)

            if clan_data.public_war_log:
                embed.add_field(
                    name="War Win/Draw/Loss Record",
                    value=f"{clan_data.war_wins} / {clan_data.war_ties} / {clan_data.war_losses}",
                    inline=True
                )
                embed.add_field(name="War Streak", value=str(clan_data.war_win_streak), inline=True)

            # Access nested names via their respective objects
            if clan_data.war_league:
                embed.add_field(name="CWL League", value=clan_data.war_league.name, inline=False)
            
            if clan_data.capital_league:
                embed.add_field(name="Clan Capital League", value=clan_data.capital_league.name, inline=True)
                
            location_name = clan_data.location.name if clan_data.location else "Unknown"
            embed.add_field(name="Location", value=f":globe_with_meridians: {location_name}", inline=False)

            embed.set_footer(text=f"Requested by {interaction.user.name}")

            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="searchclan", description="Search for clans by name")
    async def lookup_clans(self, interaction: discord.Interaction, 
    clanname: str, 
    war_frequency: str = None, 
    min_members: int = None, 
    max_members: int = None, 
    minclan_level: int = None, 
    limits: int = 1):
        await interaction.response.defer()
        try:
            clans = await coc_client.search_clans(name=clanname, limit=max(1, min(limits, 3)))
            if not clans:
                return await interaction.followup.send("No clans found.")

            for clan in clans:
                embed = Embed(
                    title=f"Clan: {clan.name}", 
                    color=0x3498db
                )
                embed.set_thumbnail(url=clan.badge.url)
                embed.add_field(name="Name", value=clan.name, inline=True)
                embed.add_field(name="Tag", value=clan.tag, inline=True)
                embed.add_field(name="Members", value=f":bust_in_silhouette: {clan.member_count} / 50", inline=False)
                embed.add_field(name="Clan Level", value=clan.level, inline=True)
                embed.add_field(name="Clan Points", value=clan.points, inline=True)
                embed.add_field(name="Min TownHall", value=str(clan.required_townhall), inline=False)
                embed.add_field(name="Req. Trophies", value=f":trophy: {clan.required_trophies}", inline=True)
                embed.add_field(name="Req. Builder Trophies", value=f":trophy: {clan.required_builder_base_trophies}", inline=True)

                if clan.public_war_log:
                    embed.add_field(
                        name="Win/Loss Record", 
                        value=f"{clan.war_wins} :white_check_mark: / {clan.war_losses} :x:", 
                        inline=False
                    )

                location_name = clan.location.name if clan.location else "N/A"
                embed.add_field(name="Location", value=f":globe_with_meridians: {location_name}", inline=False)
                
                await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    # --- MEMBER COMMANDS ---

    @app_commands.command(name="clanmembers", description="View ranked clan members")
    @app_commands.describe(ranking="List by League(default), TH, role, tag")
    async def clan_members(self, interaction: discord.Interaction, ranking: str = "LEAGUES"):
        await interaction.response.defer()
        try:
            tag = fetch_clan_from_db(interaction.guild.id)
            members = await coc_client.get_members(tag)

            member_list = f"```yaml\n** Members Ranked by {ranking}: ** \n"
            
            rank = ranking.lower()
            if rank in ["leagues", "league"]:
            # coc.py results are often sorted by rank/league by default
                sorted_members = members
            elif rank == "th":
                sorted_members = sorted(members, key=lambda m: m.town_hall, reverse=True)
            elif rank == "role":
                # FIX 2: Use exact coc.py internal names for the keys
                # 'admin' is the internal name for Elder
                role_order = {
                    "leader": 1, 
                    "co_leader": 2, 
                    "elder": 3, 
                    "member": 4
                }
                # Use m.role.name to match the internal strings above
                sorted_members = sorted(members, key=lambda m: role_order.get(m.role.name, 5))
            elif rank == "tag":
                sorted_members = members
                #sorted_members = sorted(members, key=lambda m: m.tag)
            else:
                await interaction.followup.send("Invalid ranking criteria.")
                return

            # 4. Generating member list using clean object properties
            for m in sorted_members:
                # Map role names to your preferred display format
                role_display = str(m.role)
                #print(role_display)
                #print(f"Member: {m.name} | Internal Role Name: {m.role.name}")
                
                if rank == "tag":
                    member_info = f"{m.clan_rank}. {m.name}, {m.tag}\n"
                elif rank in ["leagues", "league"]:
                    member_info = f"{m.clan_rank}. {m.name}, {role_display}, {m.league.name}\n"
                else: # TH or ROLE
                    member_info = f"{m.clan_rank}. {m.name}, {role_display}, [TH{m.town_hall}]\n"

                # Check message length (Discord 2000 char limit)
                if len(member_list) + len(member_info) > 1990:
                    break
                member_list += member_info

            member_list += "```"
            await interaction.followup.send(member_list)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="searchmember", description="Get info for a specific clan member")
    async def lookup_member(self, interaction: discord.Interaction, user: discord.Member = None, username: str = None):
        await interaction.response.defer()
        try:
            cursor = get_db_cursor() 
            guild_id = str(interaction.guild.id)
            tag = fetch_clan_from_db(interaction.guild.id)
            clan_data = await get_clan_data(tag)
        except Exception as e:
            return await interaction.followup.send(
                f"Error getting clan information: {e}",
                ephemeral=True
        )

        target = None
        timestamp = int(time.time())

        # 2. Use Object Attributes (Dot Notation) to find the member
        # coc.Clan objects use .members instead of ['memberList']
        if username:
            for member in clan_data.members:
                if member.name.lower() == username.lower():
                    target = member
                    break

        elif user:
            try:
                linked_tag = fetch_player_from_DB(guild_id, user, None)
                target = next((m for m in clan_data.members if m.tag.upper() == linked_tag.upper()), None)

                if not target:
                    return await interaction.followup.send(f"Member with tag `{linked_tag}` is linked, but not currently in this clan.", ephemeral=True)    
            except Exception as e:
                print(f"DEBUG: Lookup error for user: {e}")
                return await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
            except PlayerNotLinkedError as e:
                return await interaction.followup.send(str(e), ephemeral=True)
            except MissingPlayerTagError as e:
                return await interaction.followup.send(str(e), ephemeral=True)

        if target:
            # Mapping coc.Role object to display strings
            role_str = str(target.role).lower()
            role_display = "Elder" if role_str == 'admin' else "Co-Leader" if role_str == 'coleader' else role_str.capitalize()

            embed = discord.Embed(
                title=f"{target.name} — {target.tag}",
                color=discord.Color.green(),
                description=f"Last updated: <t:{timestamp}:R>"
            )
            
            # Access icons through nested objects
            if target.league:
                embed.set_thumbnail(url=target.league.icon.url)
                
            # Update field names to match coc.py object attributes
            embed.add_field(name="TownHall Level", value=str(target.town_hall), inline=True)
            embed.add_field(name="Clan Rank", value=str(target.clan_rank), inline=False)
            embed.add_field(name="Role", value=role_display, inline=True)
            
            league_name = target.league.name if target.league else "Unranked"
            embed.add_field(name="Trophies", value=f":trophy: {target.trophies} | {league_name}", inline=False)
            
            bb_league = target.builder_base_league.name if target.builder_base_league else "Unranked"
            embed.add_field(name="Builder Base Trophies", value=f":trophy: {target.builder_base_trophies} | {bb_league}", inline=False)
            
            # donationsReceived is shortened to .received in coc.py
            embed.add_field(name="Donations", value=f"Given: {target.donations} | Received: {target.received}", inline=False)

            return await interaction.followup.send(embed=embed)

        return await interaction.followup.send(
            f'User "{username or user.display_name}" not found in the clan.',
            ephemeral=True
        )

    # --- RAID COMMANDS ---

    @app_commands.command(name="capitalraid", description="Current raid info")
    async def capital_raid(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            tag = fetch_clan_from_db(interaction.guild.id)
            data = await calculate_raid_season_stats(tag)
            if not data: return await interaction.followup.send("No raid found.")
            state = data['state']
            res = (
        f"```yaml\n"
        f"Status: {data['state']}\n"
        f"Start Time: {data['start']}\n"
        f"End Time: {data['end']}\n"
        f"Medals Earned: {data['medals']} | Total Loot: {data['loot']:,}\n"
        f"Member Stats:\n{data['stats_text']}\n"
        f"```"
            )
            await interaction.followup.send(res)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
            
    @app_commands.command(name="previousraids", description="Retrieve capital raid history")
    @app_commands.describe(limit="Number of raids to retrieve (2-5)")
    async def previous_raids(self, interaction: discord.Interaction, limit: int = 2):
        """Retrieves history of past raid seasons."""
        await interaction.response.defer()
        try:
            tag = fetch_clan_from_db(interaction.guild.id)
            raid_data = await get_capital_raid_data(tag)
            seasons = raid_data.get('items', [])

            if not seasons:
                return await interaction.followup.send("No seasons found.")

            limit = max(2, min(limit, 5)) 

            for i, entry in enumerate(seasons[:limit]):
                state = entry.get('state', 'N/A')
                start_time = format_month_day_year(entry.get('startTime', 'N/A'))
                end_time = format_month_day_year(entry.get('endTime', 'N/A'))
                capital_total_loot = entry.get('capitalTotalLoot', 0)
                attacks = entry.get('totalAttacks', 0)
                districts_destroyed = entry.get('enemyDistrictsDestroyed', 0)
                
                # Use the helper to get either the estimate or the final count
                medal_display = calculate_medals(entry)

                colors = 0xffff00 if state == 'ongoing' else 0x1abc9c 

                embed = Embed(
                    title=f"Raid #{i + 1}:",
                    color=colors
                )
                embed.add_field(name="Status", value=state.capitalize(), inline=False)
                embed.add_field(name="Start Date", value=start_time, inline=True)
                embed.add_field(name="End Date", value=end_time, inline=True)
                embed.add_field(name="Capital Loot Obtained", value=f"{capital_total_loot:,}", inline=False)
                embed.add_field(name="Total Attacks", value=f"{attacks:,}", inline=True)
                embed.add_field(name="Districts Destroyed", value=districts_destroyed, inline=True)
                
                # Display the result from the helper
                embed.add_field(name="Raid Medals", value=medal_display, inline=False)
                
                await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

class RaidPatrol(commands.Cog):
    def __init__(self, bot, coc_client):
        self.bot = bot
        self.coc_client = coc_client

    async def cog_load(self):
        # This only manages the raid_check task
        if not self.raid_check.is_running():
            self.raid_check.start()
            print("🏰 Raid Task: Started.")

    def cog_unload(self):
        self.raid_check.cancel()
        print("🔌 Raid Task: Stopped.")

    @tasks.loop(minutes=20)
    async def raid_check(self):
        # 1. HEARTBEAT & DB ACQUISITION
        print("--- [Raid Reminder Heartbeat] ---")
        cursor = await get_safe_cursor(retries=3, delay=5)
        if not cursor:
            return

        try:
            # Fetch all servers with raid tracking enabled
            cursor.execute("SELECT clan_tag, guild_id, raid_channel_id, last_raid_reminder FROM servers")
            tracked_servers = cursor.fetchall()

            for tag, guild_id, raid_channel_id, last_sent in tracked_servers:
                if not tag or not raid_channel_id: 
                    continue

                try:
                    # 2. FETCH DATA (Raid log returns a list; we want the current one)
                    raids = await self.coc_client.get_raid_log(tag, limit=1)
                    if not raids:
                        continue
                    raid = raids[0]

                    # 3. RESET LOGIC: Clear DB flag if raid weekend ended
                    if raid.state != "ongoing":
                        if last_sent is not None:
                            cursor.execute("UPDATE servers SET last_raid_reminder = NULL WHERE clan_tag = %s", (tag,))
                            cursor.connection.commit()
                        continue
                    
                    # 4. TIME & TRIGGER LOGIC (24h and 6h windows)
                    seconds_left = raid.end_time.seconds_until
                    hours_left = seconds_left / 3600
                    
                    reminder_type = "None"
                    if hours_left <= 6:
                        reminder_type = "6h"
                    elif hours_left <= 24:
                        reminder_type = "24h"

                    # TRIGGER GATE: Mirroring the War Reminder's "Forward-Only" flow
                    if reminder_type == "None": continue
                    if (reminder_type == "6h" and last_sent == "6h"): continue
                    if (reminder_type == "24h" and last_sent in ["24h", "6h"]): continue

                    # 5. SLACKER IDENTIFICATION (Using your linked Discord accounts)
                    cursor.execute("SELECT player_tag, discord_id FROM players WHERE guild_id = %s", (str(guild_id),))
                    links = {row[0]: row[1] for row in cursor.fetchall()}
                    
                    unattacked_lines = []
                    # In raids, members can have up to 6 attacks
                    for m in raid.members:
                        if m.attack_count < 6:
                            d_id = links.get(m.tag)
                            mention = f"<@{d_id}>" if d_id else f"**{m.name[:10]}**"
                            unattacked_lines.append(f"• {mention} ({m.attack_count}/6 hits)")

                    # 6. SEND REMINDER
                    if unattacked_lines:
                        channel = self.bot.get_channel(int(raid_channel_id)) or await self.bot.fetch_channel(int(raid_channel_id))
                        
                        # Timestamp Bridge Fix (Matching War Logic)
                        try:
                            unix_ts = int(raid.end_time.time.timestamp())
                        except AttributeError:
                            unix_ts = int(raid.end_time.timestamp())

                        is_final = (reminder_type == "6h")
                        time_label = "🚨 FINAL 6 HOURS" if is_final else "⏳ 24 HOURS REMAINING"
                        
                        embed = discord.Embed(
                            title=f"🏰 {time_label}: Capital Raid",
                            description="The Raid Weekend is closing! Finish your attacks for maximum Clan Medals.",
                            color=0xFF4500 if is_final else 0xFFCC00
                        )
                        
                        # Fallback and 1024-char safety slice
                        val = "\n".join(unattacked_lines[:25]) or "Everyone has finished!"
                        embed.add_field(name="Pending Attacks", value=val[:1024], inline=False)
                        
                        embed.add_field(name="💰 Looted", value=f" `{raid.capital_resources_looted:,}`", inline=True)
                        embed.add_field(name="⏳ Ends", value=f"<t:{unix_ts}:R>", inline=True)
                        embed.set_footer(text=f"Clan Tag: {tag}")

                        await channel.send(embed=embed)
                        print(f"✅ SUCCESS: Sent {reminder_type} raid reminder for {tag}")

                    # 7. UPDATE DATABASE PERSISTENCE
                    cursor.execute("UPDATE servers SET last_raid_reminder = %s WHERE clan_tag = %s", (reminder_type, tag))
                    cursor.connection.commit()

                except Exception as clan_error:
                    print(f"❌ Error for raid tag {tag}: {clan_error}")
            
        except Exception as e:
            print(f"💥 Raid Task Error: {e}")
        finally:
            if cursor:
                cursor.close()


    @raid_check.before_loop
    async def before_raid_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="test_raid_reminder", description="DEBUG: Preview Raid Weekend stats & logic")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_raid_reminder(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        cursor = await get_safe_cursor(retries=3, delay=5)
        try:
            guild_id = str(interaction.guild.id)
            
            # 1. FETCH CONFIG
            cursor.execute("SELECT clan_tag, raid_channel_id, last_raid_reminder FROM servers WHERE guild_id = %s", (guild_id,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                return await interaction.followup.send("❌ Clan tag not configured in DB.")
            
            clan_tag, raid_channel_id, last_sent = row

            # 2. FETCH RAID DATA (list-based await, not async for)
            raids = await self.coc_client.get_raid_log(clan_tag, limit=1)
            if not raids:
                return await interaction.followup.send("❌ No raid history found for this tag.")
            
            raid = raids[0]
            
            # 3. SIMULATE TRIGGER LOGIC
            is_ongoing = (raid.state == "ongoing")
            seconds_left = raid.end_time.seconds_until
            hours_left = seconds_left / 3600
            
            simulated_window = "None"
            if is_ongoing:
                if hours_left <= 6: simulated_window = "6h"
                elif hours_left <= 24: simulated_window = "24h"

            # Check if the loop would actually fire based on the DB flag
            will_fire = False
            if simulated_window == "6h" and last_sent != "6h":
                will_fire = True
            elif simulated_window == "24h" and last_sent not in ["24h", "6h"]:
                will_fire = True

            # 4. IDENTIFY SLACKERS (With Mention Logic)
            cursor.execute("SELECT player_tag, discord_id FROM players WHERE guild_id = %s", (guild_id,))
            links = {r[0]: r[1] for r in cursor.fetchall()}
            
            slacker_list = []
            for m in raid.members:
                if m.attack_count < 6:
                    d_id = links.get(m.tag)
                    mention = f"<@{d_id}>" if d_id else f"**{m.name}**"
                    slacker_list.append(f"• {mention} ({m.attack_count}/6 hits)")

            # 5. GENERATE DEBUG REPORT
            try:
                unix_ts = int(raid.end_time.time.timestamp())
            except AttributeError:
                unix_ts = int(raid.end_time.timestamp())

            debug_report = (
                f"📊 **Raid Logic Dry Run: `{clan_tag}`**\n"
                f"• State: `{raid.state.upper()}`\n"
                f"• Time Left: `{hours_left:.2f}h`\n"
                f"• Window Detected: `{simulated_window.upper()}`\n"
                f"• DB `last_sent` Flag: `{last_sent or 'None'}`\n"
                f"• **Would Loop Trigger?** `{'✅ YES' if will_fire else '❌ NO'}`\n"
                f"--------------------------------"
            )

            # 6. CREATE PREVIEW EMBED
            is_6h = (simulated_window == "6h")
            embed = discord.Embed(
                title=f"🏰 {'🚨 FINAL 6 HOURS' if is_6h else '⏳ 24 HOURS REMAINING'}: Capital Raid",
                description="This is a preview of the automated reminder.",
                color=0xFF4500 if is_6h else 0xFFCC00
            )
            
            pending_val = "\n".join(slacker_list[:25]) or "✅ No slackers found!"
            embed.add_field(name="Pending Attacks", value=pending_val[:1024], inline=False)
            embed.add_field(name="💰 Looted", value=f"`{raid.capital_resources_looted:,}`", inline=True)
            embed.add_field(name="⏳ Ends", value=f"<t:{unix_ts}:R>", inline=True)
            embed.set_footer(text=f"Simulated State: {simulated_window} | DB: {last_sent}")

            await interaction.followup.send(content=debug_report, embed=embed)

        except Exception as e:
            await interaction.followup.send(f"⚠️ Debug Error: `{e}`")
        finally:
            if cursor:
                cursor.close()

# Requirement for main.py loading
async def setup(bot):
    await bot.add_cog(ClanCommands(bot, coc_client))
    await bot.add_cog(RaidPatrol(bot, coc_client))