; Java reference queries (feat-002, pack-java).
; A method invocation's `name` is the called method, with or without a receiver
; (`f(...)`, `this.f(...)`, `obj.f(...)`). Receiver calls are usually left
; unresolved (member access, ADR-0004).

(method_invocation
  name: (identifier) @call.callee) @call
