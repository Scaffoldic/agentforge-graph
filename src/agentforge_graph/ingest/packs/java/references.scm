; Java reference queries (feat-002, pack-java).
; A method invocation's `name` is the called method, with or without a receiver
; (`f(...)`, `this.f(...)`, `obj.f(...)`). The second pattern captures the
; receiver (@call.recv) so `this.f()` binds to the enclosing class's method
; (BUG-006); other receivers stay unresolved (member access, ADR-0004).

(method_invocation
  name: (identifier) @call.callee) @call

(method_invocation
  object: (_) @call.recv
  name: (identifier) @call.callee) @call
