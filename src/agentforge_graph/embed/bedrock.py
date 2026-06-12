"""``BedrockEmbedder`` — AWS Bedrock Cohere embed-v4 via boto3.

boto3 is imported lazily (only this driver needs it; it lives in the
``bedrock`` extra). Synchronous Bedrock calls run on a worker thread.
Supports an optional STS assume-role (the CI path); otherwise the default
AWS credential chain (a developer's configured CLI). Voyage is *not* on
Bedrock — see memory `embeddings-bedrock`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import Embedder, InputType

_INPUT_MAP: dict[str, str] = {"document": "search_document", "query": "search_query"}


class BedrockEmbedder(Embedder):
    def __init__(
        self,
        model: str = "cohere.embed-v4:0",
        region: str = "us-east-1",
        dim: int = 1024,
        batch_size: int = 96,
        assume_role_arn: str | None = None,
    ) -> None:
        self.name = f"bedrock:{model}"
        self.model = model
        self.region = region
        self.dim = dim
        self.batch_size = batch_size
        self.assume_role_arn = assume_role_arn
        self._client: Any = None

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3

            if self.assume_role_arn:
                sts = boto3.client("sts", region_name=self.region)
                creds = sts.assume_role(RoleArn=self.assume_role_arn, RoleSessionName="ckg-embed")[
                    "Credentials"
                ]
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self.region,
                    aws_access_key_id=creds["AccessKeyId"],
                    aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"],
                )
            else:
                self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            out.extend(await asyncio.to_thread(self._invoke, batch, input_type))
        return out

    def _invoke(self, batch: list[str], input_type: InputType) -> list[list[float]]:
        body = json.dumps(
            {
                "texts": batch,
                "input_type": _INPUT_MAP[input_type],
                "embedding_types": ["float"],
                "output_dimension": self.dim,
            }
        )
        resp = self._bedrock().invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        payload = json.loads(resp["body"].read())
        embeddings = payload["embeddings"]
        floats = embeddings["float"] if isinstance(embeddings, dict) else embeddings
        return [[float(x) for x in vec] for vec in floats]
