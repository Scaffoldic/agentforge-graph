; ENH-020 C-full: outbound HTTP client calls — requests.get("…") / httpx.post("…").
; Conservative: module-qualified calls only (object is a bare identifier), so a
; client-instance `.get(...)` on an arbitrary variable is not mistaken for one.
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  arguments: (argument_list) @args) @call
