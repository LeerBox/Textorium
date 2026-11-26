"""Build the Windows executable dist/LeerBox_Text_Art_Studio_V3.exe with PyInstaller.

Builds from the standalone single-file script (all fonts and resources are embedded in it),
so the EXE is fully self-contained. Pillow (graphic preview, raster export, image decoding) and NumPy
(Image & Animation Studio) are bundled.

Usage:  pip install -r requirements-build.txt
        python tools/build_exe.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_python.py")], check=True)
    work = ROOT / "build"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", "LeerBox_Text_Art_Studio_V3", "--distpath", str(ROOT / "dist"), "--workpath", str(work),
           "--specpath", str(work), "--hidden-import", "PIL.ImageTk", "--hidden-import", "PIL.WebPImagePlugin",
           "--hidden-import", "numpy", "--hidden-import", "PIL.AvifImagePlugin", "--exclude-module", "onnxruntime", "--exclude-module", "av",
           str(ROOT / "LeerBox_Text_Art_Studio_V3.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = ROOT / "dist" / "LeerBox_Text_Art_Studio_V3.exe"
    print(f"built {exe} ({exe.stat().st_size:,} bytes)")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
