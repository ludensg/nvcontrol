import shlex

import pytest

from nvcontrol.integrations import mangohud, steam, vdf
from nvcontrol.profiles.game_profile import GameProfile, build_launch_options
from nvcontrol.profiles.store import ProfileStore


# ------------------------------------------------------------------ VDF
def test_vdf_roundtrip_preserves_unknown_keys():
    src = '''"Root"
{
    // comment
    "a"   "1"
    "nested" { "Key With Space" "va\\"lue" "x" "y" }
    "cond" "z" [$WIN32]
}'''
    d = vdf.loads(src)
    assert d["Root"]["nested"]["Key With Space"] == 'va"lue'
    again = vdf.loads(vdf.dumps(d))
    assert again == d


def test_vdf_errors():
    with pytest.raises(vdf.VdfError):
        vdf.loads('"a" { "b" "c"')


def test_get_ci():
    d = {"Software": {"Valve": {"Steam": {"Apps": {"1": {"x": "y"}}}}}}
    assert vdf.get_ci(d, "software", "valve", "steam", "apps", "1", "x") == "y"


# ------------------------------------------------------------------ Steam
@pytest.fixture
def fake_steam(tmp_path, monkeypatch):
    root = steam.create_mock_steam(tmp_path / "Steam")
    monkeypatch.setattr(steam, "steam_running", lambda root=None: False)
    return steam.Steam(root)


def test_discovery(fake_steam):
    names = [g.name for g in fake_steam.games()]
    assert "Cyberpunk 2077" in names and "Proton Experimental" not in names
    tools = {t.name for t in fake_steam.compat_tools()}
    assert {"proton_9", "proton_experimental", "GE-Proton10-25"} <= tools


def test_write_preserves_other_data_and_backs_up(fake_steam):
    before = vdf.loads(fake_steam.localconfig_path().read_text())
    bk = fake_steam.set_launch_options("1091500", "mangohud %command%")
    assert bk.exists()
    after = vdf.loads(fake_steam.localconfig_path().read_text())
    assert after["UserLocalConfigStore"]["friends"] == before["UserLocalConfigStore"]["friends"]
    apps = after["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
    assert apps["1245620"]["LaunchOptions"] == "PROTON_LOG=1 %command%"
    assert apps["1245620"]["LastPlayed"] == "1"
    assert fake_steam.get_launch_options("1091500") == "mangohud %command%"
    fake_steam.restore(bk, fake_steam.localconfig_path())
    assert fake_steam.get_launch_options("1091500") == ""


def test_refuses_when_steam_running(fake_steam, monkeypatch):
    monkeypatch.setattr(steam, "steam_running", lambda root=None: True)
    with pytest.raises(steam.SteamError, match="running"):
        fake_steam.set_launch_options("1091500", "%command%")


def test_rejects_bad_input(fake_steam):
    with pytest.raises(steam.SteamError):
        fake_steam.set_launch_options("12a", "%command%")
    with pytest.raises(steam.SteamError):
        fake_steam.set_launch_options("1091500", "a\nb")
    with pytest.raises(steam.SteamError):
        fake_steam.set_compat_tool("1091500", "bad name; rm")


def test_compat_tool_roundtrip(fake_steam):
    fake_steam.set_compat_tool("1091500", "GE-Proton10-25")
    assert fake_steam.get_compat_tool("1091500") == "GE-Proton10-25"
    fake_steam.set_compat_tool("1091500", None)
    assert fake_steam.get_compat_tool("1091500") is None


def test_official_proton_names():
    assert steam._official_internal_name("Proton 9.0 (Beta)") == "proton_9"
    assert steam._official_internal_name("Proton 6.3") == "proton_63"
    assert steam._official_internal_name("Proton 5.13") == "proton_513"
    assert steam._official_internal_name("Proton - Experimental") == "proton_experimental"


# ------------------------------------------------------------------ launch options
def test_smooth_motion_only_when_allowed():
    p = GameProfile(appid="1", smooth_motion=True)
    assert "NVPRESENT_ENABLE_SMOOTH_MOTION=1" in build_launch_options(p, True).options
    r = build_launch_options(p, False)
    assert "NVPRESENT" not in r.options and r.warnings


def test_smooth_motion_and_fg_warns():
    p = GameProfile(appid="1", smooth_motion=True, dlss_fg_override=True)
    assert any("compete" in w for w in build_launch_options(p, True).warnings)


def test_quoting_prevents_injection():
    p = GameProfile(appid="1", extra_env={"FOO": "a b; rm -rf ~"}, game_args='-x "$(reboot)"')
    opts = build_launch_options(p, False).options
    toks = shlex.split(opts)
    assert "FOO=a b; rm -rf ~" in toks
    assert "$(reboot)" in toks           # passed literally, single-quoted
    assert "'$(reboot)'" in opts


def test_invalid_env_key_ignored():
    p = GameProfile(appid="1", extra_env={"BAD KEY": "1", "OK_KEY": "2"})
    r = build_launch_options(p, False)
    assert "OK_KEY=2" in r.options and "BAD KEY" not in r.options


def test_gamescope_uses_mangoapp():
    p = GameProfile(appid="1", gamescope=True, mangohud=True, gs_width=2560, gs_height=1440, fps_limit=120)
    o = build_launch_options(p, False).options
    assert "--mangoapp" in o and " mangohud " not in o and "--framerate-limit 120" in o
    assert o.index("gamescope") < o.index(" -- ") < o.index("%command%")


def test_fps_limit_without_overlay_uses_hidden_mangohud():
    r = build_launch_options(GameProfile(appid="1", fps_limit=60), False, "/x/conf")
    assert "mangohud %command%" in r.options
    assert r.mangohud_changes["fps_limit"] == "60" and r.mangohud_changes["no_display"] is None


def test_empty_profile_is_empty_string():
    assert build_launch_options(GameProfile(appid="1"), True).options == ""


def test_profile_from_dict_sanitizes():
    p = GameProfile.from_dict({"appid": "5", "dlss_sr_preset": "evil", "fps_limit": -4, "junk": 1})
    assert p.dlss_sr_preset == "default" and p.fps_limit == 0


# ------------------------------------------------------------------ store / mangohud
def test_store_defaults_and_bundle(tmp_path):
    st = ProfileStore(tmp_path / "p")
    d = st.defaults()
    d.mangohud = True
    st.save_defaults(d)
    new = st.get("42", "Game")
    assert new.mangohud and new.appid == "42"
    st.save(new)
    out = tmp_path / "b.json"
    assert st.export_bundle(out) == 1
    st2 = ProfileStore(tmp_path / "q")
    assert st2.import_bundle(out) == 1 and st2.get("42").name == "Game"
    with pytest.raises(ValueError):
        st.get("../etc")


def test_mangohud_update_preserves_lines():
    txt = "# my comment\nfps\ncustom_thing=5\nfps_limit=30\n"
    out = mangohud.update(txt, {"fps_limit": "144", "gpu_temp": None, "fps": False})
    assert "# my comment" in out and "custom_thing=5" in out
    assert "fps_limit=144" in out and "gpu_temp" in out and "\nfps\n" not in "\n" + out
    with pytest.raises(ValueError):
        mangohud.update("", {"bad key": "1"})
    with pytest.raises(ValueError):
        mangohud.update("", {"ok": "x\ninjected=1"})
