import pytest

from nvcontrol.integrations import globalenv as G
from nvcontrol.ui.curve_editor import sanitize


def test_defaults_write_nothing():
    env, dx, notes = G.build(G.GlobalGraphics(), True, False)
    assert env == {} and dx == {} and notes == []


def test_nvidia_app_rows_map_to_linux_layers():
    g = G.GlobalGraphics(dlss_sr_preset="render_preset_k", dlss_sr_mode="custom", dlss_sr_ratio=75,
                         low_latency="on", vsync="off", max_fps=297, anisotropic="16x", threaded_optimization="on",
                         shader_cache="unlimited", triple_buffering="on", negative_lod="clamp")
    env, dx, _ = G.build(g, True, False)
    assert env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION"] == "render_preset_k"
    assert env["DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE"] == "custom"
    assert env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_SCALING_RATIO"] == "75"
    assert env["__GL_MaxFramesAllowed"] == "1" and dx["dxgi.maxFrameLatency"] == "1"
    assert env["__GL_SYNC_TO_VBLANK"] == "0" and dx["dxgi.syncInterval"] == "0"
    assert dx["dxgi.maxFrameRate"] == "297" and env["VKD3D_FRAME_RATE"] == "297"
    assert env["__GL_LOG_MAX_ANISO"] == "4" and dx["d3d11.samplerAnisotropy"] == "16"
    assert env["__GL_THREADED_OPTIMIZATIONS"] == "1"
    assert env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] == "1"
    assert dx["dxgi.numBackBuffers"] == "3" and dx["d3d11.clampNegativeLodBias"] == "True"
    assert env["DXVK_CONFIG_FILE"] == str(G.dxvk_path())


def test_gating_smooth_motion_and_mfg():
    g = G.GlobalGraphics(smooth_motion=True, dlss_mfg_count="4x")
    env, _, notes = G.build(g, smooth_motion_ok=False, mfg_ok=False)
    assert "NVPRESENT_ENABLE_SMOOTH_MOTION" not in env and "DXVK_NVAPI_DRS_NGX_DLSSG_MULTI_FRAME_COUNT" not in env
    assert len(notes) == 2
    env, _, notes = G.build(g, smooth_motion_ok=True, mfg_ok=True)
    assert env["NVPRESENT_ENABLE_SMOOTH_MOTION"] == "1"
    assert env["DXVK_NVAPI_DRS_NGX_DLSSG_MULTI_FRAME_COUNT"] == "3"
    assert any("EVERY Vulkan app" in n for n in notes)


def test_write_backup_and_reset():
    env, dx, _ = G.build(G.GlobalGraphics(vsync="on", max_fps=120), True, False)
    G.write(env, dx)
    assert "__GL_SYNC_TO_VBLANK=1" in G.env_path().read_text()
    assert "dxgi.maxFrameRate = 120" in G.dxvk_path().read_text()
    G.write(*G.build(G.GlobalGraphics(), True, False)[:2])      # nothing set → files removed
    assert not G.env_path().exists() and not G.dxvk_path().exists()


def test_unsafe_values_rejected():
    with pytest.raises(ValueError):
        G.render_env({"FOO": "a b; rm -rf ~"})
    env, _, notes = G.build(G.GlobalGraphics(extra_env={"BAD KEY": "1", "OK": "x y"}), True, False)
    assert env == {} and len(notes) == 2


def test_settings_roundtrip():
    g = G.GlobalGraphics(anisotropic="8x", max_fps=144)
    g.save()
    g2 = G.GlobalGraphics.load()
    assert g2.anisotropic == "8x" and g2.max_fps == 144


def test_curve_sanitize_matches_helper_rules():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "nvh2", Path(__file__).resolve().parents[1] / "nvcontrol" / "helper" / "nvcontrol_helper.py")
    H = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(H)
    messy = [[70, 40], [50, 60], [50, 20], [95, 80]]
    clean = sanitize(messy, fan_min=30)
    assert H.validate_curve(clean, fan_min=30) == clean        # whatever the editor produces, the helper accepts


def test_ultra_adds_auto_cap_from_refresh():
    assert G.ultra_cap(144) == 138 and G.ultra_cap(165) == 157 and G.ultra_cap(240) == 224
    env, dx, notes = G.build(G.GlobalGraphics(low_latency="ultra"), True, False, refresh_hz=164.96)
    assert dx["dxgi.maxFrameLatency"] == "1" and dx["dxgi.maxFrameRate"] == "157"
    assert env["VKD3D_FRAME_RATE"] == "157" and any("Ultra" in n for n in notes)
    on_env, on_dx, _ = G.build(G.GlobalGraphics(low_latency="on"), True, False, refresh_hz=165)
    assert "dxgi.maxFrameRate" not in on_dx                     # On ≠ Ultra anymore
    _, dx, _ = G.build(G.GlobalGraphics(low_latency="ultra", max_fps=120), True, False, refresh_hz=165)
    assert dx["dxgi.maxFrameRate"] == "120"                       # explicit cap wins
