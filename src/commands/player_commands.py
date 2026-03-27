
import sys

import discord
import time
import coc
from discord.ext import commands
from discord import app_commands, Embed

# Import helpers from your config and utils
from config import get_db_cursor, coc_client
from utils import (
    fetch_player_from_DB, get_player_data, 
    PlayerNotLinkedError, MissingPlayerTagError
)

class PlayerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="playerinfo", description="Get player's general information")
    @app_commands.describe(user="Select a Discord user", player_tag="The user's tag (optional)")
    async def player_info(self, interaction: discord.Interaction, user: discord.Member = None, player_tag: str = None):
        await interaction.response.defer()

        try:
            guild_id = str(interaction.guild.id)
            
            # Assuming fetch_player_from_DB is updated to handle string IDs
            tag = fetch_player_from_DB(guild_id, user, player_tag)
            player_data = await get_player_data(tag)
            
            player_labels = ", ".join(label.name for label in player_data.labels) if player_data.labels else "None"
            timestamp = int(time.time())

            role_mapping = {
                'admin': "Elder", 
                'coleader': "Co-Leader", 
                'leader': "Leader", 
                'member': "Member"
            }
            display_role = role_mapping.get(str(player_data.role).lower(), str(player_data.role).capitalize())

            embed = discord.Embed(
                title=f"User: {player_data.name} ({player_data.tag})",
                description=f"{player_labels}\nLast updated: <t:{timestamp}:R>",
                color=0x0000FF
            )
            
            if player_data.league:
                embed.set_thumbnail(url=player_data.league.icon.url)
            
            if player_data.clan:
                embed.add_field(name="Clan", value=f"{player_data.clan.name} ({player_data.clan.tag})", inline=False)
            
            embed.add_field(name="Role", value=display_role, inline=True)
            embed.add_field(name="TH Lvl", value=player_data.town_hall, inline=True)
            embed.add_field(name="Exp Lvl", value=player_data.exp_level, inline=True)

            # War Preference Logic
            pref = "Unknown"
            if player_data.war_opted_in is True: pref = "✅ Opted In"
            elif player_data.war_opted_in is False: pref = "❌ Opted Out"
            elif player_data.war_opted_in is None: pref = "Not in a clan"
            
            embed.add_field(name="War Preference", value=pref, inline=True)
            embed.add_field(name="Trophies", value=f"🏆 {player_data.trophies}", inline=True)
            embed.add_field(name="War Stars", value=f"⭐ {player_data.war_stars}", inline=True)

            embed.add_field(name="Donated", value=f"{player_data.donations:,}", inline=True)
            embed.add_field(name="Received", value=f"{player_data.received:,}", inline=True)
            embed.add_field(name="Capital Contributions", value=f"{player_data.clan_capital_contributions:,}", inline=True)

            # 3. Use followup because we deferred
            await interaction.followup.send(embed=embed)

        except (PlayerNotLinkedError, MissingPlayerTagError) as e:
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        except Exception as e:
            print(f"Error in player_info: {e}")
            await interaction.followup.send(f"❌ {e}")


    @app_commands.command(name="playerlevels", description="Get a player's troop & siege levels")
    @app_commands.describe(
        user="Select a Discord user", 
        player_tag="The user's tag (optional)",
        village="Choose which village to view (Default: Home)"
    )
    @app_commands.choices(village=[
        app_commands.Choice(name="Home Village", value="home"),
        app_commands.Choice(name="Builder Base", value="builder"),
        app_commands.Choice(name="Both Villages", value="both")
    ])
    async def player_troops(self, interaction: discord.Interaction, 
                             user: discord.Member = None, 
                             player_tag: str = None, 
                             village: str = "home"):
        
        await interaction.response.defer()
        
        try:
            # 1. Setup Identity & Data
            guild_id = str(interaction.guild.id)
            tag = fetch_player_from_DB(guild_id, user, player_tag)
            player_data = await get_player_data(tag)

            exclude = ['super', 'sneaky', 'ice golem', 'inferno', 'rocket balloon', 'ice hound']
            
            def format_lvl(item): 
                try:
                    max_val = item.max_level
                except (IndexError, AttributeError):
                    max_val = "?"
                max_str = '★' if item.is_max else ''
                return f"  {item.name}: {item.level}/{max_val} {max_str}"

            lines = [f"PLAYER: {player_data.name} ({player_data.tag})"]

            # 2. Home Village Logic
            if village in ["home", "both"]:
                # Filter troops (excluding sieges and specific 'super' types)
                troop_list = [format_lvl(t) for t in player_data.home_troops 
                              if not t.is_siege_machine and all(w not in t.name.lower() for w in exclude)]
                siege_list = [format_lvl(s) for s in player_data.home_troops if s.is_siege_machine]
                
                if troop_list:
                    lines.append("\n--- HOME TROOPS ---")
                    lines.extend(troop_list)
                if siege_list:
                    lines.append("\n--- SIEGE MACHINES ---")
                    lines.extend(siege_list)

            # 3. Builder Base Logic
            if village in ["builder", "both"]:
                builder_list = [format_lvl(t) for t in player_data.builder_troops]
                if builder_list:
                    lines.append("\n--- BUILDER TROOPS ---")
                    lines.extend(builder_list)

            # 4. Final Formatting (Direct Send)
            final_message = f"```yaml\n" + "\n".join(lines) + "```"
            
            # Simple safety check: Discord will 400 if it's over 2000
            if len(final_message) > 2000:
                await interaction.followup.send("⚠️ This player has too much data to display in one message. Try selecting one village at a time.", ephemeral=True)
            else:
                await interaction.followup.send(final_message)

        # 5. Clean Exception Handling
        except (PlayerNotLinkedError, MissingPlayerTagError) as e:
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        except coc.NotFound:
            await interaction.followup.send(f"❌ Clash API could not find tag: `{tag}`", ephemeral=True)
        except Exception as e:
            import sys
            _, _, exc_tb = sys.exc_info()
            print(f"Error in player_troops (Line {exc_tb.tb_lineno}): {e}")
            await interaction.followup.send("❌ An error occurred while fetching player data.", ephemeral=True)

    @app_commands.command(name="playerheroes", description="Get info on player's heroes, equipment, and pets")
    async def player_equips(self, interaction: discord.Interaction, user: discord.Member = None, player_tag: str = None):
        """Displays all equipment in a single list sorted by level."""
        try:
            tag = fetch_player_from_DB(interaction.guild.id, user, player_tag)
            player_data = await get_player_data(tag)

            builder_heroes = ['Battle Machine', 'Battle Copter']

            def format_lvl(item): 
                # Identifying rarity for the display string
                rarity = "EPIC" if item.max_level > 18 else "Common"
                max_str = '★' if item.is_max else ''
                return f"  {item.name} ({rarity}): Lvl {item.level}/{item.max_level} {max_str}"

            # 1. Format and filter Heroes
            hero_list = [
                f"  {h.name}: Lvl {h.level}/{h.max_level} {'(MAXED)' if h.is_max else ''}" 
                for h in player_data.heroes if h.name not in builder_heroes
            ]
            
            # 2. Merge and Sort ALL Equipment by level (highest first)
            # We sort the actual objects before converting to text
            sorted_equipment = sorted(player_data.equipment, key=lambda x: x.level, reverse=True)
            equipment_list = [format_lvl(e) for e in sorted_equipment]

            # 3. Sort and Format Pets
            sorted_pets = sorted(player_data.pets, key=lambda x: x.level, reverse=True)
            pet_list = [f"  {p.name}: Lvl {p.level}/{p.max_level} {'(MAXED)' if p.is_max else ''}" for p in sorted_pets]

            # Build the final YAML output
            lines = [
                f"Player: {player_data.name}",
                f"Tag: {player_data.tag}",
                "\nHeroes:",
                *hero_list,
                "Equipment:",
                *equipment_list,
                "Pets:",
                *pet_list
            ]

            res = f"```yaml\n" + "\n".join(lines) + "```"
            await interaction.response.send_message(res)
            
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayerCommands(bot))