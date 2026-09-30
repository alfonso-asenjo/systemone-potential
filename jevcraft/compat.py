"""Runtime patches for python-sc2 against a newer StarCraft II build.

The installed game reports ability ids that the library's AbilityId enum does not
know (e.g. 4135 on Base97563). python-sc2 drops those from game_data.abilities and
then crashes with KeyError when a unit carries such an order. Here we:

  1. keep the raw ability table so unknown ids can be remapped to the generic
     ability the game itself points at (remaps_to_ability_id), and
  2. skip orders that cannot be resolved at all, logging each id once.

Import this module before creating the bot.
"""
from __future__ import annotations

import functools

from loguru import logger
from sc2 import game_data as _gd
from sc2 import unit as _unit
from sc2.unit import UnitOrder

_reported: set[int] = set()

from sc2.ids.ability_id import AbilityId  # noqa: E402

# (substring of link_name, AbilityId to use instead)
MANUAL_REMAP = [
    ("WorkerStopIdleAbilityVespene", AbilityId.HARVEST_GATHER_PROBE),
    ("WorkerStopIdleAbility", AbilityId.HARVEST_GATHER_PROBE),
]

# -- 1. keep raw ability protos -------------------------------------------------
_orig_gd_init = _gd.GameData.__init__


def _gd_init(self, data):
    _orig_gd_init(self, data)
    self.raw_abilities = {a.ability_id: a for a in data.abilities}


_gd.GameData.__init__ = _gd_init


def resolve_ability(game_data, ability_id: int):
    """Return an AbilityData for ability_id, remapping unknown ids when the game allows it."""
    ab = game_data.abilities.get(ability_id)
    if ab is not None:
        return ab
    raw = getattr(game_data, "raw_abilities", {}).get(ability_id)
    remap = raw.remaps_to_ability_id if raw is not None else 0
    if remap and remap in game_data.abilities:
        return game_data.abilities[remap]
    if raw is not None:
        for needle, fallback in MANUAL_REMAP:
            if needle in raw.link_name and fallback.value in game_data.abilities:
                return game_data.abilities[fallback.value]
    if ability_id not in _reported:
        _reported.add(ability_id)
        name = f"{raw.link_name}/{raw.button_name}" if raw is not None else "?"
        logger.warning(f"[compat] unknown ability id {ability_id} ({name}), orders using it are ignored")
    return None


# -- 2. tolerant Unit.orders ------------------------------------------------------
def _orders(self):
    out = []
    for order in self._proto.orders:
        ab = resolve_ability(self._bot_object.game_data, order.ability_id)
        if ab is None:
            continue
        target = order.target_unit_tag
        if order.HasField("target_world_space_pos"):
            from sc2.position import Point2
            target = Point2.from_proto(order.target_world_space_pos)
        elif order.HasField("target_unit_tag"):
            target = order.target_unit_tag
        out.append(UnitOrder(ability=ab, target=target, progress=order.progress))
    return out


_cp = functools.cached_property(_orders)
_cp.__set_name__(_unit.Unit, "orders")
_unit.Unit.orders = _cp


# -- 3. game window size --------------------------------------------------------
# run_game() does not expose SC2Process(resolution=...), so we inject it here.
from sc2 import sc2process as _sp  # noqa: E402

WINDOW: dict = {"resolution": None, "placement": (0, 0)}

_orig_sp_init = _sp.SC2Process.__init__


def _sp_init(self, *args, **kwargs):
    if kwargs.get("resolution") is None and WINDOW["resolution"]:
        kwargs["resolution"] = WINDOW["resolution"]
        kwargs.setdefault("placement", WINDOW["placement"])
    _orig_sp_init(self, *args, **kwargs)


_sp.SC2Process.__init__ = _sp_init
