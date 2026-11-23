"""Plain-text diagnostic report (also used by `nvcontrol --diagnostics`)."""
from __future__ import annotations

import time
from dataclasses import asdict

from .. import __version__


def build_report(ctx) -> str:
    s, g = ctx.sysinfo, ctx.gpu
    lines = [f"NV//CONTROL {__version__} diagnostic report — {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines.append("[system]")
    for k in ("distro", "kernel", "desktop", "session", "plasma_version", "vulkan_ok", "vulkan_device",
              "vulkan_api", "nvidia_icd", "nvidia_drm_modeset", "nvidia_drm_fbdev", "helper_installed",
              "pkexec", "lactd_active"):
        lines.append(f"  {k:22} {getattr(s, k)}")
    lines.append(f"  {'backend':22} {ctx.backend.name} — {ctx.backend.source}")
    lines.append("")
    h = getattr(ctx, "health", None)
    if h:
        lines.append("[driver health]")
        lines.append(f"  {'state':22} {h.state.value}")
        lines.append(f"  {'summary':22} {h.title}")
        lines.append(f"  {'kernel module':22} {h.kernel_version}")
        lines.append(f"  {'installed (userspace)':22} {h.userspace_version}")
        lines.append(f"  {'nvidia-smi says':22} {h.smi_message[:300]}")
        lines.append("")
    lines.append("[gpu]")
    if g:
        for k, v in asdict(g).items():
            lines.append(f"  {k:22} {v}")
        t = ctx.backend.telemetry(g.index)
        lines.append("")
        lines.append("[telemetry]")
        for k, v in asdict(t).items():
            lines.append(f"  {k:22} {v}")
        c = ctx.caps
        lines.append("")
        lines.append("[tuning capabilities]")
        lines.append(f"  power                  {c.power}")
        lines.append(f"  gpc_offset             {c.gpc_offset}")
        lines.append(f"  mem_offset             {c.mem_offset}")
        lines.append(f"  fans                   {c.fan_count} ({c.fan_min_pct}-{c.fan_max_pct}%)")
        lines.append(f"  clock lock             {c.supports_clock_lock}")
    else:
        lines.append("  no NVIDIA GPU detected")
    lines.append("")
    lines.append("[displays]")
    for d in s.displays:
        lines.append(f"  {d.name}: {d.current_mode.label if d.current_mode else '?'} scale={d.scale} "
                     f"vrr={d.vrr_policy} hdr={d.hdr} icc={d.icc_profile}")
    lines.append("")
    lines.append("[tools]")
    for tid, st in s.tools.items():
        lines.append(f"  {tid:18} {'installed' if st.installed else 'missing':10} {st.path or ''}")
    lines.append("")
    lines.append("[feature matrix]")
    for f in ctx.features:
        lines.append(f"  {f.status.value:20} {f.name:45} {f.mechanism}")
        if f.detail:
            lines.append(f"  {'':20} ↳ {f.detail}")
    return "\n".join(lines) + "\n"
