#!/usr/bin/env python3
"""
Build script for Aether Controller Windows executable.
Creates a self-contained .exe with embedded dashboard.
"""
import os
import sys
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
OUTPUT_NAME = "AetherController"


def collect_dashboard():
    """Copy dashboard files to a temp location for bundling."""
    dash_src = os.path.join(PROJECT_ROOT, "aether", "dashboard")
    dash_dst = os.path.join(PROJECT_ROOT, "dashboard_bundle")
    if os.path.exists(dash_dst):
        shutil.rmtree(dash_dst)
    shutil.copytree(dash_src, dash_dst)
    css_sst = os.path.join(PROJECT_ROOT, "aether", "dashboard", "css")
    css_dst = os.path.join(dash_dst, "css")
    if os.path.exists(css_dst):
        shutil.rmtree(css_dst)
    shutil.copytree(css_sst, css_dst)
    print(f"Dashboard files collected to {dash_dst}")
    return dash_dst


def main():
    print("\n=== Building Aether Controller Executable ===\n")

    dash_dst = collect_dashboard()

    exe_path = os.path.join(DIST_DIR, OUTPUT_NAME + ".exe")
    entry = os.path.join(PROJECT_ROOT, "aether", "controller", "app.py")

    # Build with --console so the server logs are visible
    cmd_args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", OUTPUT_NAME,
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--specpath", BUILD_DIR,
        "--clean",
        "--console",
        "--paths", PROJECT_ROOT,
        "--add-data", str(dash_dst) + ";dashboard",
        entry,
    ]

    print(f"Entry point: {entry}")
    print(f"Output:      {exe_path}")
    print(f"Command:     PyInstaller --onefile --console --name {OUTPUT_NAME} ...\n")

    try:
        proc = subprocess.Popen(
            cmd_args,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(line, end="")
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("PyInstaller build failed with code " + str(proc.returncode))
    except Exception as exc:
        print("Build error:", exc)
        raise

    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\nSUCCESS: {exe_path}")
        print(f"Size:    {size_mb:.1f} MB")
    else:
        print("\nBuild completed but exe not found at expected path.")

    if os.path.exists(dash_dst):
        shutil.rmtree(dash_dst)
        print(f"Cleaned up {dash_dst}")


if __name__ == "__main__":
    main()
