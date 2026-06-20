# VHS tape — the agentforge-graph README demo.
# Regenerate:  vhs docs/assets/demo.tape   (brew install vhs)
# Renders a creds-free walkthrough over examples/fastapi-shop:
# index -> routes -> models -> services (framework semantics as graph edges).

Output docs/assets/demo.gif

Set Shell bash
Set FontSize 18
Set Width 1180
Set Height 700
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 45ms

# --- setup (hidden): clean prompt, ckg on PATH, fresh index dir ---
Hide
Type `export PATH="$PWD/.venv/bin:$PATH"; export PS1="$ "` Enter
Type `rm -rf examples/fastapi-shop/.ckg` Enter
Type `cd examples/fastapi-shop && clear` Enter
Show

Sleep 600ms
Type "ckg index ." Sleep 400ms Enter
Sleep 2.8s

Type "ckg routes" Sleep 400ms Enter
Sleep 2.6s

Type "ckg models" Sleep 400ms Enter
Sleep 3.2s

Type "ckg services" Sleep 400ms Enter
Sleep 3.4s
