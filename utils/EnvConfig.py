from __future__ import annotations

import os


def _load_env_file(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}

    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as env_file:
        for line_number, raw_line in enumerate(env_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[len("export "):].strip()

            if "=" not in line:
                raise ValueError(f"Invalid .env entry at line {line_number}: {raw_line.rstrip()}")

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
                value = value[1:-1]

            values[key] = value

    return values


def _require(config: dict[str, str], key: str) -> str:
    value = config.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required config: {key}")
    return value


def _get_int(config: dict[str, str], key: str, default: int) -> int:
    value = config.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _parse_hosts(value: str) -> list[dict]:
    hosts: list[dict] = []
    for host_entry in value.split(","):
        host_entry = host_entry.strip()
        if not host_entry:
            continue

        parts = [part.strip() for part in host_entry.split(":")]
        if len(parts) != 3:
            raise ValueError(
                "MAN10SOCKET_HOSTS must use comma-separated name:host:port entries"
            )

        name, host, port = parts
        hosts.append({
            "name": name,
            "host": host,
            "port": int(port),
        })

    if len(hosts) == 0:
        raise ValueError("MAN10SOCKET_HOSTS must contain at least one host entry")

    return hosts


def load_config(env_path: str = ".env") -> dict:
    file_values = _load_env_file(env_path)
    merged_values = {**file_values, **os.environ}

    return {
        "hostPort": _get_int(merged_values, "HOST_PORT", 8000),
        "mongodbConnectionString": _require(merged_values, "MONGODB_CONNECTION_STRING"),
        "communicationMode": merged_values.get("COMMUNICATION_MODE", "socket"),
        "man10socket": {
            "replyStateTtlSeconds": _get_int(merged_values, "MAN10SOCKET_REPLY_STATE_TTL_SECONDS", 30),
            "defaultReplyTimeoutSeconds": _get_int(merged_values, "MAN10SOCKET_DEFAULT_REPLY_TIMEOUT_SECONDS", 5),
            "framingProtocol": merged_values.get("MAN10SOCKET_FRAMING_PROTOCOL", "delimiter_v1"),
            "maxFrameBytes": _get_int(merged_values, "MAN10SOCKET_MAX_FRAME_BYTES", 1024 * 1024),
            "hosts": _parse_hosts(_require(merged_values, "MAN10SOCKET_HOSTS")),
        },
        "queue": {
            "size": _get_int(merged_values, "QUEUE_SIZE", 8),
            "rateLimit": _get_int(merged_values, "QUEUE_RATE_LIMIT", 0),
        },
        "batching": {
            "setVariableBatchSeconds": _get_int(merged_values, "BATCHING_SET_VARIABLE_BATCH_SECONDS", 1),
        },
        "api": {
            "endpoint": merged_values.get("API_ENDPOINT", "https://{endpoint}"),
            "key": merged_values.get("API_KEY", "replace_me"),
        },
        "defaultVariables": {
            "storage": {
                "storageSizeMax": _get_int(merged_values, "DEFAULT_STORAGE_SIZE_MAX", 3456),
                "storageSlotPrice": _get_int(merged_values, "DEFAULT_STORAGE_SLOT_PRICE", 100),
            }
        },
    }
