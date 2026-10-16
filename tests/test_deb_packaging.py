"""Safe, isolated Debian package tests. Never install or remove system files."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "packaging/deb/build.py"


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not available on this system")
class DebianPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="solo-deb-test-")
        directory = Path(cls.temp.name)
        spec = importlib.util.spec_from_file_location("solo_deb_builder", BUILDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.deb = module.build(ROOT, directory / "dist")
        cls.extract = directory / "unpacked"
        subprocess.run(["dpkg-deb", "-x", str(cls.deb), str(cls.extract)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_deb_control_and_architecture(self):
        output = subprocess.check_output(["dpkg-deb", "-f", str(self.deb)], text=True)
        self.assertIn("Package: solo-agent", output)
        self.assertIn("Architecture: all", output)
        self.assertIn("gir1.2-webkit2-4.1", output)
        self.assertIn("Version: 1.0.1", output)

    def test_desktop_points_to_fixed_system_entrypoint(self):
        desktop = (self.extract / "usr/share/applications/solo-agent.desktop").read_text()
        wrapper = self.extract / "usr/bin/solo-agent"
        self.assertIn("Exec=/usr/bin/solo-agent", desktop)
        self.assertIn("Icon=solo-agent", desktop)
        self.assertIn("/usr/share/solo-agent/solo_app.py", wrapper.read_text())
        self.assertTrue(wrapper.stat().st_mode & 0o111)

    def test_core_app_and_all_original_icons_present(self):
        self.assertTrue((self.extract / "usr/share/solo-agent/ui/index.html").is_file())
        self.assertTrue((self.extract / "usr/share/solo-agent/solo_desktop.py").is_file())
        for size in (16,22,24,32,48,64,128,256,512):
            self.assertEqual((self.extract / "usr/share/icons/hicolor/{}x{}/apps/solo-agent.png".format(size,size)).read_bytes(), (ROOT / "share/icons/solo-{}.png".format(size)).read_bytes())

    def test_never_package_config_credentials_or_user_service(self):
        all_paths = [p.relative_to(self.extract).as_posix() for p in self.extract.rglob("*") if p.is_file()]
        self.assertFalse(any(".config/" in p or ".env" in p or "/systemd/" in p or "/.git/" in p for p in all_paths))
        self.assertFalse(any("/tests/" in p or "__pycache__" in p for p in all_paths))
        self.assertFalse(any("DEBIAN/" in p for p in all_paths))

    def test_no_installer_scripts_or_root_actions(self):
        data = subprocess.check_output(["dpkg-deb", "--ctrl-tarfile", str(self.deb)])
        import io,tarfile
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = {n.name.removeprefix("./") for n in tar.getmembers() if n.isfile()}
        self.assertEqual(names, {"control"})


if __name__ == "__main__":
    unittest.main()
