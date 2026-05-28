"""Minimal MCP stdio server for ReverseFlightTickets tools."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, TextIO

from reverse_flight_tickets import __version__
from reverse_flight_tickets.config import AppConfig
from reverse_flight_tickets.domain import SearchRequest
from reverse_flight_tickets.providers import (
    ProviderContext,
    available_provider_metadata,
    providers_from_names,
)
from reverse_flight_tickets.pricing import build_currency_converter
from reverse_flight_tickets.search import SearchOrchestrator
from reverse_flight_tickets.search.filters import normalize_carrier_codes

DEFAULT_EXCLUDED_CARRIERS = ("ZZ",)
PROTOCOL_VERSION = "2025-06-18"


class JsonRpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def search_flights(arguments: dict[str, Any]) -> dict[str, object]:
    """Run a flight search and return the existing normalized result shape."""

    config = AppConfig.from_env()
    request = _search_request(arguments, config)
    try:
        providers = providers_from_names(
            _string_tuple(arguments.get("provider_names")),
            include_research=bool(arguments.get("include_research", False)),
        )
    except ValueError as exc:
        raise JsonRpcError(-32602, str(exc)) from exc

    context = ProviderContext(
        credentials=config.provider_secret_map(),
        timeout_seconds=config.provider_timeout_seconds,
    )
    orchestrator = SearchOrchestrator(
        providers,
        timeout_seconds=config.provider_timeout_seconds,
        excluded_carriers=_excluded_carriers(arguments),
        currency_converter=build_currency_converter(
            exchange_rates=config.exchange_rates,
            exchange_rate_source=config.exchange_rate_source,
            cache_path=config.exchange_rate_cache_path,
            cache_ttl_seconds=config.exchange_rate_cache_ttl_seconds,
            api_base_url=config.exchange_rate_api_base_url,
            timeout_seconds=config.exchange_rate_timeout_seconds,
        ),
        payment_fee_rate=config.payment_fee_rate,
        baggage_fee_amount=config.baggage_fee_amount,
    )
    result = await orchestrator.search(request, context)
    return result.to_dict()


def list_providers() -> dict[str, object]:
    return {"providers": list(available_provider_metadata())}


def handle_jsonrpc_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request or notification."""

    message_id = message.get("id")
    method = message.get("method")
    if message_id is None:
        return None
    try:
        if method == "initialize":
            result = _initialize_result()
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tool_definitions()}
        elif method == "tools/call":
            result = asyncio.run(_call_tool(message.get("params")))
        else:
            raise JsonRpcError(-32601, f"method not found: {method}")
        return {"jsonrpc": "2.0", "id": message_id, "result": result}
    except JsonRpcError as exc:
        return _error_response(message_id, exc.code, exc.message)
    except Exception as exc:
        return _error_response(message_id, -32603, str(exc))


def serve_stdio(
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """Serve MCP JSON-RPC messages over stdio.

    Supports the MCP Content-Length framing used by clients and the newline-delimited JSON
    form used by local smoke tests and shell debugging.
    """

    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    first_line = input_stream.readline()
    if not first_line:
        return
    if first_line.lower().startswith("content-length:"):
        _serve_content_length(first_line, input_stream, output_stream)
        return
    _handle_line(first_line, output_stream, framed=False)
    for line in input_stream:
        _handle_line(line, output_stream, framed=False)


async def _call_tool(params: object) -> dict[str, object]:
    if not isinstance(params, dict):
        raise JsonRpcError(-32602, "tools/call params must be an object")
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise JsonRpcError(-32602, "tool arguments must be an object")
    try:
        if name == "list_providers":
            payload = list_providers()
        elif name == "search_flights":
            payload = await search_flights(arguments)
        else:
            raise JsonRpcError(-32602, f"unknown tool: {name}")
    except JsonRpcError:
        raise
    except Exception as exc:
        payload = {"error": str(exc)}
        return _tool_result(payload, is_error=True)
    return _tool_result(payload, is_error=False)


def _initialize_result() -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "reverse-flight-tickets", "version": __version__},
    }


def _tool_result(payload: dict[str, object], *, is_error: bool) -> dict[str, object]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": is_error,
    }


def _tool_definitions() -> list[dict[str, object]]:
    return [
        {
            "name": "list_providers",
            "description": "List configured ReverseFlightTickets provider connectors and capabilities.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "search_flights",
            "description": (
                "Search normalized flight offers, manual verification links, recommendations, "
                "provider run status, and risk flags."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "departure_date": {"type": "string", "format": "date"},
                    "return_date": {"type": "string", "format": "date"},
                    "passenger_count": {"type": "integer", "minimum": 1},
                    "cabin": {
                        "type": "string",
                        "enum": ["economy", "premium_economy", "business", "first"],
                    },
                    "allowed_markets": {"type": "array", "items": {"type": "string"}},
                    "allowed_currencies": {"type": "array", "items": {"type": "string"}},
                    "stopovers": {"type": "array", "items": {"type": "string"}},
                    "date_flexibility_days": {"type": "integer", "minimum": 0},
                    "max_layover_hours": {"type": "integer", "minimum": 0},
                    "include_split_ticket": {"type": "boolean"},
                    "include_self_transfer": {"type": "boolean"},
                    "include_hidden_city": {"type": "boolean"},
                    "provider_names": {"type": "array", "items": {"type": "string"}},
                    "include_research": {"type": "boolean"},
                    "exclude_carriers": {"type": "array", "items": {"type": "string"}},
                    "include_test_carriers": {"type": "boolean"},
                },
                "required": ["origin", "destination", "departure_date"],
                "additionalProperties": False,
            },
        },
    ]


def _search_request(arguments: dict[str, Any], config: AppConfig) -> SearchRequest:
    data: dict[str, Any] = {
        "origin": arguments.get("origin"),
        "destination": arguments.get("destination"),
        "departure_date": arguments.get("departure_date"),
        "return_date": arguments.get("return_date"),
        "passenger_count": arguments.get("passenger_count", 1),
        "cabin": arguments.get("cabin", "economy"),
        "date_flexibility_days": arguments.get("date_flexibility_days", 0),
        "max_layover_hours": arguments.get("max_layover_hours"),
        "include_split_ticket": arguments.get("include_split_ticket", False),
        "include_self_transfer": arguments.get("include_self_transfer", False),
        "include_hidden_city": arguments.get("include_hidden_city", False),
    }
    if "allowed_markets" in arguments:
        data["allowed_markets"] = _string_tuple(arguments.get("allowed_markets"))
    if "allowed_currencies" in arguments:
        data["allowed_currencies"] = _string_tuple(arguments.get("allowed_currencies"))
    if "stopovers" in arguments:
        data["stopovers"] = _string_tuple(arguments.get("stopovers"))
    return SearchRequest.from_mapping(
        data,
        default_markets=config.default_markets,
        default_currencies=config.default_currencies,
    )


def _excluded_carriers(arguments: dict[str, Any]) -> tuple[str, ...]:
    carriers: tuple[str, ...] = (
        () if bool(arguments.get("include_test_carriers", False)) else DEFAULT_EXCLUDED_CARRIERS
    )
    return normalize_carrier_codes(carriers + _string_tuple(arguments.get("exclude_carriers")))


def _string_tuple(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _error_response(message_id: object, code: int, message: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _serve_content_length(
    first_header: str,
    input_stream: TextIO,
    output_stream: TextIO,
) -> None:
    next_header: str | None = first_header
    while next_header is not None:
        headers: dict[str, str] = {}
        line = next_header
        next_header = None
        while line.strip():
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()
            line = input_stream.readline()
            if not line:
                return
        length = _content_length(headers)
        if length is None:
            _write_response(
                output_stream,
                _error_response(None, -32600, "missing or invalid Content-Length"),
                framed=True,
            )
            return
        body = input_stream.read(length)
        if len(body) != length:
            _write_response(
                output_stream,
                _error_response(None, -32700, "incomplete message body"),
                framed=True,
            )
            return
        _handle_line(body, output_stream, framed=True)
        next_header = input_stream.readline()
        while next_header == "\r\n" or next_header == "\n":
            next_header = input_stream.readline()
        if not next_header:
            return


def _handle_line(line: str, output_stream: TextIO, *, framed: bool) -> None:
    if not line.strip():
        return
    try:
        message = json.loads(line)
        if not isinstance(message, dict):
            raise JsonRpcError(-32600, "invalid request")
        response = handle_jsonrpc_message(message)
    except json.JSONDecodeError as exc:
        response = _error_response(None, -32700, f"parse error: {exc.msg}")
    except JsonRpcError as exc:
        response = _error_response(None, exc.code, exc.message)
    if response is None:
        return
    _write_response(output_stream, response, framed=framed)


def _write_response(output_stream: TextIO, response: dict[str, object], *, framed: bool) -> None:
    payload = json.dumps(response, ensure_ascii=False)
    if framed:
        encoded_length = len(payload.encode("utf-8"))
        output_stream.write(f"Content-Length: {encoded_length}\r\n\r\n{payload}")
    else:
        output_stream.write(payload + "\n")
    output_stream.flush()


def _content_length(headers: dict[str, str]) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        length = int(raw)
    except ValueError:
        return None
    return length if length >= 0 else None


def main() -> None:
    serve_stdio()


if __name__ == "__main__":
    main()
