; Laravel routes (ENH-012). Matches `Route::get('/x', ...)` static-DSL calls.
; The verb, path and handler reference are validated/extracted in code so a
; closure handler or dynamic path is handled conservatively.
(scoped_call_expression
  scope: (name) @facade
  name: (name) @method
  arguments: (arguments) @args) @call
