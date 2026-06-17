; Ruby reference queries (feat-002, pack-ruby).
; A call's `method:` field is the called name, whether or not it has a receiver
; (`foo(...)`, `obj.foo(...)`, `Mod::Klass.foo(...)`). The second pattern captures
; the receiver (@call.recv) so `self.foo()` binds to the enclosing class's method
; (BUG-006); other receivers stay unresolved (member access, ADR-0004).

(call
  method: (identifier) @call.callee) @call

(call
  receiver: (_) @call.recv
  method: (identifier) @call.callee) @call
