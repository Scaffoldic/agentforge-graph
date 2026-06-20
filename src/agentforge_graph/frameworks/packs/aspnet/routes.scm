; ASP.NET controllers (ENH-012). Capture every class; the pack inspects its
; attributes ([ApiController]/[Route]) and each method's [HttpGet("/x")]/… in
; code, so a plain class never mints routes (ADR-0004).
(class_declaration
  name: (identifier) @class) @decl
