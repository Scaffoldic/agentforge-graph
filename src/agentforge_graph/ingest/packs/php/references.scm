; PHP reference queries (feat-002, pack-php).
; Plain call `f(...)`, method call `$x->f(...)`, static call `C::f(...)`. The
; receiver is captured (@call.recv) so `$this->f()` / `self::f()` bind to the
; enclosing class's method (BUG-006); other receivers stay unresolved (ADR-0004).

(function_call_expression
  function: (name) @call.callee) @call

(member_call_expression
  object: (_) @call.recv
  name: (name) @call.callee) @call

(scoped_call_expression
  scope: (_) @call.recv
  name: (name) @call.callee) @call
