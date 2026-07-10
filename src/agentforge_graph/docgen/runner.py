"""The Agent doc runner (feat-016) — where the multi-turn loop runs.

Builds an ``agentforge.Agent`` over the read-only ckg toolset, hands it the seed
task, and captures the run's provenance set from the tool observations. The Agent
is the repo's first non-test framework-Agent consumer; ``tests/serve/
test_live_agent.py`` is the live-wiring reference. For hermetic CI a scripted
``LLMClient`` is injected via ``model=`` (no creds, no network).

``agentforge.Agent`` and ``agentforge_core`` are imported lazily inside
:meth:`compose`, so importing :mod:`docgen` stays framework-free until a run
actually happens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import DocgenError
from .templates.base import SYSTEM_PROMPT, Template
from .toolset import capture_refs, grounded_tools
from .types import GroundedPack, ProvenanceSet

if TYPE_CHECKING:
    from agentforge_core.contracts.llm import LLMClient

    from agentforge_graph.config import ConfigSource, DocGenConfig


class AgentDocRunner:
    """Runs one grounded compose loop → ``(body, ProvenanceSet)``."""

    def __init__(
        self,
        cfg: DocGenConfig,
        *,
        repo_path: str,
        config: ConfigSource = None,
        model: str | LLMClient | None = None,
    ) -> None:
        self._cfg = cfg
        self._repo_path = repo_path
        self._config = config
        self._model = model  # None → resolve from cfg; str | LLMClient → use as-is

    def _resolve_model(self) -> str | LLMClient:
        if self._model is not None:
            return self._model
        if self._cfg.provider == "scripted":
            raise DocgenError(
                "docgen provider 'scripted' requires an injected model (test-only); "
                "set docgen.provider to a real provider for generation"
            )
        return self._cfg.model_ref()

    async def compose(self, pack: GroundedPack, template: Template) -> tuple[str, ProvenanceSet]:
        from agentforge import Agent
        from agentforge_core.production.exceptions import BudgetExceeded, GuardrailViolation

        tools = grounded_tools(self._repo_path, self._config)
        task = template.build_task(pack)

        try:
            async with Agent(
                model=self._resolve_model(),
                strategy="react",
                tools=tools,
                system_prompt=SYSTEM_PROMPT,
                budget_usd=self._cfg.budget_usd,
                max_iterations=self._cfg.max_iterations,
                install_log_filter=False,
            ) as agent:
                result = await agent.run(task)
        except (BudgetExceeded, GuardrailViolation) as exc:
            raise DocgenError(
                f"budget/iteration cap reached before the doc completed: {exc}"
            ) from exc

        body = result.output if isinstance(result.output, str) else str(result.output)

        # The tool boundary: capture every citable fact the tools returned, from
        # the run's step trace (fact-bearing ckg tools return JSON with id +
        # provenance; capture_refs applies the >= parsed floor).
        observations = [
            content
            for step in result.steps
            if isinstance(content := getattr(step, "content", None), str)
        ]
        captured = capture_refs(observations)
        seed_refs = {f.ref.id: f.ref for f in pack.facts}
        prov = ProvenanceSet.build(seed_refs, captured)
        return body, prov
