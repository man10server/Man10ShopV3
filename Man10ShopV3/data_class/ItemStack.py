class ItemStack(object):
    type_base64: str = "H4sIAAAAAAAA/+NiYGBm4HZJLEkMSy0qzszPY2AQjOBgYMpMYRDNzcxLTS5KTCuxSi9KLC6OT8rJT85mZmBNzi/NK2FgYGBkAADK/sACPgAAAA=="
    type_md5: str = "adf495fbdab533b8454f40aae0e0d390"
    amount: int = 1
    display_name: str = None
    lore: list = []
    material: str = "GRASS_BLOCK"
    custom_model_data = int = -1

    def from_json(self, data: dict):
        self.type_base64 = data.get("type_base64")
        self.type_md5 = data.get("type_md5")
        self.amount = data.get("amount")
        self.display_name = data.get("display_name")
        self.lore = data.get("lore")
        self.material = data.get("material")
        self.custom_model_data = data.get("custom_model_data")

        return self

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
