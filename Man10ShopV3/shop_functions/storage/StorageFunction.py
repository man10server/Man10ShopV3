from typing import Optional

from Man10ShopV3.data_class.OrderRequest import OrderRequest
from Man10ShopV3.data_class.Player import Player
from Man10ShopV3.data_class.ShopFunction import ShopFunction


class StorageFunction(ShopFunction):
    allowed_shop_type = ["BUY", "SELL"]

    def __init__(self):
        super().__init__()
        self.users_in_storage = False

    def on_function_init(self):
        self.set_variable("storage_size", 64 * 9)
        self.set_variable("item_count", 0)

        # self.shop.register_queue_callback("storage.item.deposit", self.deposit_item)
        # self.shop.register_queue_callback("storage.item.withdraw", self.withdraw_item)
        self.shop.register_queue_callback("storage.buy", self.buy_storage)


        self.shop.register_queue_callback("storage.menu.open", self.open_menu)
        self.shop.register_queue_callback("storage.menu.close", self.close_menu)

        self.set_dynamic_variable("storage_size_max", self.get_storage_max_size())
        self.set_dynamic_variable("storage_slot_price", self.get_storage_slot_price())

    def get_storage_size(self):
        return self.get("storage_size")

    def get_item_count(self):
        return self.get("item_count")

    def get_storage_max_size(self):
        return self.shop.api.main.settings.storage_defaults.storage_size_max

    def get_storage_slot_price(self):
        return self.shop.api.main.settings.storage_defaults.storage_slot_price

    def set_item_count(self, amount: int):
        return self.set("item_count", amount)

    def add_item_count(self, amount: int):
        return self.set_item_count(self.get_item_count() + amount)

    def remove_item_count(self, amount: int):
        return self.set_item_count(self.get_item_count() - amount)

    # =========

    def open_menu(self, data): # withdraw: True
        if "player" not in data: return
        if "withdraw" not in data["data"]: return
        player: Player = data["player"]
        if self.users_in_storage:
            player.warn_message("別のプレイヤーが倉庫編集中です")
            return
        self.users_in_storage = True

        display_item_count = self.get_item_count() if data["data"]["withdraw"] else 0
        if display_item_count > 3456:
            display_item_count = 3456
        if display_item_count < 0:
            display_item_count = 0

        player.execute_command_in_server("mshop storageOpen " + self.shop.get_shop_id() + " " + player.uuid + " " + str(display_item_count), s_command=False)

    def close_menu(self, data): #amount
        if "player" not in data: return
        if "amount" not in data["data"]: return
        if not self.users_in_storage: return
        player: Player = data["player"]
        amount = data["data"]["amount"]
        if amount <= 0:
            self.remove_item_count(abs(amount))
            player.success_message("アイテムを" + str(abs(amount)) + "個取り出しました")
        else:
            self.add_item_count(amount)
            player.success_message("アイテムを" + str(amount) + "個しまいました")

        action_type: str = "withdraw" if amount <= 0 else "deposit"

        self.shop.api.create_system_log("storage." + action_type, {
            "shopId": self.shop.get_shop_id(),
            "player": player.get_json(),
            "amount": abs(amount),
            "newItemCount": self.get_item_count(),
            "isWithdraw": amount <= 0,
            "oldItemCount": self.get_item_count() - amount,
        })

        self.users_in_storage = False

    def buy_storage(self, data):
        if "amount" not in data["data"]: return
        if "player" not in data: return
        player: Player = data["player"]
        buying_units = data["data"]["amount"]
        if buying_units + self.get_storage_size() > self.get_storage_max_size():
            buying_units = self.get_storage_max_size() - self.get_storage_size()
        total_price = buying_units * self.get_storage_slot_price()
        request_take_money = player.take_money(total_price)
        if not request_take_money.success():
            player.warn_message(request_take_money.message())
            return
        self.set("storage_size", self.get_storage_size() + buying_units)
        player.success_message("ストレージを購入しました 現在:" + str(self.get_storage_size()) + "個")

    # =========

    def item_count(self, order: OrderRequest) -> Optional[int]:
        if self.shop.is_admin(): return None
        if self.shop.get_shop_type() == "BUY":
            return self.get_item_count()
        if self.shop.get_shop_type() == "SELL":
            storage_size = self.get_storage_size() - self.get_item_count()
            if storage_size < 0: storage_size = 0
            return storage_size
        return self.get_storage_size()

    def is_allowed_to_use_shop(self, order: OrderRequest) -> bool:
        if self.users_in_storage:
            order.player.warn_message("倉庫編集中です")
            return False
        if self.shop.get_shop_type() == "SELL":
            if order.amount + self.get_item_count() >= self.get_storage_size() and not self.shop.is_admin():
                order.player.warn_message("ショップの倉庫がいっぱいです")
                return False

        if self.shop.get_shop_type() == "BUY":
            if order.amount > self.get_item_count() and not self.shop.is_admin():
                order.player.warn_message("在庫がありません")
                return False
        return True
