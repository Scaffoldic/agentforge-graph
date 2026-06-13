; FastAPI route decorators (feat-011). Matches `@app.get("/x")` /
; `@router.post(...)` on a function. The method/path are validated in code
; (HTTP verb + a string-literal path) so non-route or dynamic-path decorators
; can be counted as unresolved rather than silently missed.
(decorated_definition
  (decorator
    (call
      function: (attribute object: (identifier) @app attribute: (identifier) @method)
      arguments: (argument_list) @args))
  definition: (function_definition name: (identifier) @handler)) @route
