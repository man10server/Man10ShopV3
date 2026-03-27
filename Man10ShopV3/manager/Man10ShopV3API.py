from __future__ import annotations

import datetime
import json
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Optional

import humps
import requests
from tqdm import tqdm

from Man10ShopV3.data_class.Player import Player
from Man10ShopV3.data_class.Shop import Shop
from Man10ShopV3.data_class.Sign import Sign

if TYPE_CHECKING:
    from Man10ShopV3 import Man10ShopV3


class Man10ShopV3API:

    def __init__(self, main: Man10ShopV3):
        self.main = main

        self.shops: dict[str, Shop] = {}

        self.base_shop_object = Shop(self)
        self.base_shop_object.api = None
        self.threadpool = ThreadPoolExecutor(max_workers=50)

        self.shop_variable_update_queue = Queue()
        self.shop_variable_update_thread = Thread(target=self.shop_variable_update_thread)
        self.shop_variable_update_thread.start()

        self.player_data_update_queue = Queue()
        self.player_data_update_thread = Thread(target=self.player_data_update_thread)
        self.player_data_update_thread.start()

        self.sign_cache = {}

    def shop_variable_update_thread(self):
        temp_queue = {}
        # schema of object
        # "shop_id": self.get_shop_id(),
        # "key": key,
        # "value": value
        while True:
            try:
                time.sleep(self.main.settings.batching.set_variable_batch_seconds)

                while not self.shop_variable_update_queue.empty():
                    set_variable_request_object = self.shop_variable_update_queue.get()
                    shop_id = set_variable_request_object["shop_id"]
                    key = set_variable_request_object["key"]
                    value = set_variable_request_object["value"]
                    if shop_id not in temp_queue:
                        temp_queue[shop_id] = {}
                    temp_queue[shop_id][key] = value

                if len(temp_queue) == 0:
                    continue

                for shop_id in list(temp_queue.keys()):
                    temp_queue[shop_id] = humps.camelize(temp_queue[shop_id])
                for shop_id in list(temp_queue.keys()):
                    print("Pushed data to database: " + shop_id + " " + str(temp_queue[shop_id]))
                    self.main.mongo["man10shop_v3"]["shops"].update_one({"shopId": shop_id},
                                                                        {"$set": temp_queue[shop_id]})
                    del temp_queue[shop_id]

            except Exception:
                traceback.print_exc()

    def player_data_update_thread(self):
        temp_queue = {}
        # schema of object
        # "uuid": uuid,
        # "key": key,
        # "data": data
        while True:
            try:
                time.sleep(self.main.settings.batching.set_variable_batch_seconds)

                while not self.player_data_update_queue.empty():
                    set_variable_request_object = self.player_data_update_queue.get()
                    player_uuid = set_variable_request_object["uuid"]
                    key = set_variable_request_object["key"]
                    key = humps.camelize(key)
                    data = set_variable_request_object["data"]
                    if player_uuid not in temp_queue:
                        temp_queue[player_uuid] = {}
                    temp_queue[player_uuid][key] = data

                if len(temp_queue) == 0:
                    continue

                for player_uuid in list(temp_queue.keys()):
                    temp_queue[player_uuid] = humps.camelize(temp_queue[player_uuid])
                for player_uuid in list(temp_queue.keys()):
                    print("Pushed player data to database: " + player_uuid + " " + str(temp_queue[player_uuid]))
                    data = temp_queue[player_uuid]

                    # non data
                    unsetting = {}
                    for key in list(data.keys()):
                        if data[key] is None:
                            unsetting[key] = ""
                            del data[key]

                    unset_query = {}
                    if len(unsetting) != 0:
                        unset_query["$unset"] = unsetting

                    set_query = {}
                    if len(data) != 0:
                        set_query["$set"] = data

                    self.main.mongo["man10shop_v3"]["player_data"].update_one({
                        "uuid": player_uuid,
                    }, {**set_query, **unset_query}, upsert=True)
                    del temp_queue[player_uuid]

            except Exception:
                traceback.print_exc()

    # def get_shop_id_from_location(self, sign: Sign):
    #     if sign.location_id() in self.sign_cache:
    #         return self.sign_cache.get(sign.location_id())
    #     query = {"sign.signs." + str(sign.location_id()): {"$exists": True}}
    #     query = self.main.mongo["man10shop_v3"]["shops"].find_one(query, {"_id": 0, "shopId": 1})
    #     print("sign query:",query)
    #     if query is None:
    #         self.sign_cache[sign.location_id()] = None
    #         return None
    #     self.sign_cache[sign.location_id()] = query["shopId"]
    #     return self.sign_cache.get(sign.location_id())

    def get_shop_id_from_location(self, sign: Sign):
        query = {"sign.signs." + str(sign.location_id()): {"$exists": True}}
        query = self.main.mongo["man10shop_v3"]["shops"].find_one(query, {"_id": 0, "shopId": 1})
        if query is None:
            return None
        return query["shopId"]

    def get_shop(self, shop_id) -> Optional[Shop]:
        if shop_id in self.shops:
            shop = self.shops.get(shop_id)
            return shop
        shop_object = self.main.mongo["man10shop_v3"]["shops"].find_one({"shopId": shop_id})
        if shop_object is None:
            return None
        del shop_object["_id"]
        shop = self.create_shop_instance()
        shop.from_json(shop_object)
        self.shops[shop_id] = shop
        return self.shops.get(shop_id)

    def create_shop(self, owner: Player, shop_type: str, name: str, admin: bool) -> bool:
        try:
            shop = self.create_shop_instance()
            shop_id = str(uuid.uuid4())
            shop.from_json({
                "shopId": shop_id,
                "shopType": shop_type,
                "admin": admin,
            })
            shop.name_function.set_name(name)
            if owner is not None:
                shop.permission_function.set_permission(owner, "OWNER", False)
            data = shop.get_export_data()
            self.main.mongo["man10shop_v3"]["shops"].update_one({"shopId": shop.get_shop_id()},
                                                                {"$set": data}, upsert=True)
            return True
        except Exception:
            traceback.print_exc()
            return False

    def get_player_shops(self, player: Player):
        try:
            # result = []
            # for shop_id in self.shops.keys():
            #     shop = self.shops.get(shop_id)
            #     if shop.permission_function.has_permission(player, "ACCOUNTANT"):
            #         result.append(shop)
            # return result

            query = {"permission.users." + player.uuid.replace("-", ""): {"$exists": True}}
            query = self.main.mongo["man10shop_v3"]["shops"].find(query, {"_id": 0, "shopId": 1})
            query = [self.get_shop(x["shopId"]) for x in query]
            return [x for x in query if x is not None]
        except Exception:
            traceback.print_exc()
            return []

    def get_admin_shops(self):
        # result = []
        # for shop_id in self.shops.keys():
        #     shop = self.shops.get(shop_id)
        #     if shop.is_admin():
        #         result.append(shop)
        # return result
        try:
            query = {"admin": True}
            query = self.main.mongo["man10shop_v3"]["shops"].find(query, {"_id": 0, "shopId": 1})
        except Exception:
            traceback.print_exc()
            return []
        result = []
        for query_data in query:
            try:
                result.append(self.get_shop(query_data["shopId"]))
            except Exception:
                traceback.print_exc()
                continue

        return [x for x in result if x is not None]

    def http_request(self, endpoint: str, path: str, method: str = "POST", payload: dict = None,
                     return_json: bool = True):
        try:
            req = {}
            print("req endpoint", self.main.settings.api.endpoint.replace("{endpoint}", endpoint) + path)
            if method == "GET":
                req = requests.get(self.main.settings.api.endpoint.replace("{endpoint}", endpoint) + path,
                                   data=payload, headers={"Authorization": "Bearer " + self.main.settings.api.key},
                                   verify=False)
            if method == "POST":
                req = requests.post(self.main.settings.api.endpoint.replace("{endpoint}", endpoint) + path,
                                    data=payload, headers={"Authorization": "Bearer " + self.main.settings.api.key},
                                    verify=False)

            if req.status_code != 200:
                return None
            if return_json:
                return json.loads(req.text)
            else:
                return req.text
        except Exception as e:
            traceback.print_exc()
            return None

    def execute_command_in_server(self, endpoint, command, execute_async: bool = False, s_command: bool = True):
        if self.main.settings.communication_mode == "socket":
            result = self.main.man10_socket.send_message(endpoint, {"type": "sCommand" if s_command else "command", "command": command, "target": endpoint}, reply=True)
            if result is None:
                return None
            return result.get("data")
        def task():
            url = "scommand" if s_command else "exec"
            result = self.main.api.http_request(endpoint, "/server/" + url, "POST", {
                "command": command
            }, False)
            # print("executing command", command, "in server", endpoint, "result", result)
            return result

        if not execute_async:
            return task()
        else:
            self.threadpool.submit(task)

    def update_log(self, log_id: str, data: dict):
        try:
            self.main.mongo["man10shop_v3"]["trade_log"].update_one({"logId": log_id}, {"$set": humps.camelize(data)})
            return True
        except Exception:
            traceback.print_exc()
            return False

    def create_shop_instance(self) -> Shop:
        shop = deepcopy(self.base_shop_object)
        shop.api = self
        return shop

    def load_all_shops(self):
        start = datetime.datetime.now().timestamp()
        shops_query = self.main.mongo["man10shop_v3"]["shops"].find({})
        for shop in tqdm(shops_query):
            del shop["_id"]
            copy_shop: Shop = self.create_shop_instance()
            copy_shop.from_json(shop)
            self.shops[copy_shop.get_shop_id()] = copy_shop
        print("all shops loaded in ", datetime.datetime.now().timestamp() - start)

    def create_system_log(self, log_type: str, data: dict):
        try:
            data["logType"] = log_type
            data["datetime"] = datetime.datetime.now()
            self.main.mongo["man10shop_v3"]["system_log"].insert_one(data)
            return True
        except Exception:
            traceback.print_exc()
            return False
