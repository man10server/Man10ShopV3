from __future__ import annotations

from typing import TYPE_CHECKING

from Man10Socket.data_class.Item import Item
from Man10Socket.utils.gui_manager.GUI import GUI
from Man10Socket.utils.gui_manager.GUIClickEvent import GUIClickEvent

if TYPE_CHECKING:
    from Man10ShopV3.data_class.Shop import Shop


class BuyAndSellActionMenu(GUI):

    def __init__(self, shop: Shop):
        super().__init__(6)
        self.shop: Shop = shop
        self.set_title("§e§ltest")
        self.fill(Item(material="BLUE_STAINED_GLASS_PANE"))

        button_material = "LIME_STAINED_GLASS_PANE"
        if self.shop.get_shop_type() == "SELL":
            button_material = "RED_STAINED_GLASS_PANE"

        @self.icon(slots=[30, 31, 32, 39, 40, 41, 48, 49, 50], item=Item(material=button_material))
        def on_click(event: GUIClickEvent):
            self.shop.api.main.main_queue.put({
                "shopId": self.shop.get_shop_id(),

            })

        target_item = self.shop.target_item_function.get_target_item()
        self.target_item = Item()
        if target_item is None:
            self.target_item.set_material("BARRIER").set_display_name("§c商品未設定")
        else:
            self.target_item.set_type_base64(target_item.type_base64)
        self.set_item(self.target_item, [13])

        # right
        right_icon = (Item(material="ARROW")
                      .set_display_name("§a§l取引数を増やす")
                      .set_lore(["§f左クリックで取引数1増加", "§fシフト+左クリックで取引数を最大まで増加"])
                      )
        # @self.icon(slots=[42], item=right_icon)
        # def on_click(event: GUIClickEvent):
        #     if event.click_type == "LEFT":
        #         self.set_item(self.target_item, [13])
        #     elif event.click_type == "SHIFT_LEFT":
        #         self.shop.set_trade_amount(self.shop.get_max_trade_amount())
