"""MCP server of Rookie Agent (task 11.9; docs/mcp-codie-brief.md): Genie Codie (or MyGenie) calls the flows learned on this PC.

A thin layer over the local page http://127.0.0.1:8765 (it never imports Core). Standard library only. Two ways in:
- stdio (default): JSON-RPC 2.0, one message per line; Codie starts `python -m rookie_agent mcp`.
- HTTP (`--http PORT`, when Codie runs on another machine, the contest's VM): POST /mcp with `Authorization: Bearer <token>`, only from
  the addresses allowed (`--allow`), the token from ROOKIE_MCP_TOKEN. Off unless asked.

Rules that never bend: there is no tool to approve (Duyệt) a step: a write or money step waits for a person on the page; no value
typed or read goes out (names and states only); every call is one audit line (POST /api/mcp/audit); a run has a total time limit
(ROOKIE_MCP_RUN_TIMEOUT, 900 s) and is stopped when it is over; start_run needs an idempotency_key and the same key never runs twice.
"""
