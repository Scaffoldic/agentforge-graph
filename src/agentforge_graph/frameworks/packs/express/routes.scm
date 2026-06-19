; Express route registrations (feat-011): `app.get('/x', handler)` /
; `router.post('/x', mw, handler)`. The method (get/post/…) and a string path
; are validated in code so non-route calls (`app.use`, `app.listen`) and dynamic
; paths are handled, not silently missed. Shared verbatim by the JS and TS
; grammars (same node types).
(call_expression
  function: (member_expression object: (_) @obj property: (property_identifier) @method)
  arguments: (arguments) @args) @call
