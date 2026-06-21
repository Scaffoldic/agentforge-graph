; ENH-020 C-full: HTTP client instances — `s = requests.Session()`,
; `c = httpx.Client(base_url="http://orders")`. Pass-1 records the variable +
; its base_url so a later `s.get("/path")` resolves to base_url + path.
(assignment
  left: (identifier) @var
  right: (call
    function: (attribute
      object: (identifier) @mod
      attribute: (identifier) @ctor)
    arguments: (argument_list) @ctorargs))
