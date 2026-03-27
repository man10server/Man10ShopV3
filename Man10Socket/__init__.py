from __future__ import annotations

import time
import typing
from threading import Thread

from Man10Socket.data_class.Player import Player
from Man10Socket.utils.command_manager.CommandHandler import CommandHandler
from Man10Socket.utils.connection_handler.Connection import Connection
from Man10Socket.utils.connection_handler.ConnectionHandler import ConnectionHandler
from Man10Socket.utils.gui_manager.GUIHandler import GUIHandler
from Man10Socket.utils.socket_functions.EventHandlerFunction import EventHandlerFunction
from Man10Socket.utils.socket_functions.ReplyFunction import ReplyFunction
from Man10Socket.utils.socket_functions.RequestFunction import RequestFunction
from utils.EnvConfig import SocketHostSettings


class Man10Socket:

    def __init__(self, session_name: str, hosts: list[SocketHostSettings],
                 reply_state_ttl_seconds: int = Connection.REPLY_STATE_TTL_SECONDS,
                 default_reply_timeout_seconds: int = Connection.DEFAULT_REPLY_TIMEOUT_SECONDS,
                 framing_protocol: str = Connection.DEFAULT_FRAMING_PROTOCOL,
                 max_frame_bytes: int = Connection.DEFAULT_MAX_FRAME_BYTES):
        self.session_name = session_name
        self.hosts = hosts

        self.connection_handler: ConnectionHandler = ConnectionHandler(
            reply_state_ttl_seconds=reply_state_ttl_seconds,
            default_reply_timeout_seconds=default_reply_timeout_seconds,
            framing_protocol=framing_protocol,
            max_frame_bytes=max_frame_bytes,
        )
        self.event_handler = EventHandlerFunction(self.connection_handler)
        self.command_handler = CommandHandler(self)

        self.player_cache: dict[str, Player] = {}

        self.custom_request = RequestFunction()

        def register_functions(connection: Connection):
            connection.register_socket_function(self.custom_request)
            connection.register_socket_function(ReplyFunction())
            connection.register_socket_function(self.event_handler)

        self.connection_handler.register_function_on_connect = register_functions

        for host in hosts:
            self.connection_handler.socket_open_server(host.name, host.host, host.port)

        self.gui_handler = GUIHandler(self)

        def check_open_socket_count_thread():
            while True:
                for server in self.hosts:
                    open_sockets = [x for x in self.connection_handler.sockets.values() if x.name == server.name]
                    if len(open_sockets) < 1:
                        print("Opening socket", server.name)
                        # open sockets until there are enough
                        open_socket = self.connection_handler.socket_open_server(server.name, server.host,
                                                                                 server.port)
                        if open_socket is None:
                            print("Failed to open socket", server.name)
                        else:
                            self.initialize_connection(server.name)

                time.sleep(1)

        self.check_open_socket_count_thread = Thread(target=check_open_socket_count_thread)
        self.check_open_socket_count_thread.daemon = True
        self.check_open_socket_count_thread.start()
        self.initialize_connected_hosts()

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
