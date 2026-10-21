"""Up-to-date unit classification (which troops are siege machines, which
names are pets).

The Clash API lumps troops, sieges and pets into one list with no flag to tell
them apart, and coc.py's bundled data lags the game (it didn't know Sky Wagon
or the Greedy Raven pet). ClashKing publishes game data in the same format
(https://assets.clashk.ing/static_data/), so classify from that: a siege
machine is a home-village troop produced by the Workshop, and pets come from
pets.json. New units are then picked up automatically.

If the host can't be reached, falls back to coc.py's lists plus a few names
known to be missing from them.
"""

import time

import aiohttp
from coc.constants import PETS_ORDER, SIEGE_MACHINE_ORDER

from services.hero_card import ASSET_BASE

STATIC_BASE = f"{ASSET_BASE}/static_data"
_REFRESH_SECONDS = 24 * 3600
_RETRY_SECONDS = 300

# Used only when the fetch fails; known gaps in coc.py 4.0.0's lists.
_FALLBACK_SIEGE_EXTRA = {"Sky Wagon"}
_FALLBACK_PETS_EXTRA = {"Greedy Raven"}

_siege_machines = set(SIEGE_MACHINE_ORDER) | _FALLBACK_SIEGE_EXTRA
_pets = set(PETS_ORDER) | _FALLBACK_PETS_EXTRA
_next_refresh = 0.0


def siege_machine_names():
    return _siege_machines


def pet_names():
    return _pets


async def _get_items(session, name):
    async with session.get(f"{STATIC_BASE}/{name}.json") as resp:
        resp.raise_for_status()
        return (await resp.json(content_type=None))["items"]


async def ensure_loaded():
    """Refreshes the cached sets at most once a day. Never raises: on any
    failure the previous (or fallback) sets stay in use."""
    global _siege_machines, _pets, _next_refresh
    if time.time() < _next_refresh:
        return
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "DragonBot/2.0"}) as session:
            troops = await _get_items(session, "troops")
            pets = await _get_items(session, "pets")

        sieges = {t["name"] for t in troops
                  if t.get("production_building") == "Workshop" and t.get("village") == "home"}
        pet_set = {p["name"] for p in pets}
        if sieges and pet_set:
            # Union with coc.py's lists so nothing it already knows is ever lost.
            _siege_machines = sieges | set(SIEGE_MACHINE_ORDER)
            _pets = pet_set | set(PETS_ORDER)
            _next_refresh = time.time() + _REFRESH_SECONDS
            return
        raise ValueError("empty unit data")
    except Exception as e:
        print(f"⚠️ Could not refresh unit data, using fallback lists: {e}")
        _next_refresh = time.time() + _RETRY_SECONDS
