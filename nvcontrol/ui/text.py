"""Text casing helpers (sentence case for buttons outside Veneco Mode)."""
from __future__ import annotations

ACRONYMS = {"GPU", "GPUS", "LACT", "FPS", "DDC/CI", "DDC", "VRR", "HDR", "ICC", "KDE", "NVIDIA", "DLSS", "OK", "MHZ",
            "RTX", "VRAM", "NVML", "PCIE", "USB", "X11", "CPU", "GE-PROTON", "PROTONUP-QT", "NVIDIA'S", "IDE",
            "OPENGL", "GOVERLAY", "MANGOHUD", "NV//CONTROL", "VENECO", "STEAM", "PROTON", "KWIN", "LINUX",
            "WINDOWS", "DXVK", "NVAPI", "SR", "RR"}
PROPER = {"GOVERLAY": "GOverlay", "MANGOHUD": "MangoHud", "OPENGL": "OpenGL", "PROTONUP-QT": "ProtonUp-Qt",
          "GE-PROTON": "GE-Proton", "MHZ": "MHz", "PCIE": "PCIe", "GPUS": "GPUs", "STEAM": "Steam",
          "PROTON": "Proton", "KWIN": "KWin", "LINUX": "Linux", "WINDOWS": "Windows"}


def sentence_case(text: str) -> str:
    """'SAVE AS STARTUP PROFILE' → 'Save as startup profile' (acronyms kept)."""
    if not text or text != text.upper() or not any(c.isalpha() for c in text):
        return text
    out = []
    first = True
    for w in text.split(" "):
        core = w.strip("()·,:")
        if core in ACRONYMS:
            out.append(w.replace(core, PROPER.get(core, core)))
        elif any(ch.isdigit() for ch in w) and len(w) <= 4:
            out.append(w.lower())
        elif first and any(ch.isalpha() for ch in w):
            out.append(w[:1] + w[1:].lower())
        else:
            out.append(w.lower())
        if any(ch.isalpha() for ch in w):
            first = False
    return " ".join(out)
