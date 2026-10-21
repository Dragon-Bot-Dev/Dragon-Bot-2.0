
import io
import sys
import discord
import time
import coc
from discord.ext import commands
from discord import app_commands, Embed
from coc.constants import SIEGE_MACHINE_ORDER, HOME_TROOP_ORDER, SPELL_ORDER

# Import helpers from your config and utils
from config import get_db_cursor, coc_client
from utils import (
    fetch_player_from_DB, get_player_data,
    PlayerNotLinkedError, MissingPlayerTagError
)
from services.hero_card import build_hero_image
from commands.war_commands import send_yaml_chunks

# Pets newer than coc.py's PETS_ORDER. The library files unknown pets under
# troops, so they'd be missing from Player.pets and show up as troops instead.
UNKNOWN_TO_COC_PETS = {"Greedy Raven"}


def _sorted_home_troops(player_data):
    """Home troops in game order, with troops coc.py doesn't know about last
    (the library sorts them first). Needs a player fetched with
    load_game_data=False, otherwise unknown troops make home_troops raise."""
    order = {name: i for i, name in enumerate(HOME_TROOP_ORDER)}
    return sorted(player_data.home_troops, key=lambda t: order.get(t.name, len(order)))


def _home_heroes(player_data):
    """All home-village heroes. Player.heroes only returns names in coc.py's
    fixed HERO_ORDER, silently dropping newer heroes (e.g. Dragon Duke), so
    read the library's underlying hero iterator instead. It can only be read
    once, so call this once per command and pass the result around."""
    try:
        heroes = list(player_data._iter_heroes)
    except Exception:
        heroes = []
    if not heroes:
        heroes = list(player_data.heroes)
    return [h for h in heroes if h.is_home_base]


def _sorted_spells(player_data):
    """Spells in game order, with ones coc.py doesn't know about last (the
    library sorts them first)."""
    order = {name: i for i, name in enumerate(SPELL_ORDER)}
    return sorted(player_data.spells, key=lambda s: order.get(s.name, len(order)))


def _all_pets(player_data):
    extra = [t for t in player_data.home_troops if t.name in UNKNOWN_TO_COC_PETS]
    return list(player_data.pets) + extra


def _hero_image_data(hero_objs, pet_objs):
    """Plain dicts for services.hero_card (heroes with their equipped gear,
    plus pets)."""
    heroes = [
        {
            "name": h.name, "level": h.level, "is_max": h.is_max,
            "gear": [{"name": e.name, "level": e.level, "is_max": e.is_max} for e in h.equipment],
        }
        for h in hero_objs
    ]
    pets = [{"name": p.name, "level": p.level, "is_max": p.is_max} for p in pet_objs]
    return heroes, pets


def _heroes_yaml_lines(player_data, hero_objs, pet_objs):
    """Text fallback for /playerheroes, used if the image can't be rendered."""
    def format_lvl(item):
        rarity = "EPIC" if item.max_level > 18 else "Common"
        max_str = '★' if item.is_max else ''
        return f"  {item.name} ({rarity}): Lvl {item.level}/{item.max_level} {max_str}"

    hero_list = [
        f"  {h.name}: Lvl {h.level}/{h.max_level} {'(MAXED)' if h.is_max else ''}"
        for h in hero_objs
    ]
    equipment_list = [format_lvl(e) for e in sorted(player_data.equipment, key=lambda x: x.level, reverse=True)]
    pet_list = [
        f"  {p.name}: Lvl {p.level}/{p.max_level} {'(MAXED)' if p.is_max else ''}"
        for p in sorted(pet_objs, key=lambda x: x.level, reverse=True)
    ]
    return [
        f"Player: {player_data.name}",
        f"Tag: {player_data.tag}",
        "\nHeroes:", *hero_list,
        "Equipment:", *equipment_list,
        "Pets:", *pet_list,
    ]

class PlayerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="playerinfo", description="Get player's general information")
    @app_commands.describe(user="Select a Discord user", player_tag="The user's tag (optional)")
    async def player_info(self, interaction: discord.Interaction, user: discord.User = None, player_tag: str = None):
        await interaction.response.defer()

        try:
            target_user = user or interaction.user
         #   guild_id = str(interaction.guild.id)
            
            # Assuming fetch_player_from_DB is updated to handle string IDs
            tag = fetch_player_from_DB(None, target_user, player_tag)
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
                title=f"User: {player_data.name} {player_data.tag}",
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


    @app_commands.command(name="playerlevels", description="Get a player's troop, siege & spell levels")
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
                             user: discord.User = None, 
                             player_tag: str = None, 
                             village: str = "home"):
        
        await interaction.response.defer()
        
        try:
            target_user = user or interaction.user
            tag = fetch_player_from_DB(None, target_user, player_tag)
            # Don't rely on coc.py's static data here: it lags the game, and one
            # unrecognised troop makes Player.home_troops raise for the whole player.
            player_data = await get_player_data(tag, load_game_data=False)

            exclude = ['super', 'sneaky', 'ice golem', 'inferno', 'rocket balloon', 'ice hound']
            
            def format_lvl(item): 
                try:
                    max_val = item.max_level
                except (IndexError, AttributeError):
                    max_val = "?"
                max_str = '★' if item.is_max else ''
                return f"  {item.name}: {item.level}/{max_val} {max_str}"

            lines = [f"PLAYER: {player_data.name} ({player_data.tag})"]

            # 
            if village in ["home", "both"]:
                # Without static data there's no is_siege_machine flag, so sieges are
                # identified by name. Troops unknown to coc.py sort last, not first.
                home_troops = [t for t in _sorted_home_troops(player_data) if t.name not in UNKNOWN_TO_COC_PETS]
                # Filter troops (excluding sieges and specific 'super' types)
                troop_list = [format_lvl(t) for t in home_troops
                              if t.name not in SIEGE_MACHINE_ORDER and all(w not in t.name.lower() for w in exclude)]
                siege_list = [format_lvl(s) for s in home_troops if s.name in SIEGE_MACHINE_ORDER]
                
                if troop_list:
                    lines.append("\n--- HOME TROOPS ---")
                    lines.extend(troop_list)
                if siege_list:
                    lines.append("\n--- SIEGE MACHINES ---")
                    lines.extend(siege_list)

                spell_list = [format_lvl(sp) for sp in _sorted_spells(player_data)]
                if spell_list:
                    lines.append("\n--- SPELLS ---")
                    lines.extend(spell_list)

            # 
            if village in ["builder", "both"]:
                builder_list = [format_lvl(t) for t in player_data.builder_troops]
                if builder_list:
                    lines.append("\n--- BUILDER TROOPS ---")
                    lines.extend(builder_list)

            #
            # Troops + sieges + spells can exceed Discord's 2000-char limit; split into several messages.
            await send_yaml_chunks(interaction.followup.send, lines)

        # 5. Clean Exception Handling
        except (PlayerNotLinkedError, MissingPlayerTagError) as e:
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        except coc.NotFound:
            await interaction.followup.send(f"❌ Clash API could not find tag: `{tag}`", ephemeral=True)
        except Exception as e:
            _, _, exc_tb = sys.exc_info()
            print(f"Error in player_troops (Line {exc_tb.tb_lineno}): {e}")
            await interaction.followup.send("❌ An error occurred while fetching player data.", ephemeral=True)

    @app_commands.command(name="playerheroes", description="Get info on player's heroes, equipment, and pets")
    async def player_equips(self, interaction: discord.Interaction, user: discord.User = None, player_tag: str = None):
        """Renders heroes (with equipped gear) and pets as an image."""
        # Image rendering + icon downloads can outlast Discord's 3s window.
        await interaction.response.defer()

        try:
            target_user = user or interaction.user
            tag = fetch_player_from_DB(None, target_user, player_tag)
            # See /playerlevels: avoid coc.py's lagging static data.
            player_data = await get_player_data(tag, load_game_data=False)

            hero_objs, pet_objs = _home_heroes(player_data), _all_pets(player_data)
            heroes, pets = _hero_image_data(hero_objs, pet_objs)
            if not heroes and not pets:
                return await interaction.followup.send(f"**{player_data.name}** has no heroes or pets yet.")

            try:
                png = await build_hero_image(heroes, pets)
            except Exception as render_err:
                # Never leave the user with nothing: fall back to the old text output.
                print(f"⚠️ Hero image render failed, using text fallback: {render_err}")
                return await send_yaml_chunks(interaction.followup.send, _heroes_yaml_lines(player_data, hero_objs, pet_objs))

            embed = discord.Embed(title=f"{player_data.name} ({player_data.tag})", color=0x3498db)
            embed.set_image(url="attachment://heroes.png")
            await interaction.followup.send(embed=embed, file=discord.File(io.BytesIO(png), filename="heroes.png"))

        except (PlayerNotLinkedError, MissingPlayerTagError) as e:
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayerCommands(bot))