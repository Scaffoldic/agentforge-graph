"""BedrockEmbedder: batching/parsing and client construction with boto3
mocked (CI, no creds), plus an env-gated live test against real Bedrock."""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

from agentforge_graph.embed import BedrockEmbedder


class _FakeBody:
    def __init__(self, data: dict) -> None:
        self._raw = json.dumps(data).encode()

    def read(self) -> bytes:
        return self._raw


async def test_batches_and_parses() -> None:
    e = BedrockEmbedder(dim=4, batch_size=2)
    calls = {"n": 0}

    class FakeClient:
        def invoke_model(self, **kw: object) -> dict:
            calls["n"] += 1
            body = json.loads(kw["body"])  # type: ignore[arg-type]
            n = len(body["texts"])
            return {"body": _FakeBody({"embeddings": {"float": [[0.1, 0.2, 0.3, 0.4]] * n}})}

    e._client = FakeClient()
    out = await e.embed(["a", "b", "c"], input_type="query")  # 3 texts / batch 2 -> 2 calls
    assert len(out) == 3
    assert all(len(v) == 4 for v in out)
    assert calls["n"] == 2


def test_client_default_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def client(name: str, **kw: object) -> str:
        seen["name"] = name
        return "CLIENT"

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    e = BedrockEmbedder(region="us-east-1")
    assert e._bedrock() == "CLIENT"
    assert seen["name"] == "bedrock-runtime"


def test_client_assume_role(monkeypatch: pytest.MonkeyPatch) -> None:
    def client(name: str, **kw: object) -> object:
        if name == "sts":
            return types.SimpleNamespace(
                assume_role=lambda **k: {
                    "Credentials": {
                        "AccessKeyId": "a",
                        "SecretAccessKey": "s",
                        "SessionToken": "t",
                    }
                }
            )
        return ("bedrock", kw)

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    e = BedrockEmbedder(assume_role_arn="arn:aws:iam::1:role/r")
    built = e._bedrock()
    assert built[0] == "bedrock"
    assert built[1]["aws_session_token"] == "t"


@pytest.mark.skipif(
    os.environ.get("CKG_LIVE_BEDROCK") != "1",
    reason="live Bedrock call; set CKG_LIVE_BEDROCK=1 with AWS creds",
)
async def test_live_cohere_embed() -> None:
    e = BedrockEmbedder(dim=1024)
    vecs = await e.embed(["def login(token): return validate(token)"], input_type="document")
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024
