"""
HullVanguard build orchestrator.

Run from the GUI/ folder:
    python build.py

Steps:
  1. Pre-flight: verify icon, model, python version, deps.
  2. Install PyInstaller into the current interpreter if missing.
  3. Clean prior build/ and dist/.
  4. Invoke PyInstaller against HullVanguard.spec → dist/HullVanguard/.
  5. Locate Inno Setup (iscc.exe). If present, build the installer.
  6. Print final artifact paths.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # ...\Coding\GUI
PROJECT = ROOT.parent                            # ...\Coding
SPEC = ROOT / "HullVanguard.spec"
ISS = ROOT / "installer.iss"
ICON = ROOT / "icon.ico"
MODEL_V2 = PROJECT / "AI" / "runs" / "barnacle_detect_v2" / "weights" / "best.pt"
MODEL_V1 = PROJECT / "AI" / "runs" / "barnacle_detect" / "weights" / "best.pt"
DIST = ROOT / "dist" / "HullVanguard"
BUILD = ROOT / "build"
INSTALLER_OUT = ROOT / "installer_output"


def banner(msg: str) -> None:
    bar = "─" * (len(msg) + 4)
    print(f"\n{bar}\n  {msg}\n{bar}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print(f"$ {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd or ROOT)
    if check and res.returncode != 0:
        sys.exit(f"✗ Command failed (exit {res.returncode}): {' '.join(cmd)}")
    return res.returncode


def preflight() -> None:
    banner("Pre-flight checks")

    print(f"  Python: {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 10):
        sys.exit("✗ Python 3.10+ required.")

    if not SPEC.is_file():
        sys.exit(f"✗ Missing spec: {SPEC}")
    if not ISS.is_file():
        print(f"  ! installer.iss missing — installer step will be skipped.")
    if not ICON.is_file():
        sys.exit(f"✗ Missing icon: {ICON}\n  Drop a multi-resolution icon.ico into GUI/.")
    print(f"  Icon:   {ICON.name}  ({ICON.stat().st_size:,} bytes)")

    model = MODEL_V2 if MODEL_V2.is_file() else MODEL_V1 if MODEL_V1.is_file() else None
    if model is None:
        print("  ! No best.pt found under AI/runs/. Installer will skip the AI model;")
        print("    users can still drop one in later under <install>/AI/runs/.../weights/.")
    else:
        print(f"  Model:  {model.relative_to(PROJECT)}  ({model.stat().st_size:,} bytes)")

    required = ["pygame", "serial", "PIL", "ultralytics", "torch"]
    missing = []
    for m in required:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if missing:
        sys.exit(f"✗ Missing runtime deps: {missing}\n  pip install pygame-ce pyserial pillow ultralytics")
    print(f"  Deps:   {', '.join(required)} ✓")


def ensure_pyinstaller() -> None:
    banner("PyInstaller")
    try:
        import PyInstaller  # noqa: F401
        from PyInstaller import __version__ as piv
        print(f"  PyInstaller {piv} already installed.")
    except ImportError:
        print("  Installing PyInstaller into current interpreter...")
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])


def clean() -> None:
    banner("Clean prior build")
    for d in (BUILD, ROOT / "dist", INSTALLER_OUT):
        if d.exists():
            print(f"  rm -rf {d}")
            shutil.rmtree(d, ignore_errors=True)


def build_exes() -> None:
    banner("PyInstaller build")
    t0 = time.time()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)])
    dt = time.time() - t0
    print(f"  Done in {dt:.1f}s")

    rel = DIST / "HullVanguard.exe"
    dbg = DIST / "HullVanguard-Debug.exe"
    if not rel.is_file():
        sys.exit(f"✗ Release exe missing: {rel}")
    if not dbg.is_file():
        sys.exit(f"✗ Debug exe missing: {dbg}")
    print(f"  Release: {rel}  ({rel.stat().st_size:,} bytes)")
    print(f"  Debug:   {dbg}  ({dbg.stat().st_size:,} bytes)")

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"  Bundle size: {total / 1_048_576:.0f} MB")


def find_iscc() -> str | None:
    candidates = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 5\ISCC.exe"),
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return cand
    return None


def build_installer() -> None:
    banner("Inno Setup installer")
    iscc = find_iscc()
    if iscc is None:
        print("  ! Inno Setup not found.")
        print("    Install from https://jrsoftware.org/isdl.php (free, ~6 MB),")
        print("    then re-run `python build.py`. Skipping installer step.")
        return
    print(f"  iscc: {iscc}")
    run([iscc, str(ISS)], cwd=ROOT)
    outs = sorted(INSTALLER_OUT.glob("*.exe"))
    if outs:
        print(f"  Installer: {outs[-1]}  ({outs[-1].stat().st_size:,} bytes)")
    else:
        print("  ! Installer compile finished but no .exe found in installer_output/.")


def main() -> None:
    preflight()
    ensure_pyinstaller()
    clean()
    build_exes()
    build_installer()
    banner("All done.")


if __name__ == "__main__":
    main()
