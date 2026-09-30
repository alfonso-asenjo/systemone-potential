"""The soldier: a simple Protoss bot whose priorities are set by the commander (jev).

jev decides *what* (macro focus, army stance). This code decides *how*.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from . import compat  # noqa: F401  (patches python-sc2 for newer game builds)
from .commander import Commander, Decision
from .config import settings
from .dashboard import Dashboard
from .state import ARMY_TYPES, NON_COMBAT_ENEMY, build_state

MAX_WORKERS = 66
MAX_BASES = 5
GATEWAYS_PER_BASE = 3


class JevProtoss(BotAI):
    def __init__(self, use_jev: bool = True, dashboard_port: int = settings.dashboard_port, chat: bool = False,
                 skip: float = 0.0):
        super().__init__()
        self.skip = skip                      # game seconds to fast-forward (rule mode) before pacing to realtime
        self._jev_wanted = use_jev
        self.use_jev = use_jev and skip <= 0
        self._pace: tuple[float, float] | None = None   # (wall time, game time) when realtime pacing started
        self.chat_enabled = chat
        self.dashboard = Dashboard(dashboard_port)
        self.commander = Commander(settings, broadcast=self.dashboard.broadcast, enabled=use_jev)
        self.commander.on_change = self._on_decision_change
        self.recent_lost: list[float] = []
        self.recent_killed: list[float] = []
        self.last_structure_damage = -999.0
        self.rally: Point2 | None = None
        self.forward: Point2 | None = None
        self._last_rule_tick = 0.0
        self._last_distribute = 0

    # ------------------------------------------------------------- lifecycle
    async def on_start(self):
        await self.dashboard.start()
        await self.commander.start("sc2")
        self.rally = self.main_base_ramp.top_center.towards(self.game_info.map_center, 6)
        nat = await self.get_next_expansion()
        if nat:
            self.rally = nat.towards(self.game_info.map_center, 8)
        self.forward = self.game_info.map_center.towards(self.enemy_start_locations[0], 10)
        print(f"[bot] jev={'on' if self.use_jev else 'off (rule mode)'} provider={settings.provider}")

    async def on_end(self, game_result):
        print(f"[bot] game over: {game_result} at {int(self.time // 60)}:{int(self.time % 60):02d} | jev calls={self.commander.client.total_calls} "
              f"cost=${self.commander.client.total_cost:.4f} errors={self.commander.errors}")
        await self.dashboard.broadcast({"type": "end", "result": str(game_result)})
        await self.commander.close()
        await self.dashboard.stop()

    async def on_unit_destroyed(self, unit_tag: int):
        unit = self._all_units_previous_map.get(unit_tag) if hasattr(self, "_all_units_previous_map") else None
        if unit is None:
            return
        if unit.is_mine and unit.type_id in ARMY_TYPES:
            self.recent_lost.append(self.time)
        elif unit.is_enemy and not unit.is_structure and unit.type_id not in NON_COMBAT_ENEMY:
            self.recent_killed.append(self.time)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_structure and unit.is_mine:
            self.last_structure_damage = self.time

    # ------------------------------------------------------------- main loop
    async def on_step(self, iteration: int):
        await self._pacing()
        self._trim_recent()
        d = self.commander.decision

        # 1. ask the commander (non-blocking, one request in flight)
        if self.use_jev:
            if self.commander.task is None or self.commander.task.done():
                if time.monotonic() - self.commander.last_call_at >= settings.decision_interval:
                    state = build_state(self, self._recent(), d.short())
                    self.commander.maybe_tick(state, self.time)
        else:
            await self._rule_commander()

        # 2. baseline macro that always runs
        if iteration - self._last_distribute >= 12:
            self._last_distribute = iteration
            await self.distribute_workers()
        await self._supply()
        await self._gas()
        await self._chrono()
        await self._first_buildings()

        # 3. priorities set by the commander
        await self._macro(d.macro_focus)
        await self._army(d.army_stance, d.threat)

        # 4. in-game overlay (python-sc2 sends the debug draw list itself every step)
        self._overlay(d)

    # ------------------------------------------------------------- helpers
    async def _pacing(self):
        """With --skip: run at full speed until `skip` game seconds, then hold the game at realtime speed."""
        if self.skip <= 0:
            return
        if self._pace is None:
            if self.time < self.skip:
                return
            self._pace = (time.monotonic(), self.time)
            self.use_jev = self._jev_wanted
            print(f"[bot] fast-forward done at {int(self.time // 60)}:{int(self.time % 60):02d}, "
                  f"now realtime with jev={'on' if self.use_jev else 'off'}")
            await self.dashboard.broadcast({"type": "info", "message": "fast-forward done, jev takes command"})
        wall0, game0 = self._pace
        expected = wall0 + (self.time - game0)
        now = time.monotonic()
        if now < expected:
            await asyncio.sleep(expected - now)

    def _trim_recent(self):
        cutoff = self.time - 30
        self.recent_lost = [t for t in self.recent_lost if t > cutoff]
        self.recent_killed = [t for t in self.recent_killed if t > cutoff]

    def _recent(self) -> dict[str, Any]:
        research = []
        for s in self.structures.ready:
            for o in s.orders:
                name = str(o.ability.friendly_name)
                if name.startswith("Research"):
                    research.append(name.replace("Research ", "").lower())
        return {
            "lost": len(self.recent_lost),
            "killed": len(self.recent_killed),
            "structures_damaged": self.time - self.last_structure_damage < 30,
            "research_in_progress": research,
        }

    async def _on_decision_change(self, prev: Decision, new: Decision):
        if not self.chat_enabled:
            return
        parts = []
        if new.macro_focus != prev.macro_focus:
            parts.append(f"macro -> {new.macro_focus} ({new.confidence.get('macro_focus', 0):.0%})")
        if new.army_stance != prev.army_stance:
            parts.append(f"army -> {new.army_stance} ({new.confidence.get('army_stance', 0):.0%})")
        if parts:
            await self.chat_send("[jev] " + " | ".join(parts))

    def _overlay(self, d: Decision):
        c = self.client
        y = 0.02
        lines = [
            (f"jev commander  ({settings.provider})", (255, 255, 255)),
            (f"macro: {d.macro_focus.upper()}  {d.confidence.get('macro_focus', 0):.0%}", (120, 200, 255)),
            (f"army:  {d.army_stance.upper()}  {d.confidence.get('army_stance', 0):.0%}", (255, 190, 90)),
            (f"threat: {d.threat:.1f}/3   rushing: {d.enemy_rushing:.0%}   ahead: {d.ahead:.0%}", (255, 120, 120)),
            (f"calls: {self.commander.client.total_calls}  cost: ${self.commander.client.total_cost:.4f}"
             + (f"  errors: {self.commander.errors}" if self.commander.errors else ""), (170, 170, 170)),
        ]
        if d.fallback:
            lines.append((f"low confidence, kept previous: {', '.join(d.fallback)}", (255, 220, 120)))
        if d.held:
            lines.append((f"near tie, held: {', '.join(d.held)}", (200, 200, 200)))
        res = compat.WINDOW.get("resolution") or (1024, 768)
        size = max(14, int(res[1] / 55))
        for text, color in lines:
            c.debug_text_screen(text, pos=(0.01, y), color=color, size=size)
            y += size / res[1] * 1.6

    # ------------------------------------------------------------- baseline macro
    async def _supply(self):
        if self.supply_cap >= 200:
            return
        pending = self.already_pending(UnitTypeId.PYLON)
        need = 6 if self.supply_cap < 40 else 10
        if self.supply_left < need and pending < (1 if self.supply_cap < 60 else 2) and self.can_afford(UnitTypeId.PYLON):
            near = self.townhalls.random.position.towards(self.game_info.map_center, 8) if self.townhalls else self.start_location
            await self.build(UnitTypeId.PYLON, near=near)

    async def _gas(self):
        if not self.structures(UnitTypeId.GATEWAY) and not self.structures(UnitTypeId.WARPGATE):
            return
        for th in self.townhalls.ready:
            if self.gas_buildings.closer_than(12, th).amount + self.already_pending(UnitTypeId.ASSIMILATOR) >= 2:
                continue
            if not self.can_afford(UnitTypeId.ASSIMILATOR):
                return
            for vg in self.vespene_geyser.closer_than(12, th):
                if self.gas_buildings.closer_than(1, vg):
                    continue
                worker = self.select_build_worker(vg.position)
                if worker:
                    worker.build_gas(vg)
                    return

    async def _chrono(self):
        for nexus in self.townhalls.ready:
            if nexus.energy < 50:
                continue
            targets = self.structures({UnitTypeId.CYBERNETICSCORE, UnitTypeId.FORGE, UnitTypeId.GATEWAY, UnitTypeId.ROBOTICSFACILITY, UnitTypeId.NEXUS}).ready
            busy = [s for s in targets if s.orders and not s.has_buff(BuffId.CHRONOBOOSTENERGYCOST)]
            if busy:
                nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, busy[0])
                return

    async def _first_buildings(self):
        """Opening the commander does not need to micromanage: gateway, core."""
        if not self.structures(UnitTypeId.PYLON).ready:
            return
        pylon = self.structures(UnitTypeId.PYLON).ready.random
        gates = self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount
        if gates == 0 and self.already_pending(UnitTypeId.GATEWAY) == 0 and self.can_afford(UnitTypeId.GATEWAY):
            await self.build(UnitTypeId.GATEWAY, near=pylon)
        elif gates and not self.structures(UnitTypeId.CYBERNETICSCORE) and self.already_pending(UnitTypeId.CYBERNETICSCORE) == 0 \
                and self.can_afford(UnitTypeId.CYBERNETICSCORE):
            await self.build(UnitTypeId.CYBERNETICSCORE, near=pylon)
        # minimum worker production so the economy never stalls completely
        if self.workers.amount < 16 * max(1, self.townhalls.ready.amount) and self.workers.amount < MAX_WORKERS:
            self._train_probe()

    def _train_probe(self):
        for nexus in self.townhalls.ready.idle:
            if self.can_afford(UnitTypeId.PROBE) and self.supply_left > 0:
                nexus.train(UnitTypeId.PROBE)
                return

    # ------------------------------------------------------------- commander-driven macro
    async def _macro(self, focus: str):
        if focus == "workers":
            if self.workers.amount < MAX_WORKERS:
                self._train_probe()
        elif focus == "expand":
            if self.townhalls.amount < MAX_BASES and self.already_pending(UnitTypeId.NEXUS) == 0 and self.can_afford(UnitTypeId.NEXUS):
                await self.expand_now()
        elif focus == "production":
            await self._more_production()
        elif focus == "tech":
            await self._tech()
        elif focus == "army":
            await self._train_army()
        # whatever the focus, do not sit on a huge bank
        if self.minerals > 600 or (self.vespene > 400 and self.minerals > 150):
            await self._train_army()
        if self.minerals > 900:
            await self._more_production()

    async def _more_production(self):
        if not self.structures(UnitTypeId.PYLON).ready:
            return
        pylon = self.structures(UnitTypeId.PYLON).ready.random
        gates = self.structures(UnitTypeId.GATEWAY).amount + self.structures(UnitTypeId.WARPGATE).amount + self.already_pending(UnitTypeId.GATEWAY)
        max_gates = GATEWAYS_PER_BASE * max(1, self.townhalls.amount)
        if gates < max_gates and self.can_afford(UnitTypeId.GATEWAY):
            await self.build(UnitTypeId.GATEWAY, near=pylon)
        elif self.structures(UnitTypeId.CYBERNETICSCORE).ready and self.structures(UnitTypeId.ROBOTICSFACILITY).amount + self.already_pending(UnitTypeId.ROBOTICSFACILITY) < 1 \
                and self.can_afford(UnitTypeId.ROBOTICSFACILITY):
            await self.build(UnitTypeId.ROBOTICSFACILITY, near=pylon)

    async def _tech(self):
        core = self.structures(UnitTypeId.CYBERNETICSCORE).ready
        if not core:
            return
        pylon = self.structures(UnitTypeId.PYLON).ready.random if self.structures(UnitTypeId.PYLON).ready else None
        if self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0 and self.can_afford(UpgradeId.WARPGATERESEARCH):
            core.first.research(UpgradeId.WARPGATERESEARCH)
            return
        if not self.structures(UnitTypeId.FORGE) and self.already_pending(UnitTypeId.FORGE) == 0 and self.can_afford(UnitTypeId.FORGE) and pylon:
            await self.build(UnitTypeId.FORGE, near=pylon)
            return
        forge = self.structures(UnitTypeId.FORGE).ready.idle
        if forge:
            for up in (UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1, UpgradeId.PROTOSSGROUNDARMORSLEVEL1):
                if self.already_pending_upgrade(up) == 0 and self.can_afford(up):
                    forge.first.research(up)
                    return
        if not self.structures(UnitTypeId.TWILIGHTCOUNCIL) and self.already_pending(UnitTypeId.TWILIGHTCOUNCIL) == 0 \
                and self.can_afford(UnitTypeId.TWILIGHTCOUNCIL) and pylon:
            await self.build(UnitTypeId.TWILIGHTCOUNCIL, near=pylon)
            return
        tc = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.idle
        if tc and self.already_pending_upgrade(UpgradeId.BLINKTECH) == 0 and self.can_afford(UpgradeId.BLINKTECH):
            tc.first.research(UpgradeId.BLINKTECH)
            return
        if self.structures(UnitTypeId.ROBOTICSFACILITY).amount + self.already_pending(UnitTypeId.ROBOTICSFACILITY) < 1 \
                and self.can_afford(UnitTypeId.ROBOTICSFACILITY) and pylon:
            await self.build(UnitTypeId.ROBOTICSFACILITY, near=pylon)

    async def _train_army(self):
        core_ready = bool(self.structures(UnitTypeId.CYBERNETICSCORE).ready)
        # robotics first: immortals are strong and simple
        for robo in self.structures(UnitTypeId.ROBOTICSFACILITY).ready.idle:
            if self.can_afford(UnitTypeId.IMMORTAL) and self.supply_left >= 4:
                robo.train(UnitTypeId.IMMORTAL)
        # gateways
        for gw in self.structures(UnitTypeId.GATEWAY).ready.idle:
            if core_ready and self.can_afford(UnitTypeId.STALKER) and self.supply_left >= 2:
                gw.train(UnitTypeId.STALKER)
            elif self.can_afford(UnitTypeId.ZEALOT) and self.supply_left >= 2 and (not core_ready or self.vespene < 50):
                gw.train(UnitTypeId.ZEALOT)
        # warpgates
        warpgates = self.structures(UnitTypeId.WARPGATE).ready
        if warpgates and self.structures(UnitTypeId.PYLON).ready:
            pylon = self.structures(UnitTypeId.PYLON).ready.closest_to(self.rally or self.start_location)
            for wg in warpgates:
                abilities = await self.get_available_abilities(wg)
                unit = None
                if AbilityId.WARPGATETRAIN_STALKER in abilities and self.can_afford(UnitTypeId.STALKER):
                    unit = UnitTypeId.STALKER
                elif AbilityId.WARPGATETRAIN_ZEALOT in abilities and self.can_afford(UnitTypeId.ZEALOT) and self.vespene < 50:
                    unit = UnitTypeId.ZEALOT
                if unit is None or self.supply_left < 2:
                    continue
                pos = pylon.position.to2.random_on_distance(4)
                placement = await self.find_placement(AbilityId.WARPGATETRAIN_STALKER, pos, placement_step=1)
                if placement:
                    wg.warp_in(unit, placement)

    # ------------------------------------------------------------- commander-driven army
    async def _army(self, stance: str, threat: float):
        army = self.units.filter(lambda u: u.type_id in ARMY_TYPES)
        if not army:
            return
        # base defence overrides everything when enemies are actually in the base
        intruders = None
        for th in self.townhalls:
            near = self.enemy_units.closer_than(28, th).filter(lambda u: u.can_attack or u.is_structure)
            if near:
                intruders = near
                break
        if intruders:
            target = intruders.closest_to(army.center)
            for u in army:
                u.attack(target.position)
            # pull probes only when a real force is inside
            if threat >= 2.5 and intruders.amount >= 6:
                for w in self.workers.closer_than(10, target.position):
                    w.attack(target.position)
            return

        if stance == "attack":
            target = self._attack_target()
            for u in army.idle:
                u.attack(target)
        elif stance == "pressure":
            for u in army:
                if u.distance_to(self.forward) > 8:
                    u.attack(self.forward)
        elif stance == "retreat":
            for u in army:
                if u.distance_to(self.rally) > 6:
                    u.move(self.rally)
        else:  # defend
            for u in army.idle:
                if u.distance_to(self.rally) > 6:
                    u.attack(self.rally)

    def _attack_target(self) -> Point2:
        if self.enemy_structures:
            return self.enemy_structures.closest_to(self.start_location).position
        if self.enemy_units:
            return self.enemy_units.closest_to(self.start_location).position
        return self.enemy_start_locations[0]

    # ------------------------------------------------------------- rule mode (no jev)
    async def _rule_commander(self):
        """Crude heuristics so the bot can be tested without spending jev calls."""
        if self.time - self._last_rule_tick < 6:      # game seconds
            return
        self._last_rule_tick = self.time
        d = self.commander.decision
        d.seq += 1
        army_supply = sum(self.calculate_supply_cost(u.type_id) for u in self.units.filter(lambda u: u.type_id in ARMY_TYPES))
        if self.workers.amount < 22 * self.townhalls.amount and self.workers.amount < MAX_WORKERS:
            d.macro_focus = "workers"
        elif self.townhalls.amount < 2 and self.time > 150:
            d.macro_focus = "expand"
        elif not self.structures(UnitTypeId.FORGE) and self.time > 240:
            d.macro_focus = "tech"
        elif self.minerals > 500:
            d.macro_focus = "production"
        else:
            d.macro_focus = "army"
        d.army_stance = "attack" if army_supply >= 40 else "defend"
        d.threat = 0.0
        d.confidence = {"macro_focus": 1.0, "army_stance": 1.0, "threat": 1.0}
        record = {
            "type": "decision", "seq": d.seq, "t": time.time(), "game_time": self.time, "latency_ms": 0,
            "model": "rule-mode", "usage": {"input_tokens": 0, "cost_usd": 0},
            "totals": {"calls": 0, "cost_usd": 0, "errors": 0},
            "decision": {"macro_focus": d.macro_focus, "army_stance": d.army_stance, "threat": d.threat,
                         "enemy_rushing": 0, "ahead": 0.5, "confidence": d.confidence, "fallback": [], "seq": d.seq},
            "answers": {}, "labels": {},
            "state": build_state(self, self._recent(), d.short()),
        }
        self.commander.record(record)
        await self.dashboard.broadcast(record)
