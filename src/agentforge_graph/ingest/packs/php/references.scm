; PHP reference queries (feat-002, pack-php).
; Plain call `f(...)`, method call `$x->f(...)`, static call `C::f(...)`.
; Member/static calls are usually left unresolved (member access, ADR-0004).

(function_call_expression
  function: (name) @call.callee) @call

(member_call_expression
  name: (name) @call.callee) @call

(scoped_call_expression
  name: (name) @call.callee) @call
