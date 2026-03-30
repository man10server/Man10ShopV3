from typing import Optional


class ItemStack(object):

    def __init__(self):
        self.type_base64: Optional[str] = None
        self.type_md5: Optional[str] = None
        self.amount: int = 1
        self.display_name: Optional[str] = None
        self.lore: list = []
        self.material: Optional[str] = None
        self.custom_model_data: Optional[int] = None

    def from_json(self, data: dict):
        if data is None:
            return self
        self.type_base64 = data.get("type_base64")
        self.type_md5 = data.get("type_md5")
        self.amount = data.get("amount")
        self.display_name = data.get("display_name")
        self.lore = data.get("lore")
        self.material = data.get("material")
        self.custom_model_data = data.get("custom_model_data")

        return self

    def is_configured(self) -> bool:
        return self.type_base64 is not None

    def get_json(self):
        return {
            "type_base64": self.type_base64,
            "type_md5": self.type_md5,
            "amount": self.amount,
            "display_name": self.display_name,
            "lore": self.lore,
            "material": self.material,
            "custom_model_data": self.custom_model_data
        }

    def get_icon_json(self):
        return {
            "material": self.material,
            "custom_model_data": self.custom_model_data
        }
