; Ruby reference queries (feat-002, pack-ruby).
; A call's `method:` field is the called name, whether or not it has a receiver
; (`foo(...)`, `obj.foo(...)`, `Mod::Klass.foo(...)`). Receiver-qualified calls
; are usually left unresolved (member access, ADR-0004).

(call
  method: (identifier) @call.callee) @call
