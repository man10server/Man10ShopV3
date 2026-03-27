from __future__ import annotations

import json
import socket
import struct
import threading
import traceback
import typing
import uuid
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Callable

from expiring_dict import ExpiringDict

from Man10Socket.utils.connection_handler.ConnectionFunction import ConnectionFunction

if TYPE_CHECKING:
    from Man10Socket.utils.connection_handler.ConnectionHandler import ConnectionHandler


class Connection:

    LEGACY_DELIMITER = b"<E>"
    DEFAULT_FRAMING_PROTOCOL = "delimiter_v1"
    DEFAULT_MAX_FRAME_BYTES = 1024 * 1024

    def __init__(self, main: ConnectionHandler, socket_object: socket.socket, socket_id: str, mode: str = "server",
                 name: str = None):
        self.main = main
        self.socket_object = socket_object
        self.socket_id = socket_id
        self.mode = mode

        self.name = name
        self.listening_event_types: list[str] = []

        self.reply_data = ExpiringDict(5)
        self.reply_lock = ExpiringDict(5)
        self.reply_callback = ExpiringDict(5)
        self.reply_arguments = ExpiringDict(5)

        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=20)

        self.message_queue = Queue()

        self.functions: dict[str, ConnectionFunction] = {}
        self.main.register_function_on_connect(self)

        def send_message_thread():
            while True:
                try:
                    message = self.message_queue.get()
                    # print("Sent message", message)
                    self.__send_message_internal(message)
                    self.message_queue.task_done()
                except Exception as e:
                    self.socket_close()
                    print(e)
                    break

        self.send_message_thread = Thread(target=send_message_thread)
        self.send_message_thread.daemon = True
        self.send_message_thread.start()

        self.client_thread = threading.Thread(target=self.receive_messages)
        self.client_thread.daemon = True
        self.client_thread.start()

    def register_socket_function(self, socket_function: ConnectionFunction):
        socket_function.main = self.main
        self.functions[socket_function.function_type] = socket_function

    def __send_message_internal(self, message: dict):
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.main.max_frame_bytes:
            raise ValueError(f"Outgoing frame too large: {len(payload)} > {self.main.max_frame_bytes}")

        if self.main.framing_protocol == "length_prefix_v2":
            message_bytes = struct.pack("!I", len(payload)) + payload
        else:
            message_bytes = payload + self.LEGACY_DELIMITER
        self.socket_object.sendall(message_bytes)

    def send_message(self, message: dict, reply: bool = False, callback: Callable = None, reply_timeout: int = 1,
                     reply_arguments: typing.Tuple = None) -> dict | None:
        if reply or callback is not None:
            reply = True
            reply_id = str(uuid.uuid4())

            if reply_id:
                message["replyId"] = reply_id
                if callback is not None:
                    self.reply_callback[reply_id] = callback
                    self.reply_arguments[reply_id] = () if reply_arguments is None else reply_arguments
                else:
                    response_event = threading.Event()
                    self.reply_lock[reply_id] = response_event

        self.message_queue.put(message)

        if reply and callback is None:
            # Wait for the event to be set or timeout after 1 second
            event_triggered = response_event.wait(reply_timeout)
            reply = None
            if event_triggered:
                # Event was set, response received
                reply = self.reply_data.get(reply_id, None)

            # Clean up the reply data
            self.clean_reply_data(reply_id)
            return reply

    def clean_reply_data(self, reply_id: str):
        if reply_id in self.reply_data: del self.reply_data[reply_id]
        if reply_id in self.reply_lock: del self.reply_lock[reply_id]
        if reply_id in self.reply_callback: del self.reply_callback[reply_id]
        if reply_id in self.reply_arguments: del self.reply_arguments[reply_id]

    def send_reply_message(self, status: str, message, reply_id: str):
        self.send_message({"type": "reply", "replyId": reply_id, "data": message, "status": status})

    def _extract_next_message(self, buffer: bytes) -> tuple[bytes | None, bytes]:
        if self.main.framing_protocol == "length_prefix_v2":
            if len(buffer) < 4:
                return None, buffer

            frame_length = struct.unpack("!I", buffer[:4])[0]
            if frame_length > self.main.max_frame_bytes:
                raise ValueError(f"Incoming frame too large: {frame_length} > {self.main.max_frame_bytes}")

            frame_end = 4 + frame_length
            if len(buffer) < frame_end:
                return None, buffer

            return buffer[4:frame_end], buffer[frame_end:]

        delimiter_index = buffer.find(self.LEGACY_DELIMITER)
        if delimiter_index == -1:
            if len(buffer) > self.main.max_frame_bytes + len(self.LEGACY_DELIMITER):
                raise ValueError(f"Incoming frame exceeded max size without delimiter: {len(buffer)}")
            return None, buffer

        if delimiter_index > self.main.max_frame_bytes:
            raise ValueError(f"Incoming frame too large: {delimiter_index} > {self.main.max_frame_bytes}")

        frame = buffer[:delimiter_index]
        remainder = buffer[delimiter_index + len(self.LEGACY_DELIMITER):]
        return frame, remainder

    def receive_messages(self):
        buffer = b""
        while True:
            try:
                data = self.socket_object.recv(2**10)
                if not data:
                    break
                buffer += data
                while True:
                    message, buffer = self._extract_next_message(buffer)
                    if message is None:
                        break
                    try:
                        def task(message_object):
                            json_message = json.loads(message_object.decode('utf-8'))
                            self.handle_message(json_message)

                        self.executor.submit(task, message)
                    except Exception:
                        print(message)
                        traceback.print_exc()
            except Exception as e:
                print("Error receiving data:", e)
                traceback.print_exc()
                break
        self.socket_close()

    def socket_close(self):
        try:
            self.socket_object.close()
            if self.socket_id in self.main.sockets:
                del self.main.sockets[self.socket_id]

            same_name = self.main.same_name_sockets.copy()

            for name in same_name:
                if self.socket_id in same_name[name]:
                    self.main.same_name_sockets[name].remove(self.socket_id)
                    if len(self.main.same_name_sockets[name]) == 0:
                        del self.main.same_name_sockets[name]

            print("Socket closed", self.name)
        except Exception as e:
            print("Error closing socket:", e)

    def handle_message(self, message: dict):
        message_type = message["type"]
        function = self.functions.get(message_type, None)
        if function is None:
            return
        reply = function.handle_message(self, message)
        if reply is not None and len(reply) == 2 and "replyId" in message:
            self.send_reply_message(status=reply[0], message=reply[1], reply_id=message["replyId"])
