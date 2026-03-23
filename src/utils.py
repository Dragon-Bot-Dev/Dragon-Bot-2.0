import re
import coc
import time
from datetime import datetime, timedelta, timezone
from config import get_db_cursor, coc_client

# --- Custom Errors ---
class ClanTagError(Exception): pass
class ClanNotSetError(ClanTagError):
    def __init__(self):
        super().__init__("No clan tag is set for this server. Use `/setclantag` first.")

class PlayerTagError(Exception): pass
class PlayerNotLinkedError(PlayerTagError):
    def __init__(self, mention: str):
        super().__init__(f"{mention} has not linked a Clash of Clans account.")

# --- Database Helpers ---
def fetch_clan_from_db(guild_id: int, provided_tag: str = None) -> str:
    cursor = get_db_cursor()
    if provided_tag:
        tag = provided_tag.strip().upper()
        return tag if tag.startswith("#") else f"#{tag}"

    cursor.execute("SELECT clan_tag FROM servers WHERE guild_id = %s", (guild_id,))
    row = cursor.fetchone()
    if row and row[0]:
        tag = row[0].strip().upper()
        return tag if tag.startswith("#") else f"#{tag}"
    raise ClanNotSetError()

def fetch_player_from_DB(guild_id: int, user=None, provided_tag: str = None) -> str:
    if provided_tag:
        return provided_tag.strip().upper()
    
    if user:
        cursor = get_db_cursor()
        cursor.execute("SELECT player_tag FROM players WHERE discord_id = %s AND guild_id = %s", (user.id, guild_id))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        raise PlayerNotLinkedError(user.display_name)
    raise PlayerTagError("Please provide a player tag or mention a linked user.")

# --- Formatting Helpers ---
def format_datetime(dt):
    if not dt or dt == "N/A": return "N/A"
    dt_obj = dt.time.replace(tzinfo=timezone.utc) if hasattr(dt, 'time') else None
    if not dt_obj: return "N/A"
    est = dt_obj.astimezone(timezone(timedelta(hours=-5)))
    return est.strftime('%Y-%m-%d %H:%M:%S %p EST')

def format_month_day_year(dt):
    if not dt or dt == "N/A": return "N/A"
    dt_obj = dt.time.replace(tzinfo=timezone.utc) if hasattr(dt, 'time') else None
    if not dt_obj: return "N/A"
    est = dt_obj.astimezone(timezone(timedelta(hours=-5)))
    return est.strftime('%m-%d-%Y')

def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

# 1. Update Validation Functions
async def check_coc_clan_tag(clan_tag): 
    try:
        # get_clan automatically handles the tag normalization and API call
        await coc_client.get_clan(clan_tag)
        return True
    except coc.NotFound:
        return False
    except coc.ClashOfClansException:
        return False

async def check_coc_player_tag(player_tag): 
    try:
        await coc_client.get_player(player_tag)
        return True
    except coc.NotFound:
        return False
    except coc.ClashOfClansException:
        return False


# --- Data Retrieval Helpers ---

async def get_player_data(player_tag: str):
    """
    Fetches full player profile using coc_client.
    """
    try:
        # Returns a Player object with attributes like player.name, player.town_hall, etc.
        player = await coc_client.get_player(player_tag)
        return player
    except coc.NotFound:
        raise RuntimeError(f"Clash API Error (404): Player {player_tag} not found.")
    except coc.ClashOfClansException as e:
        raise RuntimeError(f"Clash API Error: {e}")


async def get_clan_data(clan_tag: str):
    try:
        return await coc_client.get_clan(clan_tag)
    except coc.NotFound:
        raise RuntimeError(f"Clan {clan_tag} not found.")
    except Exception as e:
        raise RuntimeError(f"Clash API Error: {e}")

# async def get_war_log_data(clan_tag: str):
#     try:
#         return await coc_client.get_war_log(clan_tag)
#     except coc.PrivateWarLog:
#         raise RuntimeError("The clan's war log is private.")
#     except Exception as e:
#         raise RuntimeError(f"Clash API Error: {e}")
    
async def get_capital_raid_data(clan_tag: str):
    """
    Manually constructs a dictionary from RaidLogEntry objects.
    Maps coc.py attributes (like hall_level) to the keys used in your command.
    """
    try:
        # Fetch the raid log (returns a list of RaidLogEntry objects)
        raids = await coc_client.get_raid_log(clan_tag)
        
        items = []
        for raid in raids:
            # Construct the dictionary for each raid season
            raid_dict = {
                "state": raid.state,
                "startTime": raid.start_time, # Keep as object for format_datetime
                "endTime": raid.end_time,     # Keep as object for format_datetime
                "capitalTotalLoot": raid.total_loot,
                "totalAttacks": raid.attack_count,
                "offensiveReward": raid.offensive_reward,
                "defensiveReward": raid.defensive_reward,
                "enemyDistrictsDestroyed": raid.destroyed_district_count,
                
                # Mapping the attackLog using the RaidClan documentation provided
                "attackLog": [
                    {
                        "districts": [
                            {
                                "name": d.name,
                                "districtHallLevel": d.hall_level, # Mapping hall_level to districtHallLevel
                                "destructionPercent": d.destruction # Mapping destruction to destructionPercent
                            } for d in clan.districts
                        ]
                    } for clan in raid.attack_log # attack_log is a List[RaidClan]
                ],
                
                # Use Tag as the unique identifier for member tracking
                "members": [
                    {
                        "name": m.name,
                        "tag": m.tag,
                        "attacks": m.attack_count,
                        "capitalResourcesLooted": m.capital_resources_looted
                    } for m in raid.members
                ]
            }
            items.append(raid_dict)
        
        return {"items": items}
        
    except coc.NotFound:
        raise RuntimeError(f"Clash API Error (404): No raid data found for {clan_tag}.")
    except coc.ClashOfClansException as e:
        print(f"\n[!] CLASH API ERROR (Raid Data): {e}\n")
        raise RuntimeError(f"Clash API Error: {e}")
    
async def calculate_raid_season_stats(clan_tag: str):
    """Fetches raid data and prepares a clean dictionary for the command."""
    raid_data = await get_capital_raid_data(clan_tag)
    seasons = raid_data.get('items', [])
    
    if not seasons:
        return None

    entry = seasons[0] # This defines the 'entry' for the calculations
    
    # Member stats tracking by Tag to fix the "9 attacks" name bug
    member_stats = {} 
    for m in entry.get('members', []):
        m_tag = m.get('tag')
        if m_tag not in member_stats:
            member_stats[m_tag] = {"name": m.get('name'), "loot": 0, "atks": 0}
        member_stats[m_tag]["loot"] += m.get('capitalResourcesLooted', 0)
        member_stats[m_tag]["atks"] += m.get('attacks', 0)

    sorted_m = sorted(member_stats.values(), key=lambda x: x["loot"], reverse=True)
    stats_text = "\n".join([f"{i+1}. {m['name']}: {m['loot']:,} loot, {m['atks']} atks" for i, m in enumerate(sorted_m)])

    return {
        "state": entry.get('state', 'N/A'),
        "start": format_datetime(entry.get('startTime')),
        "end": format_datetime(entry.get('endTime')),
        "loot": entry.get('capitalTotalLoot', 0),
        "medals": calculate_medals(entry), # We call the math helper here!
        "stats_text": stats_text
    }
    
def calculate_medals(entry):
    """
    Calculates medals for a single raid entry. 
    Returns a string: 'Estimated Medals: X' (ongoing) or 'X' (ended).
    """
    state = entry.get('state', 'N/A')
    offensive_reward = entry.get('offensiveReward', 0)
    defensive_reward = entry.get('defensiveReward', 0)
    total_clan_attacks = entry.get('totalAttacks', 1) 

    if state == 'ongoing':
        raw_pool = 0
        attack_log = entry.get('attackLog', [])
        for clan in attack_log:
            for district in clan.get('districts', []):
                level = int(district.get('districtHallLevel', 0))
                if district.get('destructionPercent') == 100:
                    if district.get('name') == "Capital Peak":
                        medal_map = {10:1450, 9:1375, 8:1260, 7:1240, 6:1115, 5:810, 4:585, 3:360, 2:180}
                        raw_pool += medal_map.get(level, 0)
                    else:
                        medal_map = {5:460, 4:405, 3:350, 2:225, 1:135}
                        raw_pool += medal_map.get(level, 0)
        
        # Per-player estimate: (Total Pool / Clan Attacks) * 6
        estimate = (raw_pool / max(1, total_clan_attacks)) * 6
        return f"Estimated to be {round(estimate):,}"
    
    else:
        # Final medals for completed raids
        final_total = (offensive_reward * 6.0) + defensive_reward
        return f"{round(final_total):,}"

async def get_current_war_data(clan_tag: str, war_tag: str = None):
    try:
        if war_tag:
            war = await coc_client.get_league_war(war_tag)
        else:
            war = await coc_client.get_current_war(clan_tag)
        
        if not war or war.state == 'notInWar':
            return None
            
        # Manually construct the dictionary for the command to use
        return {
            "state": war.state,
            "startTime": war.start_time, # Keep as object for format_datetime
            "endTime": war.end_time,
            "clan": {
                "tag": war.clan.tag,
                "name": war.clan.name,
                "stars": war.clan.stars,
                "destructionPercentage": war.clan.destruction,
                "attacks": war.clan.attacks_used,
                "total_attacks": war.clan.total_attacks,
                "max_stars": war.clan.max_stars,
                "badge": war.clan.badge.url,

                "members": [
                    {
                        "name": m.name,
                        "tag": m.tag,
                        "townhallLevel": m.town_hall,
                        "attacks": [
                            {
                                "stars": a.stars, 
                                "destructionPercentage": a.destruction
                            } for a in m.attacks
                        ]
                    } for m in war.clan.members
                ]
            },
            "opponent": {
                "tag": war.opponent.tag,
                "name": war.opponent.name,
                "stars": war.opponent.stars,
                "destructionPercentage": war.opponent.destruction,
                "badge": war.opponent.badge.url
            }
        }
    except coc.PrivateWarLog:
        raise RuntimeError("War data is private for this clan.")
    except coc.ClashOfClansException as e:
        raise RuntimeError(f"Clash API Error: {e}") 


async def get_cwl_data(clan_tag: str):
    try:
        group = await coc_client.get_league_group(clan_tag)
        if not group:
            return None
            
        return {
            "state": group.state,
            "season": group.season,
            "clans": [{"name": c.name, "tag": c.tag, "level": c.level} for c in group.clans],
            "rounds": [
                {"warTags": r.war_tags} for r in group.rounds
            ]
        }
    except coc.NotFound:
        return None 
    except coc.ClashOfClansException as e:
        raise RuntimeError(f"Clash API Error: {e}")

async def get_war_log_data(clan_tag: str):
    """
    Fetches the war log for a single clan.
    Returns a list of raw coc.ClanWarLogEntry objects.
    """
    try:
        # Fetch the log for the specific tag provided
        war_log = await coc_client.get_war_log(clan_tag)
        return war_log

    except coc.PrivateWarLog:
        # Return an empty list so the command can handle the 'Private' message
        return []
    except coc.NotFound:
        # Raise an error to be caught by the command's try/except block
        raise RuntimeError(f"No clan found with tag {clan_tag}.")
    except coc.ClashOfClansException as e:
        print(f"\n[!] CLASH API ERROR (War Log): {e}\n")
        return []



class PlayerTagError(Exception):
    """Base for our player‐tag lookup errors."""

class PlayerNotLinkedError(PlayerTagError):
    """Raised when a mentioned user has no tag in the DB."""
    def __init__(self, mention: str):
        super().__init__(f"{mention} has not linked a Clash of Clans account.")

class MissingPlayerTagError(PlayerTagError):
    """Raised when neither a user nor a player_tag was provided."""
    def __init__(self):
        super().__init__("Please provide a player tag or mention a linked user.")


