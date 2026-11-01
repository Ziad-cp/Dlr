#!/bin/bash
# Dlr installer for macOS.
#
# Installs everything Dlr needs (Homebrew, Python 3.12, FFmpeg), builds the app on this Mac
# and puts Dlr in your Applications folder. Run it again any time to update Dlr.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Ziad-cp/Dlr/main/install.sh)"
#
# Or, from a copy of the source code:  ./install.sh
set -euo pipefail

REPO_TARBALL="https://github.com/Ziad-cp/Dlr/archive/refs/heads/main.tar.gz"

step() { printf '\n\033[1;35m==>\033[0m \033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "This installer is for macOS. On Windows, see README.md."

# 1. Homebrew (the standard Mac package manager), which provides Python and FFmpeg.
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && break
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  step "Installing Homebrew (it may ask for your Mac password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && break
  done
  command -v brew >/dev/null 2>&1 || fail "Homebrew didn't install. See https://brew.sh and try again."
fi

# 2. Python 3.12 (to build the app) and FFmpeg (combines picture and sound).
step "Installing Python 3.12 and FFmpeg"
brew install python@3.12 ffmpeg
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PYTHON" ] || fail "Python 3.12 wasn't found after installing it."

# 3. The source code: this folder if the script is run from it, otherwise a fresh download.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/app.py" ] && [ -f "$HERE/build.py" ]; then
  step "Using the source code in $HERE"
  SRC="$WORK/src"
  mkdir "$SRC"
  (cd "$HERE" && tar --exclude .venv --exclude .git --exclude build --exclude dist -cf - .) \
    | (cd "$SRC" && tar -xf -)
else
  step "Downloading Dlr"
  curl -fsSL "$REPO_TARBALL" | tar -xz -C "$WORK"
  SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ -f "$SRC/app.py" ] || fail "The download didn't contain Dlr's source code."
fi

# 4. Build Dlr.app in a temporary environment (nothing is installed into your system Python).
step "Building Dlr (this takes a few minutes)"
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --no-cache-dir --disable-pip-version-check -r "$SRC/requirements.txt"
(cd "$SRC" && "$WORK/venv/bin/python" build.py >/dev/null)
[ -d "$SRC/dist/Dlr.app" ] || fail "The build didn't produce Dlr.app."

# 5. Put it in Applications (replacing an older Dlr), or ~/Applications if that isn't writable.
DEST="/Applications"
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
step "Installing Dlr in $DEST"
osascript -e 'tell application "Dlr" to quit' >/dev/null 2>&1 || true
rm -rf "$DEST/Dlr.app"
cp -R "$SRC/dist/Dlr.app" "$DEST/"

printf '\n\033[1;32mDone!\033[0m Dlr is in %s. Opening it now...\n' "$DEST"
open "$DEST/Dlr.app"
