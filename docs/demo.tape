# Record from the repo root after `uv sync`: vhs docs/demo.tape
Output docs/demo.gif

Set Shell "zsh"
Set FontSize 13
Set Width 1200
Set Height 640
Set Theme "Dracula"
Set TypingSpeed 40ms

Hide
Type "rm -rf out/demo && clear"
Enter
Show

# Ingest, redact, triage, auto-approve and export the bundled synthetic traces
Type "uv run ttg demo --workdir out/demo"
Sleep 300ms
Enter
Sleep 12s

# One exported case, ready for llm-regression-detector
Type "clear && head -c 700 out/demo/golden.json"
Sleep 300ms
Enter
Sleep 5s
