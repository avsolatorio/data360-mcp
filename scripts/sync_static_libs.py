#!/usr/bin/env python3
"""
Sync Vega static libraries from official npm packages into static/libs/.
"""
import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_LIBS_DIR = os.path.join(PROJECT_ROOT, "static", "libs")

MAPPINGS = [
    ("vega", "build/vega.min.js", "vega.js"),
    ("vega-lite", "build/vega-lite.min.js", "vega-lite.js"),
    ("vega-embed", "build/vega-embed.min.js", "vega-embed.js"),
    ("vega-interpreter", "build/vega-interpreter.min.js", "vega-interpreter.js"),
]


def sync_libs():
    os.makedirs(STATIC_LIBS_DIR, exist_ok=True)
    node_modules = os.path.join(PROJECT_ROOT, "node_modules")

    # If node_modules is missing or any package is missing, auto-run npm install
    missing_any = not os.path.exists(node_modules) or any(
        not os.path.exists(os.path.join(node_modules, pkg, src_rel))
        for pkg, src_rel, _ in MAPPINGS
    )

    if missing_any:
        print("Installing npm dependencies to fetch official Vega packages...")
        try:
            subprocess.run(["npm", "install"], cwd=PROJECT_ROOT, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Warning: Could not run npm install: {e}")

    copied = 0
    for pkg_name, src_rel, dest_filename in MAPPINGS:
        src_path = os.path.join(node_modules, pkg_name, src_rel)
        dest_path = os.path.join(STATIC_LIBS_DIR, dest_filename)

        if os.path.exists(src_path):
            shutil.copy2(src_path, dest_path)
            print(f"✓ Synced {pkg_name} ({src_rel}) -> static/libs/{dest_filename}")
            copied += 1
        else:
            print(f"⚠ Warning: Could not find {src_path}")

    if copied == len(MAPPINGS):
        print(f"\nDone. Synced {copied}/{len(MAPPINGS)} libraries to {STATIC_LIBS_DIR}")
    else:
        print(f"\nWarning: Only synced {copied}/{len(MAPPINGS)} libraries.")
        sys.exit(1)


if __name__ == "__main__":
    sync_libs()
