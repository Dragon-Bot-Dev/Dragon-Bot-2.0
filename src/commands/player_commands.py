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
        """Displays full player profile using dot notation."""
        cursor = get_db_cursor()
        guild_id = interaction.guild.id

        try:
            tag = fetch_player_from_DB(guild_id, user, player_tag)
            player_data = await get_player_data(tag)
            
            player_labels = ", ".join(label.name for label in player_data.labels) if player_data.labels else "None"
            timestamp = int(time.time())

            # Map the role object to your display string
            role_mapping = {'admin': "Elder", 
                            'coleader': "Co-Leader", 
                            'leader': "Leader", 
                            'member': "Member"}
            display_role = role_mapping.get(str(player_data.role).lower(), str(player_data.role).capitalize())

            embed = discord.Embed(
                title=f"User: {player_data.name}, {player_data.tag}",
                description=f"{player_labels}\nLast updated: <t:{timestamp}:R>",
                color=0x0000FF
            )
            
            if player_data.league:
                embed.set_thumbnail(url=player_data.league.icon.url)
            
            if player_data.clan:
                embed.add_field(name="Clan Name", value=player_data.clan.name, inline=True)
                embed.add_field(name="Tag", value=player_data.clan.tag, inline=True)
            
            embed.add_field(name="Role", value=display_role, inline=True)
            embed.add_field(name="TH Lvl", value=player_data.town_hall, inline=True)
            embed.add_field(name="Exp Lvl", value=player_data.exp_level, inline=True)

            # coc.py uses .war_opt_in which returns a boolean or specific string
            pref = player_data.war_opted_in or "Unknown" 
            if pref == True:
                pref = "Opted In"
            elif pref == False:
                pref = "Opted Out"
            elif pref == None:
                pref = "Not in a clan"
            print(f"War Preference Raw: {player_data.war_opted_in}")
            
            embed.add_field(name="War Preference", value=f"{pref}", inline=True)

            embed.add_field(name="Trophies", value=f":trophy: {player_data.trophies}", inline=True)
            embed.add_field(name="Best Trophies", value=f":trophy: {player_data.best_trophies}", inline=True)
            embed.add_field(name="War Stars", value=f":star: {player_data.war_stars}", inline=True)
            embed.add_field(name="Donated", value=f"{player_data.donations:,}", inline=True)
            embed.add_field(name="Received", value=f"{player_data.received:,}", inline=True)
            embed.add_field(name="Capital Contributions", value=f"{player_data.clan_capital_contributions:,}", inline=True)

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="playerlevels", description="Get a player's troop, siege, & spell levels")
    @app_commands.describe(user="Select a user", village="home (default), builder, or both")
    async def player_troops(self, interaction: discord.Interaction, user: discord.Member = None, player_tag: str = None, village: str = "home"):
        """Filters and displays troop and pet levels."""
        cursor = get_db_cursor()
        try:
            tag = fetch_player_from_DB(interaction.guild.id, user, player_tag)
            player_data = await get_player_data(tag)

            exclude = ['super', 'sneaky', 'ice golem', 'inferno', 'rocket balloon', 'ice hound']
            def format_lvl(item): 
                max_str = '(MAXED)' if item.is_max else ''
                return f"{item.name}: Level {item.level}/{item.max_level} {max_str}"

            v_type = village.lower()
            troop_list = []
            siege_list = []
            spell_list = []

            if v_type == 'builder':
                troop_list = [format_lvl(t) for t in player_data.builder_troops if all(w not in t.name.lower() for w in exclude)]
            else:
                # 1. Filter standard troops (Not a siege machine AND not excluded)
                troop_list = [
                    format_lvl(t) for t in player_data.home_troops 
                    if not t.is_siege_machine and all(w not in t.name.lower() for w in exclude)
                ]
                
                # 2. Filter siege machines specifically
                siege_list = [
                    format_lvl(s) for s in player_data.home_troops 
                    if s.is_siege_machine
                ]
                
                # 3. Get pets
                spell_list = [format_lvl(p) for p in player_data.spells]

            # Build the result string with clear headers
            lines = [f"Name: {player_data.name}\nTag: {player_data.tag}"]
            
            if troop_list:
                lines.append("\nTroops:")
                lines.extend(troop_list)
            
            if siege_list:
                lines.append("\nSiege Machines:")
                lines.extend(siege_list)
                
            if spell_list:
                lines.append("\nSpells:")
                lines.extend(spell_list)

            res = f"```yaml\n" + "\n".join(lines) + "```"
            await interaction.response.send_message(res)
            
        except Exception as e:
            # Note: We use followup.send if the response was deferred, 
            # but since we aren't deferring here, response.send_message is fine.
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)

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
                max_str = '(MAXED)' if item.is_max else ''
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

    @app_commands.command(name="playerspells", description="Get player's spell levels")
    async def player_spells(self, interaction: discord.Interaction, user: discord.Member = None, player_tag: str = None):
        """Lists all unlocked spells and their levels."""
        try:
            tag = fetch_player_from_DB(interaction.guild.id, user, player_tag)
            player_data = await get_player_data(tag)

            spells = "\n".join([f"{s.name}: {s.level}/{s.max_level}" for s in player_data.spells])
            await interaction.response.send_message(f"```yaml\n{player_data.name}'s Spells:\n{spells}```")
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayerCommands(bot))