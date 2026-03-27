import json
import queue
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Thread

import humps
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from flask import Flask
from pymongo import MongoClient
from starlette.responses import JSONResponse

from Man10ShopV3.data_class.OrderRequest import OrderRequest
from Man10ShopV3.data_class.Player import Player
from Man10ShopV3.manager.EventManager import EventManager
from Man10ShopV3.manager.Man10ShopV3API import Man10ShopV3API
from Man10ShopV3.methods.shop import ShopMethods
from Man10Socket import Man10Socket
from Man10Socket.utils.connection_handler.Connection import Connection
from menu.action_menu.BuyAndSellActionMenu import BuyAndSellActionMenu


class Man10ShopV3:
    def sub_queue_process(self, queue_id: int):
        queue_object = self.sub_queue[queue_id]
        while self.running:
            try:
                while not queue_object.empty():
                    request = queue_object.get()
                    if request == "END":
                        return
                    # completed_task.append(request["_id"])
                    shop = self.api.get_shop(request["shop_id"])
                    if shop is None:
                        continue

                    shop.execute_queue_callback(request["key"], request)

                time.sleep(0.1)

            except Exception:
                traceback.print_exc()
                continue

    def main_queue_process(self):
        while self.running:
            try:
                while not self.main_queue.empty():
                    request = self.main_queue.get()
                    if request == "END":
                        return
                    request: dict = humps.decamelize(request)
                    if "player" in request and request["player"] is not None:
                        player_data = request["player"]
                        # if request["key"] == "shop.order" and self.check_rate_limited(player_data["uuid"]):
                        #     continue
                        player_object = Player().load_from_json(player_data, self)
                        request["player"] = player_object

                    queue_id = uuid.UUID(request["shop_id"]).int % self.config["queue"]["size"]
                    # if request["key"] == "shop.order" and self.config["queue"]["maxOrders"] != 0 and self.sub_queue[queue_id].qsize() >= self.config["queue"]["maxOrders"]:
                    #     continue
                    self.sub_queue[queue_id].put(request)

                time.sleep(0.1)

            except Exception:
                traceback.print_exc()
                continue

    def check_rate_limited(self, player_uuid: str):
        rate = self.config["queue"]["rateLimit"]
        if rate == 0:
            return False
        current_time = datetime.now().timestamp()
        if player_uuid in self.queue_rate_limit_map:
            time_diff = current_time - self.queue_rate_limit_map.get(player_uuid)
            if time_diff < rate:
                return True
        self.queue_rate_limit_map[player_uuid] = current_time
        return False

    def process_per_minute_execution_task(self):
        timer = 0
        while self.running:
            time.sleep(1)
            timer += 1
            if timer % 60 != 0:
                continue
            try:
                for shop in self.api.shops.values():
                    shop.execute_per_minute_execution_task()
            except Exception:
                traceback.print_exc()

    def __init__(self):
        # variables
        self.app = FastAPI()

        self.flask = Flask(__name__)
        self.running = True
        self.flask.url_map.strict_slashes = False
        self.config = {}
        self.thread_pool = ThreadPoolExecutor(max_workers=30)

        # load config

        config_file = open("config/config.json", encoding="utf-8")
        self.config = json.loads(config_file.read())
        config_file.close()

        self.man10_socket = Man10Socket(
            "Man10ShopV3",
            hosts=self.config["man10socket"]["hosts"],
            reply_state_ttl_seconds=self.config["man10socket"].get("replyStateTtlSeconds", 30),
            default_reply_timeout_seconds=self.config["man10socket"].get("defaultReplyTimeoutSeconds", 5),
            framing_protocol=self.config["man10socket"].get("framingProtocol", "delimiter_v1"),
            max_frame_bytes=self.config["man10socket"].get("maxFrameBytes", 1024 * 1024),
        )

        self.mongo = MongoClient(self.config["mongodbConnectionString"])
        # print([x for x in self.mongo["man10shop_v3"]["shops"].find({})])

        self.api = Man10ShopV3API(self)
        self.api.load_all_shops()

        self.event_manager = EventManager(self)

        self.shop_method = ShopMethods(self)

        # create queue
        self.queue_rate_limit_map = {}
        self.main_queue = queue.Queue(maxsize=0)
        self.sub_queue = {}
        Thread(target=self.main_queue_process).start()
        for x in range(self.config["queue"]["size"]):
            self.sub_queue[x] = queue.Queue(maxsize=0)
            Thread(target=self.sub_queue_process, args=(x,)).start()

        Thread(target=self.process_per_minute_execution_task).start()

        # self.flask.run("0.0.0.0", self.config["hostPort"], threaded=True, debug=False)
        uvicorn.run(
            self.app,
            port=self.config["hostPort"],
            host="0.0.0.0"
        )
        self.running = False
        self.main_queue.put("CLOSE")
        for x in range(self.config["queue"]["size"]):
            self.sub_queue[x].put("CLOSE")
