"""Level registry: name -> class. Import side-effect free."""
from streetball.levels.base import Level
from streetball.levels.l0_stand import L0Stand
from streetball.levels.l1_traverse import L1Traverse, L1TraverseAMP
from streetball.levels.l2_dribble import L2Crossover, L2Dribble, L2DribbleCycles, L2DribbleLeft, L2DribblePush
from streetball.levels.l3_roam import L3MovingDribble, L3Scramble
from streetball.levels.l4_shot import L4JumpShot

LEVELS: dict[str, type[Level]] = {
    L0Stand.name: L0Stand,
    L1Traverse.name: L1Traverse,
    L1TraverseAMP.name: L1TraverseAMP,
    L2Dribble.name: L2Dribble,
    L2DribbleCycles.name: L2DribbleCycles,
    L2DribblePush.name: L2DribblePush,
    L2DribbleLeft.name: L2DribbleLeft,
    L2Crossover.name: L2Crossover,
    L3MovingDribble.name: L3MovingDribble,
    L3Scramble.name: L3Scramble,
    L4JumpShot.name: L4JumpShot,
}


def make(name: str) -> Level:
    try:
        return LEVELS[name]()
    except KeyError as e:
        raise KeyError(f"unknown level {name!r}; known: {sorted(LEVELS)}") from e
