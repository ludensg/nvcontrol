# Maintainer: you
# Local PKGBUILD: builds NV//CONTROL from this source tree into a native pacman package.
#   makepkg -si        (install.sh does this for you)
pkgname=nvcontrol
pkgver=0.2.6
pkgrel=1
pkgdesc="NV//CONTROL — NVIDIA control center for CachyOS/Arch (telemetry, tuning, display, Steam/Proton profiles)"
arch=('any')
license=('MIT')
depends=('python' 'pyside6' 'python-nvidia-ml-py' 'polkit' 'nvidia-utils')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
checkdepends=('python-pytest')
optdepends=(
  'lact: fan curves, VF tuning, profiles (enable lactd)'
  'nvidia-settings: X11 color/vibrance/PowerMizer'
  'mangohud: performance overlay and FPS limiter'
  'lib32-mangohud: overlay for 32-bit games'
  'goverlay: MangoHud GUI'
  'gamescope: upscaling / resolution / HDR per game'
  'gamemode: CPU tweaks while gaming'
  'steam: game profiles'
  'vulkan-tools: Vulkan diagnostics'
  'kscreen: KDE display configuration'
  'ddcutil: real monitor brightness/contrast (DDC/CI)'
  'xorg-xrandr: X11 display modes'
)
backup=()
install=nvcontrol.install
source=()

build() {
  cd "$startdir"
  rm -rf dist build
  python -m build --wheel --no-isolation
}

check() {
  cd "$startdir"
  QT_QPA_PLATFORM=offscreen python -m pytest -q
}

package() {
  cd "$startdir"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm755 nvcontrol/helper/nvcontrol_helper.py "$pkgdir/usr/lib/nvcontrol/nvcontrol-helper"
  install -Dm644 data/polkit/org.nvcontrol.helper.policy "$pkgdir/usr/share/polkit-1/actions/org.nvcontrol.helper.policy"
  install -Dm644 data/systemd/nvcontrol-apply.service "$pkgdir/usr/lib/systemd/system/nvcontrol-apply.service"
  install -Dm644 data/systemd/nvcontrol-stable.service "$pkgdir/usr/lib/systemd/system/nvcontrol-stable.service"
  install -Dm644 data/systemd/nvcontrol-fancurve.service "$pkgdir/usr/lib/systemd/system/nvcontrol-fancurve.service"
  install -Dm644 data/systemd/nvcontrol-stable.timer "$pkgdir/usr/lib/systemd/system/nvcontrol-stable.timer"
  install -Dm644 data/nvcontrol.desktop "$pkgdir/usr/share/applications/nvcontrol.desktop"
  install -Dm644 data/icons/nvcontrol.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/nvcontrol.svg"
  install -Dm644 README.md "$pkgdir/usr/share/doc/nvcontrol/README.md"
  install -Dm644 docs/TROUBLESHOOTING.md "$pkgdir/usr/share/doc/nvcontrol/TROUBLESHOOTING.md"
  install -Dm644 docs/CAPABILITY_AUDIT.md "$pkgdir/usr/share/doc/nvcontrol/CAPABILITY_AUDIT.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/nvcontrol/LICENSE"
  install -dm755 "$pkgdir/etc/nvcontrol" "$pkgdir/var/lib/nvcontrol"
}
