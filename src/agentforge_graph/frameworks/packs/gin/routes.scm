; Gin routes (ENH-012). Matches `r.GET("/x", handler)` / `v.POST("/x", mw, h)` —
; a method call on a router/group whose field is an HTTP verb. The verb, the
; string-literal path and the handler are validated in code so non-route calls
; (`gin.Default()`, `r.Group(...)`, `r.Use(...)`) and dynamic paths are
; skipped/counted, never mis-extracted.
(call_expression
  function: (selector_expression
    operand: (_) @router
    field: (field_identifier) @method)
  arguments: (argument_list) @args) @call
