"""UI labels. Veneco Mode swaps cosmetic labels only — warnings are never replaced."""
from __future__ import annotations

from . import theme

NORMAL = {
    "nav.command": "COMMAND CENTER",
    "nav.tuning": "GPU TUNING",
    "nav.lab": "GPU LAB",
    "nav.display": "DISPLAY",
    "nav.global": "GLOBAL GRAPHICS",
    "nav.rtx": "RTX / GAMING",
    "nav.profiles": "GAME PROFILES",
    "nav.performance": "PERFORMANCE",
    "nav.tools": "SYSTEM TOOLS",
    "nav.settings": "SETTINGS",
    "fan": "Fan Control",
    "power": "Power Limit",
    "temp": "Temperature",
    "perf": "Performance",
    "load": "GPU Load",
    "vram": "VRAM",
    "core": "Core Clock",
    "mem": "Memory Clock",
}

VENECO = {
    "nav.command": "CENTRO DE COMANDO DEL COÑO",
    "nav.tuning": "PON ESA VAINA A VOLAR",
    "nav.lab": "EL LABORATORIO DEL LOCO",
    "nav.display": "LA PANTALLITA",
    "nav.global": "CONFIGURACIÓN DE UNA",
    "nav.rtx": "RTX / JUEGUITO SERIO",
    "nav.profiles": "LOS JUEGUITOS",
    "nav.performance": "RENDIMIENTO ARRECHÍSIMO",
    "nav.tools": "HERRAMIENTAS DEL BECERRO",
    "nav.settings": "CONFIGURA TU VAINA",
    "fan": "VENTILADORES DEL DEMONIO",
    "power": "MÉTELE MÁS CANDELA",
    "temp": "QUÉ TAN CALIENTE ESTÁ ESTA VERGA",
    "perf": "RENDIMIENTO ARRECHÍSIMO",
    "load": "CARGA DE LA BICHA",
    "vram": "MEMORIA DE LA BICHA",
    "core": "RELOJ DEL NÚCLEO",
    "mem": "RELOJ DE MEMORIA",
}


def L(key: str) -> str:
    table = VENECO if theme.is_veneco() else NORMAL
    return table.get(key, NORMAL.get(key, key))
