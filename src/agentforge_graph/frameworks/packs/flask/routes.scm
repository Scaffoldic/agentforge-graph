; Flask route decorators (feat-011). Matches `@app.route("/x", methods=[...])`,
; blueprint `@bp.route(...)`, and the Flask 2.0 shortcuts `@app.get("/x")` etc.
; on a function. The decorator attribute (route/get/post/…) and the path/methods
; are validated in code so non-route decorators (`@app.before_request`) and
; dynamic paths are handled, not silently missed.
(decorated_definition
  (decorator
    (call
      function: (attribute object: (_) @app attribute: (identifier) @method)
      arguments: (argument_list) @args))
  definition: (function_definition name: (identifier) @handler)) @route
