from __future__ import annotations

import json
import socket
import struct
import threading
import time
import traceback
import typing
import uuid
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Callable

from Man10Socket.utils.connection_handler.ConnectionFunction import ConnectionFunction
from Man10Socket.utils.ttl_dict import TTLDict

if TYPE_CHECKING:
    from Man10Socket.utils.connection_handler.ConnectionHandler import ConnectionHandler


class Connection:

    REPLY_STATE_TTL_SECONDS = 30
    DEFAULT_REPLY_TIMEOUT_SECONDS = 5
    DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 6
    MIN_HEARTBEAT_TIMEOUT_SECONDS = 6
    MAX_HEARTBEAT_TIMEOUT_SECONDS = 300
    LEGACY_DELIMITER = b"<E>"
    DEFAULT_FRAMING_PROTOCOL = "delimiter_v1"
    DEFAULT_MAX_FRAME_BYTES = 1024 * 1024

    def __init__(self, main: ConnectionHandler, socket_object: socket.socket, socket_id: str, mode: str = "server",
                 name: str = None, autostart: bool = True):
        self.main = main
        self.socket_object = socket_object
        self.socket_id = socket_id
        self.mode = mode

        self.name = name
        self.listening_event_types: list[str] = []
        self._lifecycle_lock = threading.Lock()
        self._started = False
        self._receive_started = False
        self._closed = False
        self._heartbeat_lock = threading.Lock()
        self._opened_at = time.monotonic()
        self._inbound_activity_seen = False
        self._heartbeat_supported = False
        self._heartbeat_stable_since: float | None = None
        self._last_heartbeat_at: float | None = None
        self._last_inbound_activity = time.monotonic()
        self._heartbeat_timeout_seconds: int | None = None
        self._heartbeat_timed_out = False
        self._heartbeat_activity_sequence = 0
        self._heartbeat_timeout_suspect_sequence: int | None = None

        self.reply_data = TTLDict(self.main.reply_state_ttl_seconds)
        self.reply_lock = TTLDict(self.main.reply_state_ttl_seconds)
        self.reply_callback = TTLDict(self.main.reply_state_ttl_seconds)
        self.reply_arguments = TTLDict(self.main.reply_state_ttl_seconds)

        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=20)

        self.message_queue = Queue()

        self.functions: dict[str, ConnectionFunction] = {}
        self.main.register_function_on_connect(self)

        def send_message_thread():
            while True:
                message = self.message_queue.get()
                try:
                    if message is None:
                        break
                    # print("Sent message", message)
                    self.__send_message_internal(message)
                except Exception as e:
                    self.socket_close()
                    print(e)
                    break
                finally:
                    self.message_queue.task_done()

        self.send_message_thread = Thread(target=send_message_thread)
        self.send_message_thread.daemon = True

        self.client_thread = threading.Thread(target=self.receive_messages)
        self.client_thread.daemon = True

        if autostart:
            self.start()

    def start(self) -> bool:
        try:
            with self._lifecycle_lock:
                if self._closed:
                    return False
                if self._started:
                    return True
                self._started = True
                self.send_message_thread.start()
                self.client_thread.start()
                self._receive_started = True
            return True
        except Exception:
            self.socket_close()
            raise

    def register_socket_function(self, socket_function: ConnectionFunction):
        socket_function.main = self.main
        self.functions[socket_function.function_type] = socket_function

    def is_closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def has_been_open_for(self, seconds: int, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        with self._lifecycle_lock:
            return not self._closed and now - self._opened_at >= seconds

    def __send_message_internal(self, message: dict):
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.main.max_frame_bytes:
            raise ValueError(f"Outgoing frame too large: {len(payload)} > {self.main.max_frame_bytes}")

        if self.main.framing_protocol == "length_prefix_v2":
            message_bytes = struct.pack("!I", len(payload)) + payload
        else:
            message_bytes = payload + self.LEGACY_DELIMITER
        self.socket_object.sendall(message_bytes)

    def send_message(self, message: dict, reply: bool = False, callback: Callable = None,
                     reply_timeout: int | None = None,
                     reply_arguments: typing.Tuple = None) -> dict | None:
        if reply_timeout is None:
            reply_timeout = self.main.default_reply_timeout_seconds
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

        with self._lifecycle_lock:
            if not self._closed:
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
        self.reply_data.pop(reply_id, None)
        self.reply_lock.pop(reply_id, None)
        self.reply_callback.pop(reply_id, None)
        self.reply_arguments.pop(reply_id, None)

    def send_reply_message(self, status: str, message, reply_id: str):
        self.send_message({"type": "reply", "replyId": reply_id, "data": message, "status": status})

    def record_inbound_activity(
            self,
            heartbeat: bool = False,
            heartbeat_timeout_seconds: int | None = None,
            now: float | None = None,
    ):
        if now is None:
            now = time.monotonic()
        first_activity = False
        with self._heartbeat_lock:
            if self._heartbeat_timed_out or self._closed:
                return
            first_activity = not self._inbound_activity_seen
            self._inbound_activity_seen = True
            self._last_inbound_activity = now
            self._heartbeat_activity_sequence += 1
            self._heartbeat_timeout_suspect_sequence = None
            if heartbeat:
                self._heartbeat_supported = True
                if (
                        isinstance(heartbeat_timeout_seconds, int)
                        and not isinstance(heartbeat_timeout_seconds, bool)
                        and self.MIN_HEARTBEAT_TIMEOUT_SECONDS
                        <= heartbeat_timeout_seconds
                        <= self.MAX_HEARTBEAT_TIMEOUT_SECONDS
                ):
                    self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
                heartbeat_continuity_seconds = (
                    self._heartbeat_timeout_seconds or self.DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
                )
                if (
                        self._last_heartbeat_at is None
                        or now - self._last_heartbeat_at > heartbeat_continuity_seconds
                ):
                    self._heartbeat_stable_since = now
                self._last_heartbeat_at = now
        if first_activity:
            self.main.connection_ready_callback(self)

    def close_if_heartbeat_timed_out(
            self,
            timeout_seconds: int,
            now: float | None = None,
            before_close: Callable[[float], None] | None = None,
    ) -> float | None:
        if timeout_seconds <= 0:
            return None
        if now is None:
            now = time.monotonic()

        with self._heartbeat_lock:
            if self._closed or self._heartbeat_timed_out or not self._heartbeat_supported:
                return None
            inactive_seconds = now - self._last_inbound_activity
            effective_timeout_seconds = max(
                self._heartbeat_timeout_seconds or timeout_seconds,
                timeout_seconds,
            )
            if inactive_seconds <= effective_timeout_seconds:
                self._heartbeat_timeout_suspect_sequence = None
                return None
            if self._heartbeat_timeout_suspect_sequence != self._heartbeat_activity_sequence:
                self._heartbeat_timeout_suspect_sequence = self._heartbeat_activity_sequence
                return None
            self._heartbeat_timed_out = True

        try:
            if before_close is not None:
                before_close(inactive_seconds)
        finally:
            self.socket_close()
        return inactive_seconds

    def has_stable_heartbeat_for(
            self,
            stable_seconds: int,
            timeout_seconds: int,
            now: float | None = None,
    ) -> bool:
        if now is None:
            now = time.monotonic()
        with self._heartbeat_lock:
            if (
                    not self._heartbeat_supported
                    or self._heartbeat_stable_since is None
                    or self._last_heartbeat_at is None
                    or self._heartbeat_timed_out
                    or self._closed
            ):
                return False
            heartbeat_continuity_seconds = self._heartbeat_timeout_seconds or timeout_seconds
            return (
                    now - self._heartbeat_stable_since >= stable_seconds
                    and now - self._last_heartbeat_at <= heartbeat_continuity_seconds
            )

    def supports_heartbeat(self) -> bool:
        with self._heartbeat_lock:
            return self._heartbeat_supported

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
        try:
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
                            json_message = json.loads(message.decode('utf-8'))
                            is_heartbeat = json_message.get("type") == "heartbeat"
                            heartbeat_generation = json_message.get("generation")
                            is_valid_heartbeat = (
                                    is_heartbeat
                                    and json_message.get("heartbeatVersion") == 1
                                    and isinstance(heartbeat_generation, str)
                                    and 0 < len(heartbeat_generation) <= 64
                            )
                            self.record_inbound_activity(
                                heartbeat=is_valid_heartbeat,
                                heartbeat_timeout_seconds=json_message.get("leaseSeconds"),
                            )
                            if is_heartbeat:
                                # Heartbeats must not wait behind business work in the executor.
                                self.handle_message(json_message)
                            else:
                                self.executor.submit(self.handle_message, json_message)
                        except Exception:
                            print(message)
                            traceback.print_exc()
                except Exception as e:
                    if not self._closed:
                        print("Error receiving data:", e)
                        traceback.print_exc()
                    break
        finally:
            try:
                self.socket_close()
            finally:
                self.executor.shutdown(wait=False, cancel_futures=False)

    def socket_close(self):
        with self._lifecycle_lock:
            first_close = not self._closed
            if first_close:
                self._closed = True
                try:
                    self.socket_object.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self.socket_object.close()
                except OSError as e:
                    print("Error closing socket:", e)
                self.message_queue.put(None)
                if not self._receive_started:
                    self.executor.shutdown(wait=False, cancel_futures=False)

            try:
                self.main.unregister_connection(self.socket_id)
            except Exception as e:
                print("Error closing socket:", e)

            if first_close:
                print("Socket closed", self.name)

    def handle_message(self, message: dict):
        message_type = message["type"]
        function = self.functions.get(message_type, None)
        if function is None:
            return
        reply = function.handle_message(self, message)
        if reply is not None and len(reply) == 2 and "replyId" in message:
            self.send_reply_message(status=reply[0], message=reply[1], reply_id=message["replyId"])
