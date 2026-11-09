#!/usr/bin/env python3
"""Start the Pērkons Mod Matrix: set up everything it needs, then open it in your browser.

    python3 start_modmatrix.py          (macOS / Linux)
    py start_modmatrix.py               (Windows)

What it does, each time:
  1. checks Python (3.9 or newer)
  2. creates a private Python environment in .venv and installs this project's Python
     packages into it (first run only; nothing is installed system-wide)
  3. checks for the Arm GCC compiler (needed to build mods) and says how to install it
  4. starts the Mod Matrix at http://127.0.0.1:6464/ and opens it

The Mod Matrix gets the mods from their repos on GitHub (the list is in
kiteless/perkons-re-mods: repos.json), and downloads only the ones you build. To work on
mods from a folder on this computer instead, set PERKONS_MODS (or local.mk) to it.

Options are passed on to the Mod Matrix: --port N, --no-browser, --no-intro.
"""
import os
import platform
import shutil
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, '.venv')
WINDOWS = platform.system() == 'Windows'


def say(msg):
    print(f'[mod matrix] {msg}', flush=True)


def stop(msg):
    print(f'\n[mod matrix] {msg}\n', file=sys.stderr, flush=True)
    sys.exit(1)


def venv_python():
    return os.path.join(VENV, 'Scripts', 'python.exe') if WINDOWS else os.path.join(VENV, 'bin', 'python')


def setup_python():
    if sys.version_info < (3, 9):
        stop(f'Python 3.9 or newer is needed (this is {platform.python_version()}). '
             'Get it from https://www.python.org/downloads/')
    py = venv_python()
    if not os.path.exists(py):
        say('creating a private Python environment in .venv (first run only)')
        venv.create(VENV, with_pip=True)
    ok = subprocess.run([py, '-c', 'import capstone, unicorn'], capture_output=True).returncode == 0
    if not ok:
        say('installing the Python packages this project needs into .venv (first run only)')
        subprocess.run([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip'], check=True)
        subprocess.run([py, '-m', 'pip', 'install', '-q', '-r', os.path.join(ROOT, 'requirements.txt')], check=True)
    return py


def check_compiler():
    if shutil.which(os.environ.get('ARM_GCC_PREFIX', 'arm-none-eabi-') + 'gcc'):
        return
    system = platform.system()
    if system == 'Darwin':
        how = 'brew install arm-none-eabi-gcc arm-none-eabi-binutils   (Homebrew: https://brew.sh)'
    elif system == 'Linux':
        how = 'sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi   (Debian/Ubuntu; other distros have similar packages)'
    else:
        how = ('install the "arm-none-eabi" toolchain from '
               'https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads and tick '
               '"Add path to environment variable"; then open a new terminal')
    stop('The Arm GCC compiler (arm-none-eabi-gcc) is needed to build the mods. Install it with:\n\n'
         f'    {how}\n\nthen run this script again.')


def mods_dir():
    """Mods on this computer to offer instead of downloading them (a developer's clone):
    PERKONS_MODS, else local.mk's; None: the mods come from GitHub."""
    if os.environ.get('PERKONS_MODS'):
        return os.environ['PERKONS_MODS']
    local_mk = os.path.join(ROOT, 'local.mk')
    if os.path.exists(local_mk):
        with open(local_mk) as f:
            for line in f:
                key, _, value = line.partition('=')
                if key.strip() == 'PERKONS_MODS' and value.strip():
                    path = value.strip()
                    return path if os.path.isabs(path) else os.path.normpath(os.path.join(ROOT, path))
    return None


def main():
    py = setup_python()
    check_compiler()
    mods = mods_dir()
    say(f'mods on this computer: {mods}' if mods else 'mods: from their repos on GitHub')
    env = dict(os.environ, PERKONS_MODS=mods) if mods else dict(os.environ)
    say('starting; press Ctrl-C in this window to stop')
    try:
        return subprocess.call([py, os.path.join(ROOT, 'tools', 'modmatrix.py'), *sys.argv[1:]], env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
