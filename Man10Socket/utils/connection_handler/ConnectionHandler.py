from __future__ import annotations

import json
import socket
import threading
import traceback
import uuid
from threading import Thread
from typing import TYPE_CHECKING, Callable

from Man10Socket.utils.connection_handler.Connection import Connection
if TYPE_CHECKING:
    pass


class ConnectionHandler:

    CONNECT_TIMEOUT_SECONDS = 2
    TCP_KEEPIDLE_SECONDS = 30
    TCP_KEEPINTERVAL_SECONDS = 10
    TCP_KEEPCNT = 3
    TCP_USER_TIMEOUT_MILLISECONDS = 40_000

    def __init__(self, reply_state_ttl_seconds: int = Connection.REPLY_STATE_TTL_SECONDS,
                 default_reply_timeout_seconds: int = Connection.DEFAULT_REPLY_TIMEOUT_SECONDS,
                 framing_protocol: str = Connection.DEFAULT_FRAMING_PROTOCOL,
                 max_frame_bytes: int = Connection.DEFAULT_MAX_FRAME_BYTES):

        self.sockets: dict[str, Connection] = {}
        self.same_name_sockets: dict[str, list[str]] = {}
        self._registry_lock = threading.RLock()
        self.get_counter = 0
        self.reply_state_ttl_seconds = reply_state_ttl_seconds
        self.default_reply_timeout_seconds = default_reply_timeout_seconds
        if framing_protocol not in {"delimiter_v1", "length_prefix_v2"}:
            raise ValueError(f"Unsupported framing protocol: {framing_protocol}")
        if max_frame_bytes <= 0:
            raise ValueError(f"max_frame_bytes must be positive: {max_frame_bytes}")
        self.framing_protocol = framing_protocol
        self.max_frame_bytes = max_frame_bytes
        self._socket_option_warning_lock = threading.Lock()
        self._warned_socket_options: set[str] = set()

        def empty(connection):
            pass

        self.register_function_on_connect: Callable[[Connection], None] = empty
        self.connection_registered_callback: Callable[[Connection], None] = empty
        self.connection_unregistered_callback: Callable[[Connection], None] = empty
        self.connection_ready_callback: Callable[[Connection], None] = empty

    def register_connection(self, connection: Connection):
        with self._registry_lock:
            self.sockets[connection.socket_id] = connection
            if connection.name is not None:
                socket_ids = self.same_name_sockets.setdefault(connection.name, [])
                if connection.socket_id not in socket_ids:
                    socket_ids.append(connection.socket_id)
        self.connection_registered_callback(connection)

    def unregister_connection(self, socket_id: str):
        connection = None
        with self._registry_lock:
            connection = self.sockets.pop(socket_id, None)
            for name in list(self.same_name_sockets):
                socket_ids = self.same_name_sockets[name]
                if socket_id in socket_ids:
                    socket_ids.remove(socket_id)
                if len(socket_ids) == 0:
                    del self.same_name_sockets[name]
        if connection is not None:
            self.connection_unregistered_callback(connection)

    def _warn_socket_option_once(self, option_name: str, message: str):
        with self._socket_option_warning_lock:
            if option_name in self._warned_socket_options:
                return
            self._warned_socket_options.add(option_name)
        print(f"Socket option {option_name} unavailable: {message}")

    def _set_socket_option(
            self,
            client_socket: socket.socket,
            level: int,
            option: int | None,
            value: int,
            option_name: str,
    ):
        if option is None:
            self._warn_socket_option_once(option_name, "not exposed by this platform")
            return
        try:
            client_socket.setsockopt(level, option, value)
        except OSError as exception:
            self._warn_socket_option_once(option_name, str(exception))

    def _configure_server_socket(self, client_socket: socket.socket):
        self._set_socket_option(client_socket, socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1, "SO_KEEPALIVE")

        keepidle_option = getattr(socket, "TCP_KEEPIDLE", None)
        if keepidle_option is None:
            keepidle_option = getattr(socket, "TCP_KEEPALIVE", None)

        self._set_socket_option(
            client_socket,
            socket.IPPROTO_TCP,
            keepidle_option,
            self.TCP_KEEPIDLE_SECONDS,
            "TCP_KEEPIDLE",
        )
        self._set_socket_option(
            client_socket,
            socket.IPPROTO_TCP,
            getattr(socket, "TCP_KEEPINTVL", None),
            self.TCP_KEEPINTERVAL_SECONDS,
            "TCP_KEEPINTVL",
        )
        self._set_socket_option(
            client_socket,
            socket.IPPROTO_TCP,
            getattr(socket, "TCP_KEEPCNT", None),
            self.TCP_KEEPCNT,
            "TCP_KEEPCNT",
        )
        self._set_socket_option(
            client_socket,
            socket.IPPROTO_TCP,
            getattr(socket, "TCP_USER_TIMEOUT", None),
            self.TCP_USER_TIMEOUT_MILLISECONDS,
            "TCP_USER_TIMEOUT",
        )

    def get_connections(self) -> list[Connection]:
        with self._registry_lock:
            return list(self.sockets.values())

    def is_registered(self, connection: Connection) -> bool:
        with self._registry_lock:
            return self.sockets.get(connection.socket_id) is connection

    def socket_open_server(self, name, host, port) -> socket.socket | None:
        socket_id = str(uuid.uuid4())
        client_socket = None
        connection = None
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._configure_server_socket(client_socket)
            client_socket.settimeout(self.CONNECT_TIMEOUT_SECONDS)
            client_socket.connect((host, port))
            client_socket.settimeout(None)
            print("Socket opened", name)
            connection = Connection(self, client_socket, socket_id=socket_id, mode="server", name=name,
                                    autostart=False)
            self.register_connection(connection)
            if not connection.start():
                connection.socket_close()
                return None
            return client_socket
        except OSError as e:
            if connection is not None:
                connection.socket_close()
            elif client_socket is not None:
                client_socket.close()
            print(f"Socket open failed ({name} {host}:{port}): {e}")
            return None
        except Exception:
            if connection is not None:
                connection.socket_close()
            elif client_socket is not None:
                client_socket.close()
            traceback.print_exc()
            return None

    def open_socket_client(self, host, port):
        def start_server():
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.bind((host, port))
            server_socket.listen()

            print(f"Listening on {host}:{port}...")

            try:
                while True:
                    client_socket, addr = server_socket.accept()
                    socket_id = str(uuid.uuid4())
                    connection = Connection(self, client_socket, socket_id, "client", autostart=False)
                    self.register_connection(connection)
                    try:
                        if not connection.start():
                            connection.socket_close()
                    except Exception:
                        connection.socket_close()
                        traceback.print_exc()
            finally:
                server_socket.close()

        self.server_thread = Thread(target=start_server)
        self.server_thread.daemon = True
        self.server_thread.start()

    def get_server_socket(self, socket_id) -> Connection:
        with self._registry_lock:
            return self.sockets[socket_id]

    def get_socket(self, name: str) -> Connection | None:
        with self._registry_lock:
            if name not in self.same_name_sockets:
                return None
            socket_ids = self.same_name_sockets[name]
            if len(socket_ids) == 0:
                return None

            # Clean up stale ids that no longer exist in self.sockets.
            valid_socket_ids = [socket_id for socket_id in socket_ids if socket_id in self.sockets]
            if len(valid_socket_ids) != len(socket_ids):
                if len(valid_socket_ids) == 0:
                    del self.same_name_sockets[name]
                    return None
                self.same_name_sockets[name] = valid_socket_ids

            import random
            rand = random.randint(0, len(valid_socket_ids) - 1)
            socket_id = valid_socket_ids[rand]
            return self.sockets.get(socket_id)
