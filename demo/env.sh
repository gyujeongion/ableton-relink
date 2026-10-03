# sourced by demo.tape (hidden): prepares the demo project and a clean prompt
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$REPO/demo/setup_demo.py"
alias ableton-relink="python3 $REPO/ableton_relink.py"
export PS1='$ '
cd /tmp/relink-demo && clear
