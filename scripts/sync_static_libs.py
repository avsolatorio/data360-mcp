#!/usr/bin/env python3
"""
Sync Vega static libraries from official npm packages into static/libs/.
"""
import os
import shutil
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

    if not os.path.exists(node_modules):
        print(f"Error: node_modules directory not found at {node_modules}.")
        print("Please run 'npm install' first.")
        sys.exit(1)

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

    print(f"\nDone. Synced {copied}/{len(MAPPINGS)} libraries to {STATIC_LIBS_DIR}")


if __name__ == "__main__":
    sync_libs()
