from django.conf import settings

import topology
from api import customers

def _customers_prefer(wargame: str) -> tuple[str, ...]:
    try:
        weights = customers.declared(wargame)["origins"]
    except customers.NoTraffic:
        return ()
    declared = settings.RANGE
    subnets = {origin.id: origin.subnet for origin in declared.origins if origin.id != declared.default_origin}
    return tuple(subnets[origin] for origin in sorted(weights, key=lambda origin: (-weights[origin], origin))
                 if origin in subnets and weights[origin] > 0)

def learner(wargame: str) -> topology.Learner:
    declared = settings.RANGE
    return topology.learner(declared, wargame, declared.roles["attacker"], _customers_prefer(wargame))
