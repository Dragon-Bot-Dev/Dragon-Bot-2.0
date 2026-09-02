import discord
import asyncio
import coc
from discord.ext import commands, tasks
from discord import app_commands, Embed
from config import get_db_connection, get_db_cursor, coc_client, get_safe_cursor
import config
from utils import (
    fetch_clan_from_db, get_current_war_data, get_war_log_data,
    get_cwl_data, get_clan_data, format_datetime, format_month_day_year, ClanNotSetError,
    check_coc_clan_tag,  # Ensure this is imported for setclantag!
    fetch_player_from_DB, PlayerNotLinkedError, MissingPlayerTagError
)
class WarStatsView(discord.ui.View):
    def __init__(self, attacked_data, unattacked_data, source_label, our_name, opp_name, timer_text, max_atks):
        super().__init__(timeout=None) # Button timer
        self.attacked = attacked_data
        self.unattacked = unattacked_data
        self.source_label = source_label
        self.our_name = our_name
        self.opp_name = opp_name
        self.timer_text = timer_text
        self.max_atks = max_atks

    @discord.ui.button(label="Show Full Lineup", style=discord.ButtonStyle.secondary, emoji="📜")
    async def show_full(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Generate the same embed but without slicing the lists
        embed = self.create_stats_embed(full=True)
        button.disabled = True # Disable button after use
        await interaction.response.edit_message(embed=embed, view=self)

    def create_stats_embed(self, full=False):
        embed = discord.Embed(
            title=f"{self.source_label}: {self.our_name} vs {self.opp_name}",
            description=f"**{self.timer_text}**",
            color=0x3498db
        )

        # Helper to format lines
        def format_entry(e):
            # Keeps the alignment clean using a code block style
            return f"`{e['rel_pos']:2}.` TH{e['th']:2} **{e['name']}**: {e['stars']}⭐ {e['pct']}% ({e['att']}/{self.max_atks}){e['diff']}"

        def format_pending(e):
            return f"`{e['rel_pos']:2}.` TH{e['th']:2} **{e['name']}**"

        # Limit to 10 entries if not 'full'
        limit = None if full else 10
        
        if self.attacked:
            entries = [format_entry(e) for e in self.attacked[:limit]]
            val = "\n".join(entries)
            
            # Character Limit Safety Check
            if len(val) > 1000:
                # If too long, we show the first 10-15 and tell them to check the game
                val = "\n".join(entries[:15]) + f"\n*...and {len(entries)-15} more (List too long for Discord)*"
            elif not full and len(self.attacked) > 10:
                val += f"\n*...and {len(self.attacked)-10} more*"
                
            embed.add_field(name="✅ Attacked", value=val, inline=False)

        if self.unattacked:
            val = "\n".join([format_pending(e) for e in self.unattacked[:limit]])
            if not full and len(self.unattacked) > 10: val += f"\n*...and {len(self.unattacked)-10} more*"
            embed.add_field(name="❌ Pending", value=val, inline=False)

        return embed
class WarCommands(commands.Cog):
    def __init__(self, bot, coc_client): 
        self.bot = bot
        self.coc_client = coc_client 

    @app_commands.command(name="currentwar", description="Get info or member stats for current war")
    @app_commands.describe(mode="Choose: info (Overview) or stats (Member details)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="General Info of War", value="info"),
        app_commands.Choice(name="Shows member stats", value="stats")
    ])

    async def currentwar(self, interaction: discord.Interaction, mode: str = "info"):
        await interaction.response.defer()
        
        try:
            db_tag = fetch_clan_from_db(interaction.guild.id)
            war_data = None
            
            # Straight to automatic fetching
            war_data = await coc_client.get_current_war(db_tag)
                
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
            # --- STATS MODE (YAML) ---
            elif mode.lower() == "stats":
                opp_th_map = {m.tag: m.town_hall for m in opp.members}
                our_sorted = sorted(our.members, key=lambda x: x.map_position)
                active_our = our_sorted[:war_data.team_size]
                
                if war_data.state.value == "preparation":
                    time_diff = war_data.start_time.seconds_until
                    timer_label = "Battle Starts In"
                else:
                    time_diff = war_data.end_time.seconds_until
                    timer_label = "Time Remaining"

                hours, minutes = time_diff // 3600, (time_diff % 3600) // 60
                time_display = f"{timer_label}: {hours}h {minutes}m"
                
                attacked, unattacked = [], []
                
                for i, m in enumerate(active_our, 1):
                    atks = m.attacks 
                    diff_str = ""
                    
                    if atks:
                        th_diffs = [f"{(opp_th_map.get(a.defender_tag, m.town_hall) - m.town_hall):+}" for a in atks]
                        opp_lineup = sorted(opp.members, key=lambda x: x.map_position)[:war_data.team_size]
                        mirr_diffs = [f"{(i - (next((idx + 1 for idx, opp_m in enumerate(opp_lineup) if opp_m.tag == a.defender_tag), i))):+}" for a in atks]
                        diff_str = f" [TH:{','.join(th_diffs)} M:{','.join(mirr_diffs)}]"

                    display_name = m.name.strip()
                    if len(display_name) > 10: 
                        display_name = f"{display_name[:8]}.."

                    entry = {
                        "rel_pos": i, "th": m.town_hall, "name": display_name,
                        "stars": sum(a.stars for a in atks), "pct": int(sum(a.destruction for a in atks)),
                        "att": len(atks), "diff": diff_str
                    }
                    
                    if entry["att"] > 0: 
                        attacked.append(entry)
                    else: 
                        unattacked.append(entry)

                # 2. Build the Raw YAML Layout String
                lines = [
                    f"{source_label} War",
                    f"Matchup: {our.name} vs {opp.name}",
                    f"Status: {time_display}",
                    "",
                    "Attacked Lineup:"
                ]
                
                for e in attacked:
                    lines.append(f"{e['rel_pos']:2d}. TH{e['th']:2d} {e['name']}: {e['stars']}⭐ {e['pct']}% ({e['att']}/{max_atks}){e['diff']}")
                
                lines.append("")
                lines.append("Pending Attacks:")
                for e in unattacked:
                    lines.append(f"{e['rel_pos']:2d}. TH{e['th']:2d} {e['name']}")

                yaml_msg = "```yaml\n" + "\n".join(lines) + "\n```"
                
                # 3. Message Chunking Guard (Bypasses character limitations)
                if len(yaml_msg) > 2000:
                    chunks = [yaml_msg[i:i+1980] for i in range(0, len(yaml_msg), 1980)]
                    for chunk in chunks:
                        await interaction.followup.send(chunk if chunk.startswith("```") else f"```yaml\n{chunk}\n```")
                else:
                    await interaction.followup.send(yaml_msg)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(name="waractivity", description="See who's shown up and finished attacks in the last 7 days of war")
    @app_commands.describe(member="Optional: look up one specific member's recent war record")
    async def war_activity(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()

        try:
            clan_tag = fetch_clan_from_db(interaction.guild.id)
        except ClanNotSetError as e:
            return await interaction.followup.send(str(e), ephemeral=True)

        # If a member was given, resolve them to a player tag up front
        target_tag = None
        if member:
            try:
                target_tag = fetch_player_from_DB(interaction.guild.id, member, None)
            except (PlayerNotLinkedError, MissingPlayerTagError) as e:
                return await interaction.followup.send(f"⚠️ {e}", ephemeral=True)

        conn = get_db_connection()
        cursor = conn.cursor(buffered=True)

        try:
            if target_tag:
                # --- SEARCH MODE: one player's per-war breakdown ---
                clean_target = target_tag.strip().upper()
                cursor.execute("""
                    SELECT player_name, war_end_time, is_cwl, stars, destruction, attacks_used, max_attacks, opponent_name
                    FROM war_participation
                    WHERE clan_tag = %s AND player_tag = %s AND recorded_at >= NOW() - INTERVAL 7 DAY
                    ORDER BY war_end_time DESC
                """, (clan_tag, clean_target))
                detail_rows = cursor.fetchall()

                if not detail_rows:
                    return await interaction.followup.send(
                        f"No war activity recorded for **{member.display_name}** in the last 7 days.", ephemeral=True
                    )

                display_name = detail_rows[0][0]
                lines = [f"War Activity: {display_name} — Last 7 Days", ""]

                total_used = total_possible = total_stars = 0
                for _, end_time, is_cwl_flag, stars, destruction, used, possible, opp_name in detail_rows:
                    wtype = "CWL" if is_cwl_flag else "Standard"
                    date_str = end_time.strftime('%m-%d-%Y') if end_time else "N/A"
                    lines.append(f"{date_str} [{wtype}] vs {opp_name}: {stars}⭐ {destruction:.0f}% ({used}/{possible} atks)")
                    total_used += used
                    total_possible += possible
                    total_stars += stars

                rate = (total_used / total_possible * 100) if total_possible else 0
                lines.append("")
                lines.append(f"Totals: {len(detail_rows)} wars | {total_stars}⭐ | {total_used}/{total_possible} attacks used ({rate:.0f}%)")

                msg = "```yaml\n" + "\n".join(lines) + "\n```"
                await interaction.followup.send(msg)
                return

            # --- LEADERBOARD MODE: whole roster ranked by recent activity ---
            cursor.execute("""
                SELECT player_tag, player_name,
                       COUNT(*) AS wars,
                       SUM(attacks_used) AS atks_used,
                       SUM(max_attacks) AS atks_possible,
                       SUM(stars) AS total_stars,
                       AVG(destruction) AS avg_destruction
                FROM war_participation
                WHERE clan_tag = %s AND recorded_at >= NOW() - INTERVAL 7 DAY
                GROUP BY player_tag, player_name
            """, (clan_tag,))
            stats_by_tag = {row[0].upper(): row for row in cursor.fetchall()}
        finally:
            cursor.close()

        try:
            clan_data = await get_clan_data(clan_tag)
        except Exception as e:
            return await interaction.followup.send(f"Error fetching clan roster: {e}")

        leaderboard, no_data = [], []
        for rm in clan_data.members:
            stat = stats_by_tag.get(rm.tag.upper())
            if not stat:
                no_data.append(rm.name)
                continue
            _, _, wars, used, possible, total_stars, avg_destr = stat
            rate = (used / possible * 100) if possible else 0
            leaderboard.append({
                "name": rm.name, "th": rm.town_hall, "wars": wars, "used": used, "possible": possible,
                "rate": rate, "stars": total_stars, "avg_destr": avg_destr or 0
            })

        leaderboard.sort(key=lambda x: (x["rate"], x["stars"]), reverse=True)

        if not leaderboard and not no_data:
            return await interaction.followup.send("No war activity recorded yet for this clan.")

        lines = [
            "War Activity — Last 7 Days",
            f"Clan: {clan_data.name} ({clan_data.tag})",
            ""
        ]
        for i, e in enumerate(leaderboard, 1):
            lines.append(
                f"{i:2d}. {e['name'][:15]} (TH{e['th']}): Wars:{e['wars']} Atks:{e['used']}/{e['possible']} "
                f"({e['rate']:.0f}%) Stars:{e['stars']} AvgDmg:{e['avg_destr']:.1f}%"
            )

        if no_data:
            lines.append("")
            lines.append("No War Activity This Week:")
            for i, n in enumerate(no_data, 1):
                lines.append(f"{i:2d}. {n}")

        yaml_msg = "```yaml\n" + "\n".join(lines) + "\n```"

        if len(yaml_msg) > 2000:
            chunks = [yaml_msg[i:i+1980] for i in range(0, len(yaml_msg), 1980)]
            for chunk in chunks:
                await interaction.followup.send(chunk if chunk.startswith("```") else f"```yaml\n{chunk}\n```")
        else:
            await interaction.followup.send(yaml_msg)

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
        print("🔌 War Reminder Task: Cancelled.")

    @tasks.loop(minutes=20)
    async def war_reminder(self):
        print("--- [War Reminder Heartbeat] ---")
        cursor = await get_safe_cursor(retries=3, delay=5)
        if not cursor: return

        try:
            # Explicit column sequencing completely matches loop unpacking order below
            cursor.execute("SELECT clan_tag, guild_id, war_channel_id, last_war_reminder, war_reminder_1, war_reminder_2 FROM servers")
            tracked_clans = cursor.fetchall()

            for clan_tag, guild_id, war_channel_id, last_sent, cfg_hours_1, cfg_hours_2 in tracked_clans:
                if not clan_tag or not war_channel_id: continue

                # Match /serverstatus's displayed defaults — unset timers are NULL in the DB
                cfg_hours_1 = cfg_hours_1 if cfg_hours_1 is not None else 4
                cfg_hours_2 = cfg_hours_2 if cfg_hours_2 is not None else 1

                try:
                    # 2. FETCH DATA
                    war_data = await self.coc_client.get_current_war(clan_tag)
                    if not war_data or war_data.state == "notInWar":
                        try:
                            group = await self.coc_client.get_league_group(clan_tag)
                            if group:
                                async for cwl_war in group.get_wars_for_clan(clan_tag):
                                    if cwl_war.state != "notInWar":
                                        war_data = cwl_war; break
                        except: pass

                    # 3. TRANSITION & SUMMARY LOGIC
                    if war_data and war_data.state == "warEnded":
                        if last_sent != "summary_sent":
                            await self.send_war_summary(guild_id, war_channel_id, war_data, clan_tag)
                            await self.record_war_participation(war_data, clan_tag)
                            cursor.execute("UPDATE servers SET last_war_reminder = 'summary_sent' WHERE guild_id = %s", (guild_id,))
                            get_db_connection().commit()
                        continue

                    if not war_data or war_data.state == "preparation":
                        if last_sent is not None:
                            cursor.execute("UPDATE servers SET last_war_reminder = NULL WHERE guild_id = %s", (guild_id,))
                            get_db_connection().commit()
                        continue

                    if war_data.state != "inWar": continue

                    # 4. DYNAMIC TIME & STATE-LOCK GATE EVALUATION
                    seconds_left = war_data.end_time.seconds_until
                    hours_left = seconds_left / 3600
                    
                    reminder_type = "None"
                    
                    # Evaluation priority: check the final alert window first
                    if cfg_hours_2 > 0 and hours_left <= cfg_hours_2:
                        if last_sent != "t2_sent":
                            reminder_type = "t2_sent"
                    elif hours_left <= cfg_hours_1:
                        if last_sent not in ["t1_sent", "t2_sent"]:
                            reminder_type = "t1_sent"

                    # If we don't fall into a valid untriggered window, slide out early
                    if reminder_type == "None": continue

                    # 5. ATTACK LIMIT & SLACKER IDENTIFICATION
                    max_atks = getattr(war_data, 'attacks_per_member', 0)
                    if max_atks == 0:
                        is_cwl = "League" in str(type(war_data)) or hasattr(war_data, 'war_tag')
                        max_atks = 1 if is_cwl else 2
                    else:
                        is_cwl = (max_atks == 1)

                    source_label = "CWL" if is_cwl else "Standard"
                    
                    our_members = sorted(war_data.clan.members, key=lambda x: x.map_position or 99)
                    active_lineup = our_members[:war_data.team_size]
                    
                    # 🔗 REINSTATED PLAYER DICTIONARY LOOKUP (Fixes NameError)
                    cursor.execute("SELECT player_tag, discord_id FROM players")
                    links = {row[0]: row[1] for row in cursor.fetchall()}
                    
                    unattacked_lines = []
                    for m in active_lineup:
                        if len(m.attacks) < max_atks:
                            d_id = links.get(m.tag)
                            
                            if d_id:
                                discord_user = self.bot.get_user(int(d_id))
                                if discord_user:
                                    # Target pings only fly out on the absolute final alert interval
                                    mention = discord_user.mention if reminder_type == "t2_sent" else f"**{discord_user.display_name}**"
                                else:
                                    mention = f"**{m.name[:10]}**"
                            else:
                                mention = f"**{m.name[:10]}**"
                                
                            unattacked_lines.append(f"{m.map_position}. {mention} ({max_atks - len(m.attacks or [])} left)")

                    # 6. SEND REMINDER (Only if there are slackers)
                    if unattacked_lines:
                        channel = self.bot.get_channel(int(war_channel_id)) or await self.bot.fetch_channel(int(war_channel_id))
                        
                        try: unix_ts = int(war_data.end_time.time.timestamp())
                        except AttributeError: unix_ts = int(war_data.end_time.timestamp())

                        # Dynamic label assignment maps clean layout values to embed header
                        current_target = cfg_hours_1 if reminder_type == "t1_sent" else cfg_hours_2
                        time_label = f"⏳ {current_target} HOURS REMAINING" if reminder_type == "t1_sent" else "🚨 FINAL WARNING"
                        
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
                        embed.set_footer(text=f"Clan Tag: {clan_tag} | 🔗 = Linked Player")

                        await channel.send(embed=embed)
                        print(f"✅ SUCCESS: Sent custom {current_target}h alert for {clan_tag}")

                    # 7. UPDATE DATABASE PERSISTENCE LOCK
                    cursor.execute("UPDATE servers SET last_war_reminder = %s WHERE guild_id = %s", (reminder_type, guild_id))
                    get_db_connection().commit()

                except Exception as clan_error:
                    print(f"❌ Error for clan {clan_tag}: {clan_error}")

        except Exception as db_e:
            print(f"❌ Database Loop Error: {db_e}")
        finally:
            if cursor:
                cursor.close()

    async def send_war_summary(self, guild_id, channel_id, war, tag):
        channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
        if not channel: return

        # Identify 'our' vs 'opp' (Logic remains identical)
        our = war.clan if war.clan.tag == tag else war.opponent
        opp = war.opponent if war.clan.tag == tag else war.clan

        # 1. Calculate Results
        won = our.stars > opp.stars or (our.stars == opp.stars and our.destruction > opp.destruction)
        draw = our.stars == opp.stars and our.destruction == opp.destruction
        
        result_text = "🏆 VICTORY" if won else "🤝 DRAW" if draw else "DEFEAT"

        # 2. Process Member Stats (Logic remains identical)
        opp_th_map = {m.tag: m.town_hall for m in opp.members}
        max_atks = getattr(war, 'attacks_per_member', 2)
        attacked, unattacked = [], []
        
        our_members = sorted(our.members, key=lambda x: x.map_position or 99)[:war.team_size]
        for i, m in enumerate(our_members, 1):
            atks = getattr(m, 'attacks', [])
            diff_str = ""
            if atks:
                th_diffs = [f"{(opp_th_map.get(a.defender_tag, m.town_hall) - m.town_hall):+}" for a in atks]
                opp_lineup = sorted(opp.members, key=lambda x: x.map_position or 99)[:war.team_size]
                mirr_diffs = [f"{(i - (next((idx + 1 for idx, om in enumerate(opp_lineup) if om.tag == a.defender_tag), i))):+}" for a in atks]
                diff_str = f" [TH:{','.join(th_diffs)} M:{','.join(mirr_diffs)}]"
            
            entry = {"rel_pos": i, "th": m.town_hall, "name": m.name[:10], "stars": sum(a.stars for a in atks), "pct": int(sum(a.destruction for a in atks)), "att": len(atks), "diff": diff_str}
            if entry["att"] > 0: attacked.append(entry)
            else: unattacked.append(entry)

        # 3. Build the Raw YAML Layout String
        source_label = "CWL" if max_atks == 1 else "Standard"
        
        lines = [
            f"Result: {result_text}",
            f"{source_label} War",
            f"Scoreboard:",
            f" {our.name}: {our.stars}⭐ ({round(our.destruction, 1)}%)",
            f" {opp.name}: {opp.stars}⭐ ({round(opp.destruction, 1)}%)",
            "",
            "Attacked Lineup:"
        ]
        
        for e in attacked:
            lines.append(f"{e['rel_pos']:2d}. TH{e['th']:2d} {e['name']}: {e['stars']}⭐ {e['pct']}% ({e['att']}/{max_atks}){e['diff']}")
        
        if unattacked:
            lines.append("")
            lines.append("Unused Attacks:")
            for e in unattacked:
                lines.append(f"{e['rel_pos']:2d}. TH{e['th']:2d} {e['name']}")

        yaml_msg = f"**The War has ended!**\n```yaml\n" + "\n".join(lines) + "\n```"
        
        # 4. Message Chunking Guard (Bypasses character limitations)
        if len(yaml_msg) > 2000:
            chunks = [yaml_msg[i:i+1980] for i in range(0, len(yaml_msg), 1980)]
            for idx, chunk in enumerate(chunks):
                if idx == 0:
                    await channel.send(content=chunk if chunk.startswith("🎖️") else f"```yaml\n{chunk}\n```")
                else:
                    await channel.send(content=chunk if chunk.startswith("```") else f"```yaml\n{chunk}\n```")
        else:
            await channel.send(content=yaml_msg)

    async def record_war_participation(self, war_data, clan_tag):
        """Persists each active-lineup member's result for a finished war, so
        /waractivity can build a rolling 7-day view of who's showing up and
        finishing their attacks."""
        # Resolve 'our' clan the same safe way send_war_summary does above —
        # the earlier slacker-gate logic in this loop trusts war_data.clan
        # blindly, which isn't safe to repeat for CWL rounds.
        our = war_data.clan if war_data.clan.tag == clan_tag else war_data.opponent
        opp = war_data.opponent if war_data.clan.tag == clan_tag else war_data.clan

        max_atks = getattr(war_data, 'attacks_per_member', 0)
        if max_atks == 0:
            is_cwl = "League" in str(type(war_data)) or hasattr(war_data, 'war_tag')
            max_atks = 1 if is_cwl else 2
        else:
            is_cwl = (max_atks == 1)

        try:
            war_end_dt = war_data.end_time.time
        except AttributeError:
            war_end_dt = war_data.end_time

        our_members = sorted(our.members, key=lambda x: x.map_position or 99)[:war_data.team_size]

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(buffered=True)

            for m in our_members:
                atks = getattr(m, 'attacks', []) or []
                stars = sum(a.stars for a in atks)
                destruction = sum(a.destruction for a in atks)

                cursor.execute("""
                    INSERT INTO war_participation
                        (clan_tag, player_tag, player_name, war_end_time, is_cwl, stars, destruction, attacks_used, max_attacks, opponent_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        player_name = VALUES(player_name),
                        stars = VALUES(stars),
                        destruction = VALUES(destruction),
                        attacks_used = VALUES(attacks_used),
                        max_attacks = VALUES(max_attacks),
                        opponent_name = VALUES(opponent_name)
                """, (
                    clan_tag, m.tag, m.name, war_end_dt, int(is_cwl),
                    stars, destruction, len(atks), max_atks, opp.name
                ))

            conn.commit()
            print(f"📊 Recorded war participation for {len(our_members)} members ({clan_tag}).")
        except Exception as e:
            print(f"💥 Failed to record war participation for {clan_tag}: {e}")
        finally:
            # NOTE: get_db_connection() hands back a shared module-level connection
            # (see config.py), not a dedicated one — closing it here would yank the
            # rug out from under war_reminder()'s own cursor, which is still in use
            # right after this call returns. Only close what we opened ourselves.
            if cursor: cursor.close()

    @war_reminder.before_loop
    async def before_war_reminder(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    # Pass config.coc_client to both
    await bot.add_cog(WarCommands(bot, config.coc_client))
    await bot.add_cog(WarPatrol(bot, config.coc_client))
