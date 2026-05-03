# VHS tape for the README demo GIF.
# Run from repo root: `vhs images/pr-council.tape` -> images/pr-council.gif
# Drives images/demo.py (mock spinner, no API calls).

Output images/pr-council.gif

Set Shell bash
Set FontSize 16
Set Width 1000
Set Height 180
Set Padding 20
Set TypingSpeed 60ms
Set PlaybackSpeed 1.5

Hide
Type "export PS1='$ '"
Enter
Type "alias prc='uv run -q python images/demo.py'"
Enter
Type "uv run -q python -c '' >/dev/null 2>&1"
Enter
Type "clear"
Enter
Show

Sleep 500ms
Type "prc review"
Sleep 400ms
Enter
Sleep 7s
