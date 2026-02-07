"""JSON-RPC 2.0 message framing over newline-delimited JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JsonRpcRequest:
    """JSON-RPC 2.0 request."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int | str = 0

    def to_dict(self) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
            "id": self.id,
        }


@dataclass(frozen=True)
class JsonRpcResponse:
    """JSON-RPC 2.0 response (success or error)."""

    id: int | str = 0
    result: Any = None
    error: dict | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_dict(self) -> dict:
        d: dict = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d


@dataclass(frozen=True)
class JsonRpcNotification:
    """JSON-RPC 2.0 notification (no id, no response expected)."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
        }


def encode(msg: JsonRpcRequest | JsonRpcResponse | JsonRpcNotification) -> bytes:
    """Encode a JSON-RPC message as a newline-delimited JSON bytes line."""
    return json.dumps(msg.to_dict(), default=str).encode() + b"\n"


def decode(line: bytes) -> JsonRpcRequest | JsonRpcResponse | JsonRpcNotification:
    """Decode a newline-delimited JSON line into a JSON-RPC message."""
    data = json.loads(line)

    if "method" in data:
        if "id" in data:
            return JsonRpcRequest(
                method=data["method"],
                params=data.get("params", {}),
                id=data["id"],
            )
        return JsonRpcNotification(
            method=data["method"],
            params=data.get("params", {}),
        )

    # Response
    return JsonRpcResponse(
        id=data.get("id", 0),
        result=data.get("result"),
        error=data.get("error"),
    )


def make_error(id: int | str, code: int, message: str) -> JsonRpcResponse:
    """Create a JSON-RPC error response."""
    return JsonRpcResponse(
        id=id,
        error={"code": code, "message": message},
    )


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
