from __future__ import annotations

import random
import time
import typing
from threading import Lock, Thread

from Man10Socket.data_class.Player import Player
from Man10Socket.utils.command_manager.CommandHandler import CommandHandler
from Man10Socket.utils.connection_handler.Connection import Connection
from Man10Socket.utils.connection_handler.ConnectionHandler import ConnectionHandler
from Man10Socket.utils.gui_manager.GUIHandler import GUIHandler
from Man10Socket.utils.socket_functions.EventHandlerFunction import EventHandlerFunction
from Man10Socket.utils.socket_functions.HeartbeatFunction import HeartbeatFunction
from Man10Socket.utils.socket_functions.ReplyFunction import ReplyFunction
from Man10Socket.utils.socket_functions.RequestFunction import RequestFunction
from utils.EnvConfig import SocketHostSettings


class Man10Socket:

    RECONNECT_MAX_DELAY_SECONDS = 30
    RECONNECT_CHECK_INTERVAL_SECONDS = 0.25
    STABLE_CONNECTION_RESET_SECONDS = 120
    HEARTBEAT_WATCHDOG_INTERVAL_SECONDS = 0.25
    HEARTBEAT_PROBATION_TIMEOUT_SECONDS = 15
    HEARTBEAT_PROBATION_STABLE_SECONDS = 60

    def __init__(self, session_name: str, hosts: list[SocketHostSettings],
                 reply_state_ttl_seconds: int = Connection.REPLY_STATE_TTL_SECONDS,
                 default_reply_timeout_seconds: int = Connection.DEFAULT_REPLY_TIMEOUT_SECONDS,
                 framing_protocol: str = Connection.DEFAULT_FRAMING_PROTOCOL,
                 max_frame_bytes: int = Connection.DEFAULT_MAX_FRAME_BYTES,
                 heartbeat_timeout_seconds: int = Connection.DEFAULT_HEARTBEAT_TIMEOUT_SECONDS):
        if heartbeat_timeout_seconds != 0 and not (
                Connection.MIN_HEARTBEAT_TIMEOUT_SECONDS
                <= heartbeat_timeout_seconds
                <= Connection.MAX_HEARTBEAT_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "heartbeat_timeout_seconds must be 0 or between "
                f"{Connection.MIN_HEARTBEAT_TIMEOUT_SECONDS} and "
                f"{Connection.MAX_HEARTBEAT_TIMEOUT_SECONDS}: {heartbeat_timeout_seconds}"
            )
        self.session_name = session_name
        self.hosts = hosts
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._reconnect_failures = {host.name: 0 for host in hosts}
        self._next_reconnect_at = {host.name: 0.0 for host in hosts}
        self._awaiting_heartbeat = {host.name: None for host in hosts}
        self._active_socket_ids = {host.name: None for host in hosts}
        self._heartbeat_probation = {host.name: False for host in hosts}
        self._heartbeat_recovery_pending: dict[str, tuple[str, float]] = {}
        self._reconnect_lock = Lock()

        self.connection_handler: ConnectionHandler = ConnectionHandler(
            reply_state_ttl_seconds=reply_state_ttl_seconds,
            default_reply_timeout_seconds=default_reply_timeout_seconds,
            framing_protocol=framing_protocol,
            max_frame_bytes=max_frame_bytes,
        )
        self.connection_handler.connection_registered_callback = self._connection_registered
        self.connection_handler.connection_unregistered_callback = self._connection_closed
        self.connection_handler.connection_ready_callback = self._connection_ready
        self.event_handler = EventHandlerFunction(self.connection_handler)
        if (
                self.heartbeat_timeout_seconds > 0
                and HeartbeatFunction.CAPABILITY not in self.event_handler.listening_event_types
        ):
            self.event_handler.listening_event_types.append(HeartbeatFunction.CAPABILITY)
        self.command_handler = CommandHandler(self)

        self.player_cache: dict[str, Player] = {}

        self.custom_request = RequestFunction()

        def register_functions(connection: Connection):
            connection.register_socket_function(self.custom_request)
            connection.register_socket_function(ReplyFunction())
            connection.register_socket_function(self.event_handler)
            if self.heartbeat_timeout_seconds > 0:
                connection.register_socket_function(HeartbeatFunction())

        self.connection_handler.register_function_on_connect = register_functions

        for host in hosts:
            if self.connection_handler.socket_open_server(host.name, host.host, host.port) is None:
                self._schedule_reconnect(host.name)

        self.gui_handler = GUIHandler(self)

        def heartbeat_watchdog_thread():
            while True:
                tick_started_at = time.monotonic()
                for connection in self.connection_handler.get_connections():
                    try:
                        timeout_seconds = self._effective_heartbeat_timeout(connection.name)

                        def record_timeout(inactive_seconds: float, monitored_connection=connection):
                            self._record_heartbeat_timeout(
                                monitored_connection,
                                inactive_seconds,
                                tick_started_at,
                            )

                        inactive_seconds = connection.close_if_heartbeat_timed_out(
                            timeout_seconds,
                            tick_started_at,
                            before_close=record_timeout,
                        )
                        if (
                                inactive_seconds is None
                                and connection.has_stable_heartbeat_for(
                                    self.HEARTBEAT_PROBATION_STABLE_SECONDS,
                                    timeout_seconds,
                                    tick_started_at,
                                )
                        ):
                            self._end_heartbeat_probation(connection)
                    except Exception as exception:
                        print(
                            "[Man10Socket heartbeat] Watchdog error "
                            f"(target={connection.name}, socket_id={connection.socket_id}): {exception}"
                        )

                elapsed_seconds = time.monotonic() - tick_started_at
                time.sleep(max(0.0, self.HEARTBEAT_WATCHDOG_INTERVAL_SECONDS - elapsed_seconds))

        def maintain_host_connection(server: SocketHostSettings):
            while True:
                now = time.monotonic()
                open_sockets = [
                    connection
                    for connection in self.connection_handler.get_connections()
                    if connection.name == server.name
                ]
                for connection in open_sockets:
                    if (
                            connection.has_been_open_for(self.STABLE_CONNECTION_RESET_SECONDS, now)
                            and not connection.supports_heartbeat()
                    ):
                        self._connection_ready(connection, recovery_confirmed=False)
                        self._end_heartbeat_probation(
                            connection,
                            stable_seconds=self.STABLE_CONNECTION_RESET_SECONDS,
                        )

                if len(open_sockets) < 1 and self._reconnect_due(server.name, now):
                    print("Opening socket", server.name)
                    open_socket = self.connection_handler.socket_open_server(server.name, server.host, server.port)
                    if open_socket is None:
                        print("Failed to open socket", server.name)
                        self._schedule_reconnect(server.name)
                    else:
                        self.initialize_connection(server.name)

                time.sleep(self.RECONNECT_CHECK_INTERVAL_SECONDS)

        self.heartbeat_watchdog_thread = Thread(target=heartbeat_watchdog_thread)
        self.heartbeat_watchdog_thread.daemon = True
        self.heartbeat_watchdog_thread.start()
        self.check_open_socket_count_threads = []
        for host in hosts:
            thread = Thread(
                target=maintain_host_connection,
                args=(host,),
                name=f"Man10Socket-Reconnect-{host.name}",
                daemon=True,
            )
            thread.start()
            self.check_open_socket_count_threads.append(thread)
        self.check_open_socket_count_thread = (
            self.check_open_socket_count_threads[0]
            if self.check_open_socket_count_threads
            else None
        )
        self.initialize_connected_hosts()

    def _schedule_reconnect(self, target: str):
        with self._reconnect_lock:
            self._schedule_reconnect_locked(target)

    def _schedule_reconnect_locked(self, target: str, now: float | None = None):
        if now is None:
            now = time.monotonic()
        failures = self._reconnect_failures.get(target, 0) + 1
        self._reconnect_failures[target] = failures
        capped_exponent = min(failures - 1, 5)
        base_delay = min(2 ** capped_exponent, self.RECONNECT_MAX_DELAY_SECONDS)
        delay = (base_delay / 2) + random.uniform(0, base_delay / 2)
        self._next_reconnect_at[target] = now + delay

    def _reconnect_due(self, target: str, now: float) -> bool:
        with self._reconnect_lock:
            return (
                    self._active_socket_ids.get(target) is None
                    and now >= self._next_reconnect_at.get(target, 0)
            )

    def _connection_registered(self, connection: Connection):
        if connection.name is None or connection.name not in self._awaiting_heartbeat:
            return
        with self._reconnect_lock:
            self._active_socket_ids[connection.name] = connection.socket_id
            self._awaiting_heartbeat[connection.name] = connection.socket_id

    def _connection_closed(self, connection: Connection):
        if connection.name is None or connection.name not in self._active_socket_ids:
            return
        now = time.monotonic()
        with self._reconnect_lock:
            if self._active_socket_ids.get(connection.name) != connection.socket_id:
                return
            self._active_socket_ids[connection.name] = None
            was_awaiting_heartbeat = self._awaiting_heartbeat.get(connection.name) == connection.socket_id
            self._awaiting_heartbeat[connection.name] = None

            recovery = self._heartbeat_recovery_pending.get(connection.name)
            if recovery is not None and recovery[0] == connection.socket_id:
                return

            if was_awaiting_heartbeat:
                self._schedule_reconnect_locked(connection.name, now)
                return

            already_in_probation = self._heartbeat_probation.get(connection.name, False)
            self._heartbeat_probation[connection.name] = True
            self._heartbeat_recovery_pending[connection.name] = (connection.socket_id, now)
            if already_in_probation:
                self._schedule_reconnect_locked(connection.name, now)
            else:
                self._next_reconnect_at[connection.name] = now
            retry_delay_seconds = max(0.0, self._next_reconnect_at[connection.name] - now)

        print(
            "[Man10Socket reconnect] Established connection closed unexpectedly "
            f"(target={connection.name}, socket_id={connection.socket_id}); reconnecting"
        )
        if already_in_probation:
            print(
                "[Man10Socket reconnect] Repeated close during probation; applying reconnect backoff "
                f"(target={connection.name}, retry_delay_seconds={retry_delay_seconds:.1f})"
            )
        else:
            print(
                "[Man10Socket reconnect] Anti-flapping probation enabled "
                f"(target={connection.name}, stable_seconds={self.HEARTBEAT_PROBATION_STABLE_SECONDS})"
            )

    def _reset_reconnect_locked(self, target: str):
        self._reconnect_failures[target] = 0
        self._next_reconnect_at[target] = 0.0

    def _effective_heartbeat_timeout(self, target: str | None) -> int:
        if target is None:
            return self.heartbeat_timeout_seconds
        with self._reconnect_lock:
            if self._heartbeat_probation.get(target, False):
                return max(self.heartbeat_timeout_seconds, self.HEARTBEAT_PROBATION_TIMEOUT_SECONDS)
            return self.heartbeat_timeout_seconds

    def _record_heartbeat_timeout(self, connection: Connection, inactive_seconds: float, now: float):
        if connection.name is None:
            return
        with self._reconnect_lock:
            if self._active_socket_ids.get(connection.name) != connection.socket_id:
                return
            already_in_probation = self._heartbeat_probation.get(connection.name, False)
            self._heartbeat_probation[connection.name] = True
            self._heartbeat_recovery_pending[connection.name] = (connection.socket_id, now)
            if already_in_probation:
                self._schedule_reconnect_locked(connection.name, now)
            else:
                self._next_reconnect_at[connection.name] = now
            retry_delay_seconds = max(0.0, self._next_reconnect_at[connection.name] - now)
        print(
            "[Man10Socket heartbeat] Half-open connection detected "
            f"(target={connection.name}, socket_id={connection.socket_id}, "
            f"inactive_seconds={inactive_seconds:.1f}); closing and reconnecting"
        )
        if already_in_probation:
            print(
                "[Man10Socket heartbeat] Repeated timeout during probation; applying reconnect backoff "
                f"(target={connection.name}, retry_delay_seconds={retry_delay_seconds:.1f})"
            )
        else:
            print(
                "[Man10Socket heartbeat] Anti-flapping probation enabled "
                f"(target={connection.name}, timeout_seconds={self.HEARTBEAT_PROBATION_TIMEOUT_SECONDS}, "
                f"stable_seconds={self.HEARTBEAT_PROBATION_STABLE_SECONDS})"
            )

    def _connection_ready(self, connection: Connection, recovery_confirmed: bool = True):
        if (
                connection.name is None
                or connection.is_closed()
                or not self.connection_handler.is_registered(connection)
        ):
            return
        with self._reconnect_lock:
            if (
                    self._active_socket_ids.get(connection.name) != connection.socket_id
                    or self._awaiting_heartbeat.get(connection.name) != connection.socket_id
            ):
                return
            if not self._heartbeat_probation.get(connection.name, False):
                self._reset_reconnect_locked(connection.name)
            if not recovery_confirmed:
                return
            self._awaiting_heartbeat[connection.name] = None
            recovery = self._heartbeat_recovery_pending.pop(connection.name, None)

        if recovery is not None:
            old_socket_id, detected_at = recovery
            print(
                "[Man10Socket heartbeat] Reconnect confirmed by inbound traffic "
                f"(target={connection.name}, old_socket_id={old_socket_id}, "
                f"new_socket_id={connection.socket_id}, "
                f"recovery_seconds={max(0.0, time.monotonic() - detected_at):.1f})"
            )

    def _end_heartbeat_probation(
            self,
            connection: Connection,
            stable_seconds: int | None = None,
    ):
        if stable_seconds is None:
            stable_seconds = self.HEARTBEAT_PROBATION_STABLE_SECONDS
        if (
                connection.name is None
                or connection.is_closed()
                or not self.connection_handler.is_registered(connection)
        ):
            return
        with self._reconnect_lock:
            if (
                    self._active_socket_ids.get(connection.name) != connection.socket_id
                    or not self._heartbeat_probation.get(connection.name, False)
            ):
                return
            self._heartbeat_probation[connection.name] = False
            self._reset_reconnect_locked(connection.name)
        print(
            "[Man10Socket heartbeat] Connection stable; anti-flapping probation cleared "
            f"(target={connection.name}, socket_id={connection.socket_id}, "
            f"stable_seconds={stable_seconds}, "
            f"timeout_seconds={self.heartbeat_timeout_seconds})"
        )

    def initialize_connected_hosts(self):
        for host in self.hosts:
            if self.connection_handler.get_socket(host.name) is None:
                continue
            self.initialize_connection(host.name)

    def initialize_connection(self, target: str):
        if self.connection_handler.get_socket(target) is None:
            return False
        self.set_session_name(target, self.session_name)
        self.event_handler.subscribe_to_server(target)
        self.command_handler.register_all_commands(target)
        return True


    def get_default_target(self) -> str | None:
        if len(self.hosts) == 0:
            return None
        return self.hosts[0].name

    def get_player(self, player_uuid: str, server: str | None = None) -> Player|None:
        if player_uuid is None:
            return None
        if player_uuid in self.player_cache:
            player = self.player_cache[player_uuid]
            if server is not None:
                player.set_server(server)
            return player
        player = Player(player_uuid, self, server=server)
        self.player_cache[player_uuid] = player
        return player

    def send_message(self, target: str, message: dict, reply: bool = False, callback: typing.Callable = None,
                     reply_timeout: int | None = None,
                     reply_arguments: typing.Tuple = None):
        socket_connection = self.connection_handler.get_socket(target)
        if socket_connection is None:
            print("Socket not connected:", target)
            return None
        return socket_connection.send_message(message, reply, callback, reply_timeout, reply_arguments)

    def set_session_name(self, target: str, session_name: str):
        self.session_name = session_name
        self.send_message(target, {"type": "set_name", "name": session_name})

    def register_route(self, path: str, callback: typing.Callable[[dict], typing.Tuple]):
        self.custom_request.register_route(path, callback)
