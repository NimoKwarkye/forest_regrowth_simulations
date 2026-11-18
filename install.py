#!/usr/bin/env python3
"""Install cluster launchers without moving study files."""
import argparse
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def install(bin_dir, python=None):
    if sys.platform == 'win32':
        raise RuntimeError('Run this installer on the Linux cluster.')
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('uv must be installed and available on PATH.')
    interpreter = ROOT / '.venv/bin/python'
    bin_dir = bin_dir.expanduser().resolve()
    launcher = bin_dir / 'regrowth'
    marker = '# LPJ-GUESS launcher: ' + str(ROOT)
    if launcher.exists() or launcher.is_symlink():
        if launcher.is_symlink() or marker not in launcher.read_text():
            raise RuntimeError(f'Refusing to replace unrelated launcher: {launcher}')
    if not interpreter.exists():
        subprocess.run([uv, 'venv', '--python', python or sys.executable, str(ROOT / '.venv')], check=True)
    subprocess.run([uv, 'pip', 'install', '--python', str(interpreter), '-r', str(ROOT / 'requirements.txt')], check=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/bin/sh\n' + marker + '\nexec ' + shlex.quote(str(interpreter)) + ' ' + shlex.quote(str(ROOT / 'launcher.py')) + ' "$@"\n')
    launcher.chmod(0o755)
    print(f'Installed {launcher}\nAdd {bin_dir} to PATH.\nSet cluster.json python to: {interpreter}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=Path.home()/'.local/bin')
    parser.add_argument('--python', help='Interpreter for initial virtual environment creation')
    args = parser.parse_args()
    try:
        install(args.bin_dir, args.python)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Installation failed: {exc}\n')

if __name__ == '__main__':
    main()
