from __future__ import annotations

from range import fabric
from range.declared import Declaration

def home_net(declaration: Declaration) -> str:
    origins = [origin.subnet for origin in declaration.origins]
    inside = [fabric.INSIDE["estate"], fabric.INSIDE[fabric.MANAGEMENT]]
    return "[" + ",".join(origins + inside) + "]"
