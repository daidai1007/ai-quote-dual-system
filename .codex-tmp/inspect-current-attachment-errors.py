"""Read-only, restricted diagnostic of recent local quotation recovery files."""
import gzip
import json
from pathlib import Path

FIELDS = ("item_name", "attachment_price_id", "status", "error", "pending_manual_error",
          "pending_manual_dimensions", "manual_inputs", "quote_line_id")


def inspect(value, path):
    if isinstance(value, dict):
        if ("attachment_price_id" in value or "item_name" in value) and (
            value.get("status") in ("ERROR", "PENDING_MANUAL")
            or value.get("error") or value.get("pending_manual_error")
        ):
            print(path, json.dumps({key: value[key] for key in FIELDS if key in value}, ensure_ascii=False))
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                inspect(child, path + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect(child, path + "[" + str(index) + "]")


root = Path(r"C:\Users\Administrator\AppData\Local\AIQuoteDualSystem\projects")
for path in sorted(root.glob("recovery-*.aiquote"), key=lambda file: file.stat().st_mtime, reverse=True)[:3]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    print("FILE", path.name, "SAVED", data.get("saved_at"))
    print("state collections", [(key, len(value)) for key, value in data.get("state", {}).items()
                               if isinstance(value, (dict, list))])
    inspect(data, "root")
