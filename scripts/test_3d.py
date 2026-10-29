"""Batch 2 step 0: can a three.js scene float over the desktop with NO background on this PC?

    python scripts/test_3d.py              # Esc closes
    python scripts/test_3d.py --seconds 8  # closes by itself

Shows a rotating, labelled heart made of spheres and tubes in a frameless, transparent,
always-on-top QWebEngineView. If you see a black (or white) box behind the heart, transparent
web views don't work with this graphics driver and the 3D board must use a glass panel instead.
"""
import argparse
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

WEB = Path(__file__).resolve().parent.parent / "zavero" / "web"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; background: transparent; overflow: hidden; }
  .label { position: absolute; transform: translate(-50%, -100%); padding: 4px 10px; border-radius: 12px;
           background: rgba(15, 23, 42, .85); color: #fff; font: 600 13px "Segoe UI", sans-serif;
           white-space: nowrap; pointer-events: none; }
</style></head><body>
<script src="three.min.js"></script>
<script>
const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(W, H);
renderer.setClearColor(0x000000, 0);           // fully transparent background
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 100);
camera.position.set(0, 0.3, 7);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.1); sun.position.set(3, 4, 5); scene.add(sun);

const heart = new THREE.Group(); scene.add(heart);
const mat = c => new THREE.MeshStandardMaterial({ color: c, roughness: .45, metalness: .05 });
const parts = [];
function ball(name, color, x, y, z, r) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 48, 32), mat(color));
  m.position.set(x, y, z); heart.add(m); parts.push([name, m, r]);
}
function tube(name, color, pts, r) {
  const curve = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
  const m = new THREE.Mesh(new THREE.TubeGeometry(curve, 64, r, 16, false), mat(color));
  heart.add(m); parts.push([name, m, r, curve.getPoint(1)]);
}
ball("Left ventricle", 0xc62828, 0.45, -0.55, 0, 0.85);
ball("Right ventricle", 0xe57373, -0.5, -0.45, 0.25, 0.75);
ball("Left atrium", 0xd84343, 0.55, 0.55, -0.2, 0.5);
ball("Right atrium", 0x7e57c2, -0.65, 0.5, 0.05, 0.5);
tube("Aorta", 0xb71c1c, [[0.2, 0.3, 0], [0.25, 1.4, 0], [-0.3, 1.9, 0], [-0.9, 1.4, 0], [-0.95, 0.6, -0.3]], 0.17);
tube("Vena cava", 0x1e66f5, [[-0.75, 0.8, 0.1], [-0.8, 1.9, 0.1]], 0.14);
tube("Pulmonary artery", 0x3b82f6, [[-0.1, 0.1, 0.4], [0.1, 1.1, 0.5], [0.9, 1.4, 0.4]], 0.13);

const labels = parts.map(([name]) => {
  const d = document.createElement("div"); d.className = "label"; d.textContent = name;
  document.body.appendChild(d); return d;
});
const v = new THREE.Vector3();
function tick(t) {
  heart.rotation.y = t / 2600;
  heart.rotation.x = Math.sin(t / 3100) * 0.15;
  renderer.render(scene, camera);
  parts.forEach(([name, m, r, tip], i) => {
    if (tip) v.copy(tip).applyMatrix4(heart.matrixWorld); else { m.getWorldPosition(v); v.y += r; }
    v.project(camera);
    labels[i].style.left = ((v.x + 1) / 2 * W) + "px";
    labels[i].style.top = ((1 - v.y) / 2 * H) + "px";
    labels[i].style.opacity = v.z < 1 ? 1 : 0;
  });
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0, help="close by itself after this many seconds")
    args = ap.parse_args()
    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    view.setStyleSheet("background: transparent")
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    view.setHtml(PAGE, QUrl.fromLocalFile(str(WEB) + "/"))
    screen = app.primaryScreen().availableGeometry()
    view.setGeometry(screen.center().x() - 300, screen.center().y() - 260, 600, 520)
    QShortcut(QKeySequence("Esc"), view, activated=app.quit)
    view.show()
    if args.seconds:
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
    print("3D test window is open. Esc closes it.", flush=True)
    app.exec()


if __name__ == "__main__":
    main()
