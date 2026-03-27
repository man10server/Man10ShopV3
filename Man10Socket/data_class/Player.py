from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from Man10Socket import Man10Socket
    from Man10Socket.utils.gui_manager.GUI import GUI


class Player:

    def __init__(self, player_uuid: str, main: Man10Socket, server: str | None = None):
        self.__uuid = player_uuid
        self.__main: Man10Socket = main
        self.__server = server if server is not None else self.__main.get_default_target()
        self.current_gui: str|None = None

    def get_uuid(self) -> str:
        return self.__uuid

    def get_server(self) -> str | None:
        return self.__server if self.__server is not None else self.__main.get_default_target()

    def set_server(self, server: str | None):
        self.__server = server if server is not None else self.__main.get_default_target()

    def open_gui(self, gui: GUI):
        self.__main.gui_handler.open_gui(self, gui)

    def send_message(self, message: str, send_async: bool = False):
        target_server = self.get_server()
        if target_server is None:
            print("Socket target is not configured")
            return None
        socket_connection = self.__main.connection_handler.get_socket(target_server)
        if socket_connection is None:
            print("Socket not connected:", target_server)
            return None
        return socket_connection.send_message({
            "type": "player_tell",
            "target": self.__uuid,
            "player": self.__uuid,
            "message": message
        }, reply=not send_async)
