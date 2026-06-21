# VHS tape — the three ways to run agentforge-graph (the 0.5 setups).
# Regenerate:  scripts/render-setups-gif.sh    (it preps state, then runs vhs)
# Creds-free: single repo -> central store (host + read-only) -> workspace
# (cross-service call graph + trace). Renders docs/assets/setups.gif.
#
# State (central configs + a pre-built central index) is prepared by the wrapper
# script before this tape runs, so the hidden block here stays short.

Output docs/assets/setups.gif

Set Shell bash
Set FontSize 18
Set Width 1180
Set Height 760
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 38ms

Hide
Type `export PATH="$PWD/.venv/bin:$PATH"; export PS1="$ "` Enter
Type `cd examples/microservices && clear` Enter
Show

Sleep 800ms
# ── 1) a single repo ────────────────────────────────────────────────
Type "# 1) a single repo — a typed graph in seconds (no creds, no server)" Sleep 250ms Enter
Type "ckg index ../fastapi-shop" Sleep 250ms Enter
Sleep 2.6s
Type "ckg routes ../fastapi-shop" Sleep 250ms Enter
Sleep 2.6s
Type "clear" Enter

# ── 2) a central store ──────────────────────────────────────────────
Type "# 2) a central store — host the index outside the repo, consume read-only" Sleep 250ms Enter
Type "ckg status orders | grep store" Sleep 250ms Enter
Sleep 2.2s
Type "ckg index orders --read-only" Sleep 250ms Enter
Sleep 2.8s
Type "clear" Enter

# ── 3) a workspace ──────────────────────────────────────────────────
Type "# 3) a workspace — the cross-service call graph across services" Sleep 250ms Enter
Type "ckg services-map --workspace workspace.yaml" Sleep 250ms Enter
Sleep 3.2s
Type "# blast radius: who breaks if payments changes?" Sleep 250ms Enter
Type "ckg trace payments --workspace workspace.yaml --direction upstream" Sleep 250ms Enter
Sleep 3.6s
