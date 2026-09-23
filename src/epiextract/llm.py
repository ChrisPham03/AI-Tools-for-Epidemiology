"""LLM access behind a small interface.

`LLMClient.extract(system, prompt, schema)` returns an instance of `schema`.
`BedrockClient` uses Amazon Bedrock's Converse API with a forced tool call, so the
model must answer in the schema's JSON shape. `CachedLLM` saves every response to
disk and replays it, so demos and tests run without cloud credentials.
Production target: an AzureOpenAIClient implementing the same interface.
"""
from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    model_id: str = "unknown"

    @abstractmethod
    def extract(self, system: str, prompt: str, schema: Type[T]) -> T: ...


def inline_refs(schema: dict) -> dict:
    """Pydantic puts nested models under $defs; inline them for tool schemas."""
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


class BedrockClient(LLMClient):
    TOOL = "record_answer"

    def __init__(self, model_id: str | None = None, region: str | None = None, max_retries: int = 1):
        import boto3  # imported here so replay mode works without AWS setup

        self.model_id = model_id or os.environ["BEDROCK_MODEL_ID"]
        self.client = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        self.max_retries = max_retries

    def extract(self, system: str, prompt: str, schema: Type[T]) -> T:
        tool = {
            "toolSpec": {
                "name": self.TOOL,
                "description": "Record the answer in the required structure.",
                "inputSchema": {"json": inline_refs(schema.model_json_schema())},
            }
        }
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        for attempt in range(self.max_retries + 1):
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=messages,
                inferenceConfig={"temperature": 0, "maxTokens": 4096},
                toolConfig={"tools": [tool], "toolChoice": {"tool": {"name": self.TOOL}}},
            )
            content = response["output"]["message"]["content"]
            tool_use = next(c["toolUse"] for c in content if "toolUse" in c)
            try:
                return schema.model_validate(tool_use["input"])
            except ValidationError as err:
                if attempt == self.max_retries:
                    raise
                # one retry: show the model exactly what was wrong with its output
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": [{
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"text": f"Invalid output, fix and resend:\n{err}"}],
                            "status": "error",
                        }
                    }]},
                ]


class CachedLLM(LLMClient):
    """Replays saved responses; calls the live client only on a cache miss."""

    def __init__(self, cache_dir: str | Path, live: LLMClient | None = None, model_id: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.live = live
        self.model_id = live.model_id if live else (model_id or os.environ.get("BEDROCK_MODEL_ID", "unknown"))

    def _key(self, system: str, prompt: str, schema: Type[BaseModel]) -> Path:
        raw = json.dumps([self.model_id, system, prompt, schema.model_json_schema()], sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(raw.encode()).hexdigest()[:16]}.json"

    def extract(self, system: str, prompt: str, schema: Type[T]) -> T:
        path = self._key(system, prompt, schema)
        if path.exists():
            return schema.model_validate_json(path.read_text())
        if self.live is None:
            raise RuntimeError(
                "No saved response for this question and no LLM credentials configured. "
                "Set BEDROCK_MODEL_ID and AWS credentials in .env to run live."
            )
        result = self.live.extract(system, prompt, schema)
        path.write_text(result.model_dump_json(indent=2))
        return result


def default_client(cache_dir: str | Path = "cache/llm") -> LLMClient:
    live = BedrockClient() if os.environ.get("BEDROCK_MODEL_ID") else None
    return CachedLLM(cache_dir, live=live)
