import json

from nvcontrol.backend.models import GpuInfo
from nvcontrol.capabilities import smoothmotion as SM
from nvcontrol.capabilities.driverhealth import Health, diagnose, parse_kernel_version
from nvcontrol.core.runner import Result

PROC = "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  580.95.05  Release Build  (builder@host)\n"


def test_parse_kernel_version():
    assert parse_kernel_version(PROC) == "580.95.05"
    assert parse_kernel_version("NVRM version: NVIDIA UNIX x86_64 Kernel Module  575.64  Tue") == "575.64"


def test_mismatch_after_update_without_reboot():
    # the friend's log: nvidia-smi exit 18, empty stderr, Vulkan can't find a GPU
    smi = Result(False, 18, "Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 590.44", "")
    h = diagnose(smi, PROC, "nvidia-utils 590.44.01-2\n", nouveau=False)
    assert h.state == Health.MISMATCH and h.can_reboot_fix
    assert h.kernel_version == "580.95.05" and h.userspace_version == "590.44.01"
    assert "restart" in h.title.lower()


def test_mismatch_detected_from_versions_even_if_message_differs():
    h = diagnose(Result(False, 18, "", ""), PROC, "nvidia-utils 590.44.01-1", nouveau=False)
    assert h.state == Health.MISMATCH


def test_healthy():
    h = diagnose(Result(True, 0, "GPU 0: NVIDIA GeForce RTX 4070", ""), PROC, "nvidia-utils 580.95.05-1",
                 nouveau=False)
    assert h.ok


def test_not_loaded_and_nouveau():
    assert diagnose(Result(False, 9, "NVIDIA-SMI has failed", ""), "", "nvidia-utils 580.95.05-1",
                    nouveau=False).state == Health.NOT_LOADED
    assert diagnose(Result(False, 9, "", ""), "", "", nouveau=True).state == Health.NOUVEAU


def test_layer_discovery(tmp_path):
    d = tmp_path / "implicit_layer.d"
    d.mkdir()
    (d / "nvidia_layers.json").write_text(json.dumps({"file_format_version": "1.0.1", "layers": [
        {"name": "VK_LAYER_NV_optimus", "library_path": "libGLX_nvidia.so.0"},
        {"name": "VK_LAYER_NV_present", "library_path": "libnvidia-present.so.580.95.05"}]}))
    layers = SM.find_layers([str(d)])
    assert len(layers) == 1 and layers[0].library.startswith("libnvidia-present")


def test_preflight_flags_each_problem():
    from nvcontrol.capabilities.driverhealth import DriverHealth
    ok = DriverHealth(Health.OK, "ok")
    gpu = GpuInfo(0, "NVIDIA GeForce RTX 4070", driver_version="580.95.05", arch="Ada Lovelace")
    layer = [SM.LayerInfo(tmp := __import__("pathlib").Path("/x.json"), "libnvidia-present.so.1")]
    assert all(c.ok is not False for c in SM.preflight(gpu, ok, True, layer))
    bad = SM.preflight(gpu, DriverHealth(Health.MISMATCH, "restart", fix=["Restart"]), False, [])
    assert [c.ok for c in bad[:4]] == [True, False, False, False]
    old = GpuInfo(0, "NVIDIA GeForce RTX 4070", driver_version="580.76.05", arch="Ada Lovelace")
    assert SM.preflight(old, ok, True, layer)[0].ok is False
    _ = tmp


def test_verdicts():
    mk = lambda **k: SM.RunningGame(1, "Game.exe", "1", **{**dict(env_on=True, layer_loaded=False, vulkan=True,  # noqa
                                                               wined3d=False, dxvk=True, is32=False), **k})
    assert SM.judge(mk(layer_loaded=True), (580,)).active
    g = SM.judge(mk(env_on=False), (580,))
    assert not g.active and "NOT enabled" in g.verdict
    g = SM.judge(mk(vulkan=False, wined3d=True, dxvk=False), (580,))
    assert any("WineD3D" in r for r in g.reasons)
    g = SM.judge(mk(is32=True), (580, 95))
    assert any("32-bit" in r for r in g.reasons)
    assert not any("32-bit" in r for r in SM.judge(mk(is32=True), (595, 1)).reasons)
    assert SM.judge(mk(layer_loaded=None), (580,)).active          # can't prove, but env+vulkan → likely


def test_verification_log(tmp_path):
    p = tmp_path / "1.log"
    assert not SM.read_log(p).exists
    p.write_text("[nvpresent] Smooth Motion enabled\n[nvpresent] frame 1\n")
    r = SM.read_log(p)
    assert r.loaded and r.lines == 2 and r.highlights


def test_profile_adds_verification_env():
    from nvcontrol.profiles.game_profile import GameProfile, build_launch_options
    p = GameProfile(appid="7", smooth_motion=True, sm_verify=True)
    o = build_launch_options(p, True, sm_log_path="/home/u/.local/state/nvcontrol/smoothmotion/7.log").options
    assert "NVPRESENT_LOG_LEVEL=4" in o and "NVPRESENT_LOG_FILE=/home/u/" in o
    assert "NVPRESENT_LOG" not in build_launch_options(p, False, sm_log_path="/x").options


def test_only_games_are_candidates():
    # global env var on a desktop service (the dbus-broker-launch bug) must be ignored
    assert not SM.is_candidate(None, env_on=True, layer_loaded=False, vulkan=False)
    assert not SM.is_candidate("0", env_on=True, layer_loaded=False, vulkan=True)
    assert not SM.is_candidate(None, env_on=True, layer_loaded=None, vulkan=True)   # random Vulkan app
    assert SM.is_candidate("1091500", env_on=True, layer_loaded=False, vulkan=True)  # Steam game
    assert SM.is_candidate(None, env_on=True, layer_loaded=True, vulkan=True)        # layer really running


def test_overlay_compat_and_active_tips():
    from nvcontrol.profiles.game_profile import GameProfile, build_launch_options
    o = build_launch_options(GameProfile(appid="570", smooth_motion=True, sm_overlay_compat=True), True).options
    assert "NVPRESENT_QUEUE_FAMILY=1" in o
    g = SM.judge(SM.RunningGame(1, "dota2", "570", True, True, True, False, False, False), (620,))
    assert g.active and any("BASE frame rate" in r for r in g.reasons)
