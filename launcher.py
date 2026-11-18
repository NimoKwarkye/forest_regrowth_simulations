#!/usr/bin/env python3
"""Convenience launcher for a Git checkout; preserves the caller's directory."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()

def update():
    import shutil
    if not shutil.which('uv'):
        raise RuntimeError('uv must be available on PATH before updating.')
    if Path(git('rev-parse', '--show-toplevel')).resolve() != ROOT:
        raise RuntimeError('The tool must be the root of its own Git checkout.')
    if git('status', '--porcelain'):
        raise RuntimeError('Checkout has local changes. Commit or move them before updating; nothing was overwritten.')
    git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    before = git('rev-parse', 'HEAD')
    subprocess.run(['git', '-C', str(ROOT), 'pull', '--ff-only'], check=True)
    subprocess.run(['uv', 'pip', 'install', '--python', sys.executable, '-r', str(ROOT/'requirements.txt')], check=True)
    print(f'Updated {before[:12]} -> {git("rev-parse", "HEAD")[:12]}')

def main():
    args = sys.argv[1:]
    try:
        if args == ['update']:
            update()
            return 0
        if args == ['version']:
            print(git('rev-parse', 'HEAD'))
            return 0
        if args and args[0] == 'prepare-sites':
            return subprocess.call([sys.executable, str(ROOT/'prepare_sites.py'), *args[1:]])
        if not args or args == ['--help']:
            print('Additional launcher commands: update, version, prepare-sites --study PATH', flush=True)
        return subprocess.call([sys.executable, str(ROOT/'regrowth.py'), *args])
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Launcher failed: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
