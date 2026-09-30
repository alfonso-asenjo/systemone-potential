"""Serialize the python-sc2 BotAI view into the compact JSON that jev receives.

Keep it small: accuracy drops with irrelevant material and every token costs.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

ARMY_TYPES = {
    UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.SENTRY, UnitTypeId.ADEPT,
    UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.ARCHON, UnitTypeId.HIGHTEMPLAR,
    UnitTypeId.DARKTEMPLAR, UnitTypeId.VOIDRAY, UnitTypeId.PHOENIX, UnitTypeId.CARRIER,
    UnitTypeId.TEMPEST, UnitTypeId.DISRUPTOR, UnitTypeId.ORACLE,
}
WORKER_TYPES = {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.MULE}
NON_COMBAT_ENEMY = WORKER_TYPES | {UnitTypeId.OVERLORD, UnitTypeId.OVERSEER, UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.OBSERVER}

BASE_RADIUS = 30.0


def _name(t: UnitTypeId) -> str:
    return t.name.lower()


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _bucket(bot, pos: Point2) -> str:
    """Where a unit is, relative to the two bases."""
    for th in bot.townhalls:
        if th.distance_to(pos) < BASE_RADIUS:
            return "our_base"
    if bot.enemy_start_locations and bot.enemy_start_locations[0].distance_to(pos) < BASE_RADIUS:
        return "enemy_base"
    for st in bot.enemy_structures:
        if st.distance_to(pos) < 15:
            return "enemy_base"
    return "midmap"


def build_state(bot, recent: dict[str, Any], last_decision: dict[str, Any] | None) -> dict[str, Any]:
    time_s = bot.time
    workers = bot.workers
    army = bot.units.filter(lambda u: u.type_id in ARMY_TYPES)
    townhalls = bot.townhalls

    bases = []
    for th in townhalls.ready:
        bases.append({
            "workers": th.assigned_harvesters,
            "ideal": th.ideal_harvesters,
        })

    structures = Counter(_name(s.type_id) for s in bot.structures.ready)
    building = Counter(_name(s.type_id) for s in bot.structures.not_ready)
    army_by_type = Counter(_name(u.type_id) for u in army)
    in_production = Counter()
    for s in bot.structures.ready:
        for order in s.orders:
            in_production[str(order.ability.friendly_name).replace("Train ", "").replace("Warp In ", "").lower()] += 1

    # enemy view
    enemy_units = bot.enemy_units.filter(lambda u: u.type_id not in NON_COMBAT_ENEMY)
    enemy_by_loc: dict[str, Counter] = {"our_base": Counter(), "midmap": Counter(), "enemy_base": Counter()}
    for u in enemy_units:
        enemy_by_loc[_bucket(bot, u.position)][_name(u.type_id)] += 1
    enemy_structures = Counter(_name(s.type_id) for s in bot.enemy_structures)
    enemy_workers_seen = bot.enemy_units.filter(lambda u: u.type_id in WORKER_TYPES).amount
    enemy_bases_known = bot.enemy_structures.filter(lambda s: s.type_id in {
        UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS,
        UnitTypeId.HATCHERY, UnitTypeId.LAIR, UnitTypeId.HIVE}).amount

    army_pos = "home"
    if army:
        army_pos = _bucket(bot, army.center)
        if army_pos == "our_base":
            army_pos = "home"

    enemy_army_supply = sum(bot.calculate_supply_cost(u.type_id) for u in enemy_units)
    our_army_supply = sum(bot.calculate_supply_cost(u.type_id) for u in army)

    production_buildings = (structures.get("gateway", 0) + structures.get("warpgate", 0)
                            + structures.get("roboticsfacility", 0) + structures.get("stargate", 0))
    idle_production = sum(1 for st in bot.structures.ready if st.type_id in {
        UnitTypeId.GATEWAY, UnitTypeId.WARPGATE, UnitTypeId.ROBOTICSFACILITY, UnitTypeId.STARGATE} and st.is_idle)
    ideal_total = sum(b["ideal"] for b in bases) or 1
    assigned_total = sum(b["workers"] for b in bases)

    state = {
        "game_time": _clock(time_s),
        "race": "protoss",
        "enemy_race": bot.enemy_race.name.lower() if bot.enemy_race else "unknown",
        "resources": {"minerals": bot.minerals, "gas": bot.vespene,
                      "supply": f"{bot.supply_used}/{bot.supply_cap}",
                      "supply_maxed": bot.supply_used >= 196,
                      "unspent": ("huge" if bot.minerals + bot.vespene > 3000 else "high" if bot.minerals + bot.vespene > 1200
                                  else "normal" if bot.minerals + bot.vespene > 400 else "low")},
        "economy": {"workers": workers.amount, "bases": bases, "expanding": bool(building.get("nexus")),
                    "mineral_saturation_pct": int(100 * assigned_total / ideal_total),
                    "workers_per_base": round(workers.amount / max(1, len(bases)), 1)},
        "production": {"buildings": production_buildings, "idle": idle_production,
                       "per_base": round(production_buildings / max(1, len(bases)), 1)},
        "structures": dict(structures),
        "under_construction": dict(building),
        "army": {"supply": our_army_supply, "units": dict(army_by_type), "position": army_pos,
                 "in_production": dict(in_production),
                 "army_supply_per_worker": round(our_army_supply / max(1, workers.amount), 2)},
        "research": recent.get("research_in_progress", []),
        "enemy": {
            "army_supply_visible": enemy_army_supply,
            "units_visible": {k: dict(v) for k, v in enemy_by_loc.items() if v},
            "structures_seen": dict(enemy_structures),
            "bases_known": enemy_bases_known,
            "workers_seen": enemy_workers_seen,
        },
        "last_30s": {
            "our_units_lost": recent.get("lost", 0),
            "enemy_units_killed": recent.get("killed", 0),
            "structures_damaged": recent.get("structures_damaged", False),
        },
        "previous_decision": last_decision or {},
    }
    return state
