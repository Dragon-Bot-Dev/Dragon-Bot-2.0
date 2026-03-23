
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
    def __init__(self, bot):
        self.bot = bot

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

    @tasks.loop(hours=6)
    async def raid_check(self):
        """Precise reminders at 24h and 6h remaining."""
        try:
            cursor = await get_safe_cursor(retries=3, delay=5)
            cursor.execute("SELECT clan_tag, raid_channel_id FROM servers")
            
            for tag, raid_channel_id in cursor.fetchall():
                if not tag or not raid_channel_id: continue

                async for raid in self.coc_client.get_raid_log(tag, limit=1):
                    if raid.state != "ongoing":
                        break
                    
                    seconds_left = raid.end_time.seconds_until
                    
                    # --- THE WINDOWS ---
                    # Window 1: 24 Hours Left (Interval: 18h to 24.5h)
                    is_24h_call = 64800 <= seconds_left <= 88200
                    
                    # Window 2: 6 Hours Left (Interval: 0.5h to 7h)
                    is_6h_call = 1800 <= seconds_left <= 25200

                    if not (is_24h_call or is_6h_call):
                        continue

                    # Identify Slackers
                    slackers = [f"• **{m.name}** ({m.attack_count}/6)" for m in raid.members if m.attack_count < 6]
                    
                    if slackers:
                        channel = self.bot.get_channel(int(raid_channel_id))
                        if not channel:
                            try: channel = await self.bot.fetch_channel(int(raid_channel_id))
                            except: continue

                        time_label = "24 HOURS REMAINING" if is_24h_call else "🚨 FINAL 6 HOURS"
                        
                        embed = discord.Embed(
                            title=f"🏰 {time_label}: Capital Raid",
                            description="Finish your attacks for more clan medals!",
                            color=0xFFCC00 if is_24h_call else 0xFF4500 # Yellow then Orange/Red
                        )
                        embed.add_field(name="Pending Hits", value="\n".join(slackers[:20]))
                        embed.set_footer(text=f"Total Loot So Far: {raid.capital_resources_looted:,}")
                        
                        await channel.send(embed=embed)
                    break 
        except Exception as e:
            print(f"Raid Task Error: {e}")

    @raid_check.before_loop
    async def before_raid_check(self):
        await self.bot.wait_until_ready()
@app_commands.command(name="test_raid_reminder", description="Forces a raid reminder check for the current server.")
async def test_raid_reminder(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    
    try:
        cursor = await get_safe_cursor(retries=3, delay=5)
        # Fetch config ONLY for this guild to avoid spamming other servers during testing
        cursor.execute(
            "SELECT clan_tag, raid_channel_id FROM servers WHERE guild_id = %s", 
            (interaction.guild_id,)
        )
        result = cursor.fetchone()

        if not result or not result[0] or not result[1]:
            return await interaction.followup.send("❌ Error: No clan tag or raid channel set for this server.")

        tag, raid_channel_id = result
        found_raid = False

        async for raid in self.coc_client.get_raid_log(tag, limit=1):
            if raid.state != "ongoing":
                return await interaction.followup.send(f"ℹ️ The raid for `{tag}` is not currently ongoing.")

            found_raid = True
            # Identify Slackers (Logic copied exactly from your task)
            slackers = [f"• **{m.name}** ({m.attack_count}/6)" for m in raid.members if m.attack_count < 6]
            
            if not slackers:
                return await interaction.followup.send("✅ Everyone has finished their attacks!")

            # Target the test channel
            channel = self.bot.get_channel(int(raid_channel_id))
            if not channel:
                channel = await self.bot.fetch_channel(int(raid_channel_id))

            # We force "FINAL 6 HOURS" label for the test
            embed = discord.Embed(
                title="🏰 [TEST] FINAL 6 HOURS: Capital Raid",
                description="This is a manual test of the reminder system.",
                color=0xFF4500 
            )
            embed.add_field(name="Pending Hits", value="\n".join(slackers[:20]))
            embed.set_footer(text=f"Total Loot: {raid.capital_resources_looted:,}")
            
            await channel.send(embed=embed)
            await interaction.followup.send(f"✅ Test reminder sent to <#{raid_channel_id}>")
            break 

        if not found_raid:
            await interaction.followup.send("❌ No raid log entries found for this clan.")

    except Exception as e:
        await interaction.followup.send(f"⚠️ Test Command Error: {e}")
        print(f"Test Raid Error: {e}")

# Requirement for main.py loading
async def setup(bot):
    await bot.add_cog(ClanCommands(bot))