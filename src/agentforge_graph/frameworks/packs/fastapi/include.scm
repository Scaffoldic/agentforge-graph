; FastAPI router mounts (ENH-011). Matches `app.include_router(x.router,
; prefix="/api")` — the cross-file compose-point. The method name
; (`include_router`) and the router ref / prefix are validated in code so a
; dynamic mount (non-literal router or prefix) is counted, not mis-resolved.
(call
  function: (attribute object: (identifier) @app attribute: (identifier) @method)
  arguments: (argument_list) @args) @mount
