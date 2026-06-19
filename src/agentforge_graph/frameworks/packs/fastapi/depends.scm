; FastAPI dependency injection (feat-011). Capture every function so the pack
; can inspect its parameters for `= Depends(provider)` / `= Security(provider)`
; defaults in code (both `default_parameter` and `typed_default_parameter`
; carry the call in their `value` field).
(function_definition
  name: (identifier) @func) @fn
