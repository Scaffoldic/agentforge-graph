; Rails routes (ENH-012). Capture the `…routes.draw do … end` block; the pack
; walks its body for explicit `get '/x' => 'c#a'` / `get '/x', to: 'c#a'` /
; `root 'c#a'` declarations. Scoping to the draw block avoids treating an
; unrelated `get`/`post` method call elsewhere as a route.
(call
  method: (identifier) @draw
  block: (do_block) @block) @drawcall
