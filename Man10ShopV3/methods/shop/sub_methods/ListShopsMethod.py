from __future__ import annotations

import json
import traceback
from typing import TYPE_CHECKING, Optional

import humps
from pydantic import BaseModel

from Man10ShopV3.data_class.Player import Player
from Man10ShopV3.common_variables.common_variables import player_schema, PlayerBaseModel
from utils.JsonSchemaWrapper import flask_json_schema
from utils.MatResponseWrapper import flask_mat_response_wrapper

if TYPE_CHECKING:
    from Man10ShopV3.methods.shop import ShopMethods


class ListShopsRequest(BaseModel):
    player: PlayerBaseModel
    admin: Optional[bool] = False
    searchQuery: Optional[str] = None


class ListShopsMethod:

    def __init__(self, methods: ShopMethods):
        self.methods = methods
        self.methods.main.man10_socket.custom_request.register_route("/shop/list", self.socket_route)

        @self.methods.main.app.post("/shop/list")
        async def shop_list(request: ListShopsRequest, lang: Optional[str] = "jp"):
            return self.shop_list(request, lang)

    def shop_list(self, request: ListShopsRequest, lang: Optional[str] = "jp"):
        try:

            request.player = humps.decamelize(request.player.dict())

            player = Player().load_from_json(request.player, self.methods.main)
            shops = self.methods.main.api.get_player_shops(player)

            if request.admin:
                shops = self.methods.main.api.get_admin_shops()

            results = []
            for shop in shops:
                target_item = shop.target_item_function.get_target_item()
                permission = shop.permission_function.get_permission(player)
                if shop.delete_function.is_deleted(): continue
                if permission is None:
                    permission = "ERROR"
                if permission == "ALLOWED_TO_USE" or permission == "IS_BANNED":
                    continue
                if request.searchQuery is not None:
                    if request.searchQuery not in shop.name_function.get_name() and request.searchQuery not in shop.category_function.get_category():
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

    def socket_route(self, data: dict):
        # convert dict to ShopInformationRequest
        request_data = ListShopsRequest(**data["data"])
        result = self.shop_list(request_data)
        result = json.loads(result.body)
        return result["status"], result["data"]
