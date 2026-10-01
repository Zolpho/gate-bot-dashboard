from __future__ import annotations


SPOT_GRID_CREATE_ACTION = "spot_grid_create"
INFINITE_GRID_CREATE_ACTION = "infinite_grid_create"
BOT_STOP_ACTION = "bot_stop"

CREATE_ACTIONS = frozenset({
    SPOT_GRID_CREATE_ACTION,
    INFINITE_GRID_CREATE_ACTION,
})

MUTATION_ACTIONS = frozenset({
    *CREATE_ACTIONS,
    BOT_STOP_ACTION,
})
