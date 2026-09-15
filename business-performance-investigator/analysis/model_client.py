"""Offline Chat Completions boundary replay; never constructs a network client."""

import copy
import json


class ReplayClient:
    """Scripted tool decisions, not simulated model intelligence or token usage."""

    execution_kind = "replay"

    def __init__(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
            raise ValueError("Replay needs one to fifty steps.")
        self._steps = copy.deepcopy(steps)
        self._position = 0

    def create(self, **kwargs):
        if self._position >= len(self._steps):
            raise ValueError("Replay exhausted; no implicit finish or retry.")
        step = self._steps[self._position]
        self._position += 1
        if not isinstance(step, dict) or set(step) != {"name", "arguments"}:
            raise ValueError("Replay steps require exactly name and arguments.")
        return {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": f"replay_{self._position}", "type": "function",
                        "function": {
                            "name": step["name"],
                            "arguments": json.dumps(step["arguments"], allow_nan=False),
                        },
                    }],
                },
            }],
            "usage": None,
        }
