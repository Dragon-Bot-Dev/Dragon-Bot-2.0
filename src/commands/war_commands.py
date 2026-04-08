import discord
import asyncio
import coc
from discord.ext import commands, tasks
from discord import app_commands, Embed
from config import get_db_cursor, coc_client, get_safe_cursor
import config
from utils import (
    fetch_clan_from_db, get_current_war_data, get_war_log_data,
    get_cwl_data, format_datetime, format_month_day_year, ClanNotSetError,
    check_coc_clan_tag  # Ensure this is imported for setclantag!
)

class WarCommands(commands.Cog):
    def __init__(self, bot, coc_client): # Add coc_client here
        self.bot = bot
        self.coc_client = coc_client # Store it

    @app_commands.command(name="currentwar", description="Get info or member stats for current war")
    @app_commands.describe(wartag="Tag for a specific CWL war", mode="Choose: info (Overview) or stats (Member details)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Overall Information of War Results", value="info"),
        app_commands.Choice(name="Shows each member's attacks, stars, and destruction", value="stats")
    ])
    async def currentwar(self, interaction: discord.Interaction, wartag: str = None, mode: str = "info"):
    
        
        await interaction.response.defer()
        
        try:
            db_tag = fetch_clan_from_db(interaction.guild.id)
            war_data = None
            
            # 1. Fetch the data
            if wartag:
                war_data = await coc_client.get_league_war(wartag)
            else:
                # Standard check
                war_data = await coc_client.get_current_war(db_tag)
                
                # If standard check is empty or not in war, try the group
                if not war_data or war_data.state == "notInWar":
                    group = await coc_client.get_league_group(db_tag)
                    if group:
                        async for war in group.get_wars_for_clan(db_tag):
                            if war.state != "notInWar":
                                war_data = war
                                break

            if not war_data or war_data.state == "notInWar":
                return await interaction.followup.send("No active war or CWL round found.")

        
            max_atks = getattr(war_data, 'attacks_per_member', 0)
            if max_atks == 0:
                is_cwl = "League" in str(type(war_data)) or hasattr(war_data, 'war_tag')
                max_atks = 1 if is_cwl else 2
            else:
                is_cwl = (max_atks == 1)

            source_label = "CWL" if is_cwl else "Standard"
            print(is_cwl, max_atks, source_label)

            # Ensure our clan is always 'our'
            if war_data.clan.tag == db_tag:
                our, opp = war_data.clan, war_data.opponent
            else:
                our, opp = war_data.opponent, war_data.clan

            # 2. Format the Embed
            max_attacks = 1 if is_cwl else 2
            total_possible = war_data.team_size * max_attacks
            # 1. Calculate Triples (Standard "CS" iteration)
            our_triples = sum(1 for m in our.members for a in getattr(m, 'attacks', []) if a.stars == 3)
            opp_triples = sum(1 for m in opp.members for a in getattr(m, 'attacks', []) if a.stars == 3)

            if mode.lower() == "info":
                display_state = str(war_data.state).capitalize()
                
                # Determine color based on stars
                if war_data.state == "preparation":
                    embed_color = 0xffff00 #yellow for prep
                elif our.stars > opp.stars: 
                    embed_color = 0x00ff00 # Green
                elif our.stars < opp.stars: 
                    embed_color = 0xff0000 # Red
                    
                else: embed_color = 0x3498db # blue for draw or unknown

                embed = discord.Embed(
                    title=f"{our.name} vs {opp.name}",
                    description=f"**Type:** {source_label}\nClan Tag: `{our.tag}` | Opp. Tag: `{opp.tag}`",
                    color=embed_color
                )
                
                # Add extra info for CWL like the Round number if available
                if is_cwl and hasattr(war_data, 'war_tag'):
                    embed.set_footer(text=f"CWL War Tag: {war_data.war_tag}")

                embed.add_field(name="Clan Stars", value=f"⭐ `{our.stars}/{our.max_stars}`", inline=True)
                embed.add_field(name="Clan Attacks Used", value=f"`{our.attacks_used}/{total_possible}`", inline=True)
                embed.add_field(name="Clan Destruction", value=f"💥 `{round(our.destruction, 1)}%/100%`", inline=True)

                # embed.add_field(name="Stars", value=f"⭐ {our.stars} - {opp.stars}", inline=True)
                # embed.add_field(name="Destruction", value=f"💥 {round(our.destruction, 1)}% - {round(opp.destruction, 1)}%", inline=True)
                
                embed.add_field(name="Opp. Stars", value=f"⭐ `{opp.stars}/{opp.max_stars}`", inline=True)
                embed.add_field(name="Opp. Attacks Used", value=f"`{opp.attacks_used}/{total_possible}`", inline=True)
                embed.add_field(name="Opp. Destruction", value=f"💥 `{round(opp.destruction, 1)}%/100%`", inline=True)

                # CWL has 1 attack per person, Normal has 2
                embed.add_field(name="3 Stars", value=f"`{our_triples}/{war_data.team_size}`", inline=True) 
                embed.add_field(name="Opp. 3 Stars", value=f"`{opp_triples}/{war_data.team_size}`", inline=True) 

                # --- Dynamic Time Logic ---
                if war_data.state == "preparation":
                    time_diff = war_data.start_time.seconds_until
                    label = "War Starts In"
                else:
                    time_diff = war_data.end_time.seconds_until
                    label = "Time Remaining"

                hours, minutes = time_diff // 3600, (time_diff % 3600) // 60
                time_str = f"⏳ {hours}h {minutes}m"

                embed.add_field(name=label, value=f"`{time_str}`", inline=True)

                end_date = format_month_day_year(war_data.end_time)
                embed.add_field(name="`War Ends`", value=f"`{end_date}`", inline=False)
                
                await interaction.followup.send(embed=embed)
                # --- STATS MODE (YAML) ---
            elif mode.lower() == "stats":
                # 1. Map opponent data
                opp_th_map = {m.tag: m.town_hall for m in opp.members}
                
                our_sorted = sorted(our.members, key=lambda x: x.map_position)
                active_our = our_sorted[:war_data.team_size]
                
                # --- Dynamic Timer for Stats Header ---
                if war_data.state.value == "preparation":
                    time_diff = war_data.start_time.seconds_until
                    timer_label = "Battle Starts In"
                else:
                    time_diff = war_data.end_time.seconds_until
                    timer_label = "Time Remaining"

                hours, minutes = time_diff // 3600, (time_diff % 3600) // 60
                time_display = f"{hours}h {minutes}m"
                
                attacked, unattacked = [], []
                
                for i, m in enumerate(active_our, 1):
                    atks = m.attacks 
                    diff_str = ""
                    
                    if atks:
                        th_diffs = [f"{(opp_th_map.get(a.defender_tag, m.town_hall) - m.town_hall):+}" for a in atks]
                        # Corrected Mirror Logic: Current - Target
                        # We use 'i' as current_rel_pos based on the sorted list
                        mirr_diffs = [f"{(i - (next((index + 1 for index, opp_m in enumerate(sorted(opp.members, key=lambda x: x.map_position)[:war_data.team_size]) if opp_m.tag == a.defender_tag), i))):+}" for a in atks]
                        diff_str = f" [TH:{','.join(th_diffs)} M:{','.join(mirr_diffs)}]"

                    # Name Trimming
                    display_name = m.name.strip()
                    if len(display_name) > 10:
                        display_name = f"{display_name[:8]}.."

                    entry = {
                        "rel_pos": i,
                        "th": m.town_hall,
                        "name": display_name,
                        "stars": sum(a.stars for a in atks),
                        "pct": sum(a.destruction for a in atks),
                        "att": len(atks),
                        "diff": diff_str
                    }
                    
                    if entry["att"] > 0:
                        attacked.append(entry)
                    else:
                        unattacked.append(entry)

                lines = [
                    "```yaml",
                    f"{source_label} War: {our.name} vs {opp.name}",
                    f"State: {war_data.state.value.capitalize()}",
                    f"{timer_label}: {time_display}",
                    ""
                ]

                # If it's Preparation Day, just show one list of "Lineup"
                if war_data.state.value == "preparation":
                    lines.append("⚔️ Active Lineup")
                    for e in unattacked:
                        lines.append(f"{e['rel_pos']:2}. TH{e['th']:2} {e['name']}")
                else:
                    # Normal Battle Day view
                    if attacked:
                        lines.append("✅ Attacked")
                        for e in attacked:
                            lines.append(f"{e['rel_pos']:2}. TH{e['th']:2} {e['name']}: {e['stars']}⭐, {round(e['pct'], 1)}% ({e['att']}/{max_attacks}){e['diff']}")
                    
                    if unattacked:
                        lines.append("\n❌ Pending Attacks")
                        for e in unattacked:
                            lines.append(f"{e['rel_pos']:2}. TH{e['th']:2} {e['name']}")

                lines.append("```")
                
                final_yaml = "\n".join(lines)
                # (Keep your character limit safety logic here)
                await interaction.followup.send(final_yaml)
           

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="cwlschedule", description="Receive information about the current CWL Schedule")
    async def cwlschedule(self, interaction: discord.Interaction):
        """Fetches the rounds and opponents for the current CWL season."""
        DEFAULT_CLAN_TAG = "#2JL28OGJJ"
        guild_id = interaction.guild.id
        
        try:
            db_tag = fetch_clan_from_db(guild_id)
        except ClanNotSetError:
            db_tag = DEFAULT_CLAN_TAG

        await interaction.response.defer()

        try:
            # 1. Fetch the group first
            group = await coc_client.get_league_group(db_tag)
            
            if not group:
                return await interaction.followup.send("This clan is not participating in CWL right now.")

            lines = [
                f"**CWL Season {group.season}** - State: {group.state}",
                "",
                "Participating Clans:"
            ]
            for i, c in enumerate(group.clans, start=1):
                lines.append(f"{i}. {c.name} ({c.tag})")

            lines.append("\nRound Schedule:")

            # 2. TO FIX THE LOOP ERROR: 
            # We will fetch wars manually but in a simplified way that doesn't trigger 
            # the library's internal loop conflict.
            my_norm = db_tag.strip().lstrip("#").upper()
            
            # Instead of the Iterator, we fetch only the rounds that have valid tags
            for idx, round_tags in enumerate(group.rounds, start=1):
                opponent_name = "Not yet scheduled"
                
                # Filter out the empty #0 tags before making requests
                valid_tags = [t for t in round_tags if t != "#0"]
                
                if not valid_tags:
                    lines.append(f"Round {idx}: {opponent_name}")
                    continue

                # Look for our clan in the round's wars
                found = False
                for wt in valid_tags:
                    try:
                        # Fetch the specific war
                        war = await coc_client.get_league_war(wt)
                        
                        # Check if our clan is in this war
                        c1 = war.clan.tag.strip().lstrip("#").upper()
                        c2 = war.opponent.tag.strip().lstrip("#").upper()
                        
                        if c1 == my_norm:
                            opponent_name = f"vs {war.opponent.name}"
                            found = True
                        elif c2 == my_norm:
                            opponent_name = f"vs {war.clan.name}"
                            found = True
                        
                        if found:
                            lines.append(f"Round {idx}: {opponent_name} (War Tag: {wt})")
                            break
                    except Exception:
                        continue # Skip failed fetches
                
                if not found:
                    lines.append(f"Round {idx}: {opponent_name}")

            text = "```yaml\n" + "\n".join(lines) + "\n```"
            await interaction.followup.send(text)

        except Exception as e:
            # If the loop error still persists, we know it's the coc_client initialization
            print(f"DEBUG: {e}")
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="warlog", description="Retrieve the clan's war log")
    @app_commands.describe(limit="Number of recent wars to display (max 8)")
    async def war_log(self, interaction: discord.Interaction, limit: int = 1):
        await interaction.response.defer()
        try:
            tag = fetch_clan_from_db(interaction.guild.id)
            war_log = await get_war_log_data(tag)
            
            if not war_log:
                return await interaction.followup.send("No public war log found or log is private.")

            count = 0
            # We iterate directly to avoid the slicing bug in coc.py
            limit = max(1, min(limit, 8)) 
            for entry in war_log:
                if count >= limit:
                    break
                is_cwl = getattr(entry, 'is_league_entry', False)
                max_atks_per_player = 1 if is_cwl else 2
                
                total_possible = entry.team_size * max_atks_per_player
                
                # Safely handle names and stars
                clan_name = entry.clan.name
                clan_tag = entry.clan.tag
                clan_stars = entry.clan.stars
                if entry.opponent and entry.opponent.name:
                    opp_name = entry.opponent.name
                    opp_tag = entry.opponent.tag or "N/A"
                    opp_stars = entry.opponent.stars
                    opp_destruction = round(entry.opponent.destruction, 3)
                else:
                    # This handles the CWL summary cases where opponent is None
                    opp_name = "CWL Group"
                    opp_tag = "N/A"
                    opp_stars = "N/A"
                    opp_destruction = 0
                
                CWL_rounds = 7
                clan_destruction = round(entry.clan.destruction, 3)
                opp_destruction = round(entry.opponent.destruction, 3) if entry.opponent else 0

                res_raw = str(entry.result).lower() if entry.result else "league"
                color = 0x00ff00 if "win" in res_raw else 0xff0000 if "lose" in res_raw else 0xffff00

                embed = discord.Embed(
                    title=f"{clan_name} vs {opp_name}",
                    description=f"Type: {'CWL' if opp_name == 'CWL Group' else 'Standard War'}\nClan Tag: `{clan_tag}` | Opp. Tag: `{opp_tag}`",
                    color=color
                )
                embed.add_field(name="Result", value=f"**{entry.result or 'CWL'}**", inline=False)

                if is_cwl:
                    embed.add_field(name="Clan Stars", value=f":star: {entry.clan.stars}/{entry.clan.max_stars*7}", inline=True)
                    embed.add_field(name="Clan Attacks Used", value=f"`{entry.clan.attacks_used}/{total_possible*7}`", inline=True)
                    embed.add_field(name="Clan Destruction", value=f":boom: {clan_destruction}%/700%", inline=True)
                if not is_cwl:
                    embed.add_field(name="Clan Stars", value=f":star: {entry.clan.stars}/{(entry.clan.max_stars)}", inline=True)
                    embed.add_field(name="Clan Attacks Used", value=f"`{entry.clan.attacks_used}`/`{total_possible}`", inline=True)
                    embed.add_field(name="Clan Destruction", value=f":boom: {clan_destruction}%/100%", inline=True)
                if not is_cwl:
                    embed.add_field(name="Opponent Stars", value=f":star: {entry.opponent.stars}/{entry.opponent.max_stars}", inline=True)
                    embed.add_field(name="Opponent Attacks Used", value=f"`{entry.opponent.attacks_used}`/`{total_possible}`", inline=True)
                    embed.add_field(name="Opponent Destruction", value=f":boom: {opp_destruction}%/100%", inline=True)

                # embed.add_field(name="Stars", value=f"{entry.clan.stars} - {opp_stars}", inline=True)
                # embed.add_field(name="Destruction", value=f"{round(entry.clan.destruction, 1)}%", inline=True)
                embed.add_field(name = "Exp. Earned", value=f"{entry.clan.exp_earned}", inline=False)
                end_date = format_month_day_year(entry.end_time)
                embed.add_field(name="End Date", value=end_date, inline=False)
                
                await interaction.followup.send(embed=embed)
                count += 1

        except Exception as e:
            # This handles the internal library crash gracefully
            await interaction.followup.send(f"An entry in the war log could not be parsed by the library: {e}")

            
    @app_commands.command(name="cwlclansearch", description="Search CWL clans by name or tag")
    @app_commands.describe(nameortag="Clan name or tag")
    async def cwlclansearch(self, interaction: discord.Interaction, nameortag: str):
        await interaction.response.defer()
        try:
            db_tag = fetch_clan_from_db(interaction.guild.id)
            group = await coc_client.get_league_group(db_tag)
            
            if not group:
                return await interaction.followup.send("This clan is not participating in CWL right now.")

            query = nameortag.strip().upper().lstrip("#")
            match_tag = None

            # 1. First, search the group.clans list (if populated)
            for clan in group.clans:
                if clan.tag.lstrip("#").upper() == query or clan.name.upper() == query:
                    match_tag = clan.tag
                    break

            # 2. If not found and Round 1 has tags, search the actual wars
            # This is helpful if group.clans is empty during Round 1 prep
            if not match_tag and group.rounds:
                # Check Round 1 (index 0)
                round_one_tags = [t for t in group.rounds[0] if t != "#0"]
                for wt in round_one_tags:
                    try:
                        war = await coc_client.get_league_war(wt)
                        # Check Clan A
                        if war.clan.tag.lstrip("#").upper() == query or war.clan.name.upper() == query:
                            match_tag = war.clan.tag
                            break
                        # Check Clan B
                        if war.opponent.tag.lstrip("#").upper() == query or war.opponent.name.upper() == query:
                            match_tag = war.opponent.tag
                            break
                    except:
                        continue
                    if match_tag: break

            if not match_tag:
                return await interaction.followup.send(
                    f"Clan `{nameortag}` not found. If CWL just started, the API may take a few minutes to sync all clans."
                )

            # 3. Final Fetch
            full_clan = await coc_client.get_clan(match_tag)
            sorted_m = sorted(full_clan.members, key=lambda m: m.town_hall, reverse=True)
            member_info = "\n".join(f"{i}. {m.name} (TH {m.town_hall})" for i, m in enumerate(sorted_m[:30], start=1))

            res = (
                f"```yaml\n"
                f"CWL Clan Search Result\n"
                f"Status: {group.state}\n"
                f"Clan: {full_clan.name} ({full_clan.tag})\n"
                f"TH Breakdown (Top 30):\n"
                f"{member_info}\n"
                f"```"
            )
            await interaction.followup.send(res)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
            
    @app_commands.command(name="cwlprep", description="Full scout of enemy TH levels and Win Streaks")
    async def cwl_prep(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            db_tag = fetch_clan_from_db(interaction.guild.id)
            group = await coc_client.get_league_group(db_tag)
            
            if not group:
                return await interaction.followup.send("No active CWL group found.")

            lines = [f"**CWL Scouting: Season {group.season}**", ""]
            
            for clan in group.clans:
                # 1. Fetch clan data
                clan_obj = await coc_client.get_clan(clan.tag)
                
                # 2. Count ALL Town Halls
                th_counts = {}
                for m in clan_obj.members:
                    th_counts[m.town_hall] = th_counts.get(m.town_hall, 0) + 1
                
                # 3. Format the full breakdown (Sorted highest TH to lowest)
                # This creates a string like: "TH16: 5, TH15: 12, TH14: 3..."
                all_ths = ", ".join([f"TH{th}: {count}" for th, count in sorted(th_counts.items(), reverse=True)])
                
                # 4. War Streak logic
                streak = clan_obj.war_win_streak
                streak_emoji = "🔥" if streak >= 5 else "⚔️"
                
                # 5. Public/Private log indicator
                log_status = "🔓 Public Log" if clan_obj.public_war_log else "🔒 Private Log"

                lines.append(f"{clan_obj.name} (Lvl {clan_obj.level})")
                lines.append(f"  Streak: {streak_emoji} {streak} Wins | {log_status}")
                lines.append(f"  Lineup: {all_ths}")
                lines.append("-" * 25)

            # 6. Final Formatting and character limit safety
            final_msg = "```yaml\n" + "\n".join(lines) + "```"
            
            if len(final_msg) > 2000:
                # Split the message if it's too long for Discord
                chunks = [final_msg[i:i+1990] for i in range(0, len(final_msg), 1990)]
                for chunk in chunks:
                    await interaction.followup.send(chunk if chunk.startswith("```") else f"```yaml\n{chunk}")
            else:
                await interaction.followup.send(final_msg)

        except Exception as e:
            await interaction.followup.send(f"Scouting Error: {e}")


class WarPatrol(commands.Cog):
    def __init__(self, bot, coc_client):
        self.bot = bot
        self.coc_client = coc_client
        #

    async def cog_load(self):
        """Runs once when the Cog is loaded into the bot."""
        if not self.war_reminder.is_running():
            self.war_reminder.start()
            print("⚔️ War Reminder Task: Started safely.")

    def cog_unload(self):
        """Runs when the Cog is removed or the bot shuts down."""
        # This is your "Zombie Killer"
        self.war_reminder.cancel()
        print("🔌 War Reminder Task: Cancelled gracefully.")

    @tasks.loop(minutes=20)
    async def war_reminder(self):
        # 1. HEARTBEAT & DB ACQUISITION
        print("--- [War Reminder Heartbeat] ---")
        cursor = await get_safe_cursor(retries=3, delay=5)
        if not cursor:
            return

        try:
            # Fetch all servers
            cursor.execute("SELECT clan_tag, guild_id, war_channel_id, last_war_reminder FROM servers")
            tracked_clans = cursor.fetchall()

            for clan_tag, guild_id, war_channel_id, last_sent in tracked_clans:
                if not clan_tag or not war_channel_id:
                    continue 

                try:
                    # 2. FETCH DATA & FALLBACK
                    war_data = await self.coc_client.get_current_war(clan_tag)
                    if not war_data or war_data.state == "notInWar":
                        try:
                            group = await self.coc_client.get_league_group(clan_tag)
                            if group:
                                async for cwl_war in group.get_wars_for_clan(clan_tag):
                                    if cwl_war.state != "notInWar":
                                        war_data = cwl_war
                                        break
                        except coc.NotFound:
                            pass

                    # 3. RESET LOGIC: Clear DB flag if war ended or hasn't started
                    if not war_data or war_data.state != "inWar":
                        if last_sent is not None:
                            cursor.execute("UPDATE servers SET last_war_reminder = NULL WHERE clan_tag = %s", (clan_tag,))
                            cursor.connection.commit()
                        continue

                    # 4. TIME & TRIGGER LOGIC
                    seconds_left = war_data.end_time.seconds_until
                    hours_left = seconds_left / 3600
                    
                    reminder_type = "None"
                    if hours_left <= 1:
                        reminder_type = "final"
                    elif hours_left <= 4:
                        reminder_type = "warning"

                    # TRIGGER GATE: Only proceed if we are in a window and haven't sent it yet
                    if reminder_type == "None": continue
                    if (reminder_type == "warning" and last_sent in ["warning", "final"]): continue
                    if (reminder_type == "final" and last_sent == "final"): continue

                    # 5. ATTACK LIMIT & SLACKER IDENTIFICATION
                    max_atks = getattr(war_data, 'attacks_per_member', 0)
                    if max_atks == 0:
                        is_cwl = "League" in str(type(war_data)) or hasattr(war_data, 'war_tag')
                        max_atks = 1 if is_cwl else 2
                    else:
                        is_cwl = (max_atks == 1)

                    source_label = "CWL" if is_cwl else "Standard"
                    
                    # Sort and Slice by team_size (O(N log N) but N is small)
                    our_members = sorted(war_data.clan.members, key=lambda x: x.map_position or 99)
                    active_lineup = our_members[:war_data.team_size]
                    
                    cursor.execute("SELECT player_tag, discord_id FROM players WHERE guild_id = %s", (str(guild_id),))
                    links = {row[0]: row[1] for row in cursor.fetchall()}
                    
                    unattacked_lines = []
                    for m in active_lineup:
                        if len(m.attacks) < max_atks:
                            d_id = links.get(m.tag)
                            mention = f"<@{d_id}>" if d_id else f"**{m.name[:10]}**"
                            unattacked_lines.append(f"{m.map_position}. {mention} ({max_atks - len(m.attacks or [])} left)")

                    # 6. SEND REMINDER (Only if there are slackers)
                    if unattacked_lines:
                        channel = self.bot.get_channel(int(war_channel_id)) or await self.bot.fetch_channel(int(war_channel_id))
                        
                        # Timestamp Bridge Fix
                        try:
                            unix_ts = int(war_data.end_time.time.timestamp())
                        except AttributeError:
                            unix_ts = int(war_data.end_time.timestamp())

                        time_label = "🚨 FINAL HOUR" if reminder_type == "final" else "⏳ 4 HOURS LEFT"
                        
                        # Dynamic Embed Color
                        if war_data.clan.stars > war_data.opponent.stars: embed_color = 0x2ecc71
                        elif war_data.clan.stars < war_data.opponent.stars: embed_color = 0xe74c3c
                        else: embed_color = 0xf1c40f

                        embed = discord.Embed(
                            title=f"{time_label}: War Status Report",
                            description=f"**{war_data.clan.name}** vs **{war_data.opponent.name}**\n"
                                        f"Type: `{source_label}` | Remaining: `{len(unattacked_lines)}/{war_data.team_size}`",
                            color=embed_color
                        )
                        
                        
                        embed.add_field(name="⚠️ Pending Attacks", value="\n".join(unattacked_lines[:25]), inline=False)
                        embed.add_field(name="Scoreboard", value=f"⭐ `{war_data.clan.stars}` vs ⭐ `{war_data.opponent.stars}`", inline=True)
                        embed.add_field(name="⏳ Ends", value=f"<t:{unix_ts}:R>", inline=True)
                        embed.set_footer(text=f"Clan Tag: {clan_tag}")

                        await channel.send(embed=embed)
                        print(f"✅ SUCCESS: Sent {reminder_type} reminder for {clan_tag}")

                    # 7. UPDATE DATABASE PERSISTENCE
                    cursor.execute("UPDATE servers SET last_war_reminder = %s WHERE clan_tag = %s", (reminder_type, clan_tag))
                    cursor.connection.commit()

                except Exception as clan_error:
                    print(f"❌ Error for clan {clan_tag}: {clan_error}")

        except Exception as db_e:
            print(f"❌ Database Loop Error: {db_e}")
        finally:
            if cursor:
                cursor.close()

    @war_reminder.before_loop
    async def before_war_reminder(self):
        await self.bot.wait_until_ready()

    # @app_commands.command(name="test_reminder", description="DEBUG: War Map Stats & Reminder Preview")
    # @app_commands.checks.has_permissions(administrator=True)
    # async def test_reminder(self, interaction: discord.Interaction):
    #     await interaction.response.defer(ephemeral=True)
        
    #     cursor = await get_safe_cursor(retries=3, delay=5)
    #     try:
    #         guild_id = str(interaction.guild.id)
    #         # Fetching last_sent is key for simulation
    #         cursor.execute("SELECT clan_tag, war_channel_id, last_war_reminder FROM servers WHERE guild_id = %s", (guild_id,))
    #         row = cursor.fetchone()
    #         if not row or not row[0]:
    #             return await interaction.followup.send("❌ Clan tag not configured.")
            
    #         clan_tag, war_channel_id, last_sent = row
            
    #         # 1. FETCH DATA
    #         war_data = await self.coc_client.get_current_war(clan_tag)
    #         if not war_data or war_data.state == "notInWar":
    #             try:
    #                 group = await self.coc_client.get_league_group(clan_tag)
    #                 if group:
    #                     async for cwl_war in group.get_wars_for_clan(clan_tag):
    #                         if cwl_war.state != "notInWar":
    #                             war_data = cwl_war
    #                             break
    #             except coc.NotFound:
    #                 pass

    #         if not war_data or war_data.state == "notInWar":
    #             return await interaction.followup.send("💤 No active war found.")

    #         # 2. LOGIC PREPARATION
    #         max_atks = getattr(war_data, 'attacks_per_member', 0)
    #         if max_atks == 0:
    #             is_cwl = "League" in str(type(war_data)) or hasattr(war_data, 'war_tag')
    #             max_atks = 1 if is_cwl else 2
    #         else:
    #             is_cwl = (max_atks == 1)

    #         source_label = "CWL" if is_cwl else "Standard"
            
    #         our_members = sorted(war_data.clan.members, key=lambda x: x.map_position or 99)
    #         active_our = our_members[:war_data.team_size]
            
    #         cursor.execute("SELECT player_tag, discord_id FROM players WHERE guild_id = %s", (guild_id,))
    #         links = {r[0]: r[1] for r in cursor.fetchall()}

    #         # 3. CATEGORIZE
    #         attacked, unattacked = [], []
    #         for m in active_our:
    #             atks = m.attacks
    #             display_name = m.name[:10] + ".." if len(m.name) > 10 else m.name
    #             entry = {
    #                 "pos": m.map_position,
    #                 "name": display_name,
    #                 "tag": m.tag,
    #                 "done": len(atks),
    #                 "stars": sum(a.stars for a in atks)
    #             }
    #             if len(atks) >= max_atks:
    #                 attacked.append(entry)
    #             else:
    #                 d_id = links.get(m.tag)
    #                 entry["mention"] = f"<@{d_id}>" if d_id else f"**{display_name}**"
    #                 unattacked.append(entry)

    #         # 4. TIME & TRIGGER SIMULATION
    #         try:
    #             unix_ts = int(war_data.end_time.time.timestamp())
    #         except AttributeError:
    #             unix_ts = int(war_data.end_time.timestamp())

    #         seconds_left = war_data.end_time.seconds_until
    #         hours_left = seconds_left / 3600
            
    #         # --- TRIGGER LOGIC ---
    #         simulated_trigger = "None"
    #         will_fire = False

    #         if hours_left <= 1:
    #             simulated_trigger = "final"
    #             if last_sent != "final":
    #                 will_fire = True
    #         elif hours_left <= 4:
    #             simulated_trigger = "warning"
    #             if last_sent not in ["warning", "final"]:
    #                 will_fire = True

    #         # 5. DRY RUN REPORT TEXT
    #         status_report = (
    #             f"📊 **Reminder Dry Run: `{clan_tag}`**\n"
    #             f"• Time Left: `{hours_left:.2f}h`\n"
    #             f"• DB State: `{last_sent or 'None'}`\n"
    #             f"• Current Window: `{simulated_trigger.upper()}`\n"
    #             f"• **Loop Triggered?** `{'✅ YES' if will_fire else '❌ NO'}`\n"
    #             f"--------------------------------"
    #         )

    #         # 6. EMBED FORMATTING
    #         is_final = (hours_left <= 1)
    #         time_label = "🚨 FINAL HOUR" if is_final else "⏳ 4 HOURS LEFT"
            
    #         if war_data.state == "preparation": embed_color = 0x3498db
    #         elif war_data.clan.stars > war_data.opponent.stars: embed_color = 0x2ecc71
    #         elif war_data.clan.stars < war_data.opponent.stars: embed_color = 0xe74c3c
    #         else: embed_color = 0xf1c40f

    #         embed = discord.Embed(
    #             title=f"{time_label}: War Status Report",
    #             description=f"**{war_data.clan.name}** vs **{war_data.opponent.name}**\n"
    #                         f"Type: `{source_label}` | Remaining: `{len(unattacked)}/{war_data.team_size}`",
    #             color=embed_color
    #         )

    #         if unattacked:
    #             slacker_list = "\n".join([f"{e['pos']}. {e['mention']} ({max_atks - e['done']} left)" for e in unattacked])
    #             embed.add_field(name="⚠️ Pending Attacks", value=slacker_list[:1024], inline=False)
    #         else:
    #             embed.add_field(name="✅ Status", value="All attacks completed!", inline=False)

    #         if attacked:
    #             done_list = "\n".join([f"{e['pos']}. **{e['name']}** ({e['stars']}⭐)" for e in attacked])
    #             embed.add_field(name="Completed Attacks", value=done_list[:1024], inline=False)

    #         embed.add_field(name="Scoreboard", value=f"⭐ `{war_data.clan.stars}` vs ⭐ `{war_data.opponent.stars}`", inline=True)
    #         embed.add_field(name="⏳ Ends", value=f"<t:{unix_ts}:R>", inline=True)
    #         embed.set_footer(text=f"Trigger Status: {simulated_trigger.upper()} | DB: {last_sent or 'None'}")

    #         # Send both the report and the embed preview
    #         await interaction.followup.send(content=status_report, embed=embed)

    #     except Exception as e:
    #         await interaction.followup.send(f"⚠️ Error: `{e}`")
    #     finally:
    #         cursor.close()

async def setup(bot):
  
    import config 
    
    # Pass config.coc_client to both
    await bot.add_cog(WarCommands(bot, config.coc_client))
    await bot.add_cog(WarPatrol(bot, config.coc_client))