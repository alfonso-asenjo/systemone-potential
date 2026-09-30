"""The commander's questions. One call, all questions evaluated in parallel.

Rule from the jev docs: ask judgments, not things code can compute. The code
already knows the numbers; jev is asked what to do with them.
"""
from __future__ import annotations

MACRO_FOCUS = {
    "workers": "Build more workers. Fewer than about 20 workers per base, no bank of resources, and the army is already adequate.",
    "expand": "Take a new base. Current bases are close to saturated, the army can hold the new base, and we have fewer than about 5 bases.",
    "production": "Add production buildings (gateways, robotics). Minerals or gas are piling up unspent, or there are too few production buildings for the number of bases.",
    "tech": "Invest in technology: tech buildings, upgrades and research. Economy and production are fine and we can afford a stronger army later.",
    "army": "Spend everything on army units right now. The army is small compared to the economy, or the enemy army is bigger than ours.",
}

ARMY_STANCE = {
    "defend": "Keep the army at home to protect the bases and workers. The enemy is threatening us or we are not strong enough to leave.",
    "pressure": "Move the army to a forward position near the middle of the map and contain the enemy without engaging into their defenses.",
    "attack": "Send the army to the enemy base and fight. We are clearly stronger, or supply is maxed and resources are piling up so the army must be traded, and there is no threat at home.",
    "retreat": "Pull the army back home immediately. The current fight or position is unfavorable.",
}

THREAT_LEVELS = [
    "No enemy activity near our bases.",
    "Enemy scouts or a handful of units near our bases.",
    "A meaningful enemy force is approaching our bases.",
    "Our base is under attack right now and losing units or buildings.",
]

COMMANDER_QUESTIONS = {
    "macro_focus": {
        "type": "choice",
        "instructions": "You command a Protoss army in a StarCraft II match. Given the game state, what should the economy and production focus be for the next ten seconds?",
        "criteria": MACRO_FOCUS,
    },
    "army_stance": {
        "type": "choice",
        "instructions": "What should the army do right now?",
        "criteria": ARMY_STANCE,
    },
    "threat": {
        "type": "score",
        "instructions": "How threatening is the current enemy activity to our bases?",
        "criteria": THREAT_LEVELS,
    },
    "enemy_rushing": {
        "type": "noul",
        "instructions": "Based on what has been scouted, the enemy is committing to an early rush or all-in attack.",
    },
    "ahead": {
        "type": "noul",
        "instructions": "We are ahead of the enemy in economy and army strength.",
    },
}

LABELS = {
    "macro_focus": "Macro focus",
    "army_stance": "Army stance",
    "threat": "Threat to base",
    "enemy_rushing": "Enemy rushing",
    "ahead": "We are ahead",
}
