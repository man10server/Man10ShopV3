from __future__ import annotations

from fastapi import Request
import traceback
from typing import TYPE_CHECKING, Optional

from Man10ShopV3.data_class.Player import Player

if TYPE_CHECKING:
    from Man10ShopV3.methods.shop import ShopMethods


class PublicListShopsMethod:

    def __init__(self, methods: ShopMethods):
        self.methods = methods

        @self.methods.main.app.get("/public/shop/list")
        async def shop_list(request: Request):
            try:
                user_id_header = request.headers.get("x-user-id")
                if user_id_header is None:
                    return self.methods.response_object("post_body_invalid", "header: x-user-id is missing")

                player = Player().load_from_json({
                    "uuid": user_id_header
                }, self.methods.main)
                shops = self.methods.main.api.get_player_shops(player)

                results = []
                for shop in shops:
                    target_item = shop.target_item_function.get_target_item()
                    permission = shop.permission_function.get_permission(player)
                    if shop.delete_function.is_deleted(): continue
                    if permission is None:
                        permission = "ERROR"
                    if permission == "ALLOWED_TO_USE" or permission == "IS_BANNED":
                        continue
                    results.append({
                        "shopId": shop.get_shop_id(),
                        "name": shop.name_function.get_name(),
                        "shopType": shop.get_shop_type_string(),
                        "icon": target_item.get_icon_json() if target_item is not None else None,
                        "permission": permission,
                        "money": shop.money_function.get_money(),
                        "itemCount": shop.storage_function.get_item_count(),
                        "category": shop.category_function.get_category()
                    })
                results = sorted(results, key=lambda x: x["category"] + "-" + x["name"], reverse=False)
                return self.methods.response_object("success", results)
            except Exception as e:
                traceback.print_exc()
                return self.methods.response_object("error_internal", {"message": str(e)})
