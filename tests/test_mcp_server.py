import json
from io import StringIO

from reverse_flight_tickets.mcp_server import handle_jsonrpc_message, serve_stdio


def test_mcp_initialize_response() -> None:
    response = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )

    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "reverse-flight-tickets"
    assert response["result"]["capabilities"] == {"tools": {}}


def test_mcp_tools_list_includes_search() -> None:
    response = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )

    assert response is not None
    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"list_providers", "search_flights"}.issubset(tool_names)


def test_mcp_list_providers_tool_returns_content() -> None:
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_providers", "arguments": {}},
        }
    )

    assert response is not None
    text = response["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert any(provider["name"] == "skyscanner" for provider in payload["providers"])


def test_mcp_search_flights_tool_returns_manual_offer() -> None:
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_flights",
                "arguments": {
                    "origin": "PVG",
                    "destination": "LAX",
                    "departure_date": "2026-10-01",
                    "provider_names": ["skyscanner"],
                },
            },
        }
    )

    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["offers"][0]["provider"] == "skyscanner"
    assert payload["offers"][0]["manual_check_required"] is True


def test_mcp_stdio_serves_newline_delimited_jsonrpc() -> None:
    input_stream = StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}}) + "\n"
    )
    output_stream = StringIO()

    serve_stdio(input_stream=input_stream, output_stream=output_stream)

    response = json.loads(output_stream.getvalue())
    assert response == {"jsonrpc": "2.0", "id": 5, "result": {}}


def test_mcp_stdio_serves_content_length_framed_jsonrpc() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}})
    input_stream = StringIO(f"Content-Length: {len(body)}\r\n\r\n{body}")
    output_stream = StringIO()

    serve_stdio(input_stream=input_stream, output_stream=output_stream)

    raw_output = output_stream.getvalue()
    _, _, payload = raw_output.partition("\r\n\r\n")
    assert json.loads(payload) == {"jsonrpc": "2.0", "id": 6, "result": {}}
