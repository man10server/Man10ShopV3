from __future__ import annotations

from typing import TYPE_CHECKING

from Man10Socket.utils.connection_handler.ConnectionFunction import ConnectionFunction

if TYPE_CHECKING:
    from Man10Socket.utils.connection_handler.Connection import Connection


class HeartbeatFunction(ConnectionFunction):

    CAPABILITY = "__man10shopv3_heartbeat_v1__"
    ACTIVE_CAPABILITY_PREFIX = "__man10shopv3_heartbeat_v1_active__:"
    ACTIVE_CAPABILITY_REPEATS = 3

    def __init__(self):
        super().__init__()
        self._acknowledged_generation: str | None = None
        self._active_capability_sent = 0

    def information(self):
        self.name = "Heartbeat Function"
        self.function_type = "heartbeat"
        self.mode = ["server"]

    def handle_message(self, connection: Connection, json_message: dict):
        generation = json_message.get("generation")
        if (
                json_message.get("heartbeatVersion") == 1
                and isinstance(generation, str)
                and 0 < len(generation) <= 64
        ):
            if generation != self._acknowledged_generation:
                self._acknowledged_generation = generation
                self._active_capability_sent = 0
            if self._active_capability_sent < self.ACTIVE_CAPABILITY_REPEATS:
                connection.send_message({
                    "type": "event_subscribe",
                    "event_types": [self.ACTIVE_CAPABILITY_PREFIX + generation],
                })
                self._active_capability_sent += 1

        # The pulse is intentionally one-way. Replying would make the current Java
        # Man10Socket allocate another worker for each heartbeat until it reaches 200.
        return None
