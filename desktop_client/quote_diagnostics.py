"""Operator-approved quote diagnostics, without credentials or drawing files."""

from collections import deque
from datetime import datetime, timezone
import json
import re
from urllib import request
from urllib.parse import urlsplit, urlunsplit


MAX_EVENTS = 200
MAX_REPORT_BYTES = 4 * 1024 * 1024
ITEM_FIELDS = (
    "name", "product_family", "product_code", "model_code", "specification",
    "width_mm", "height_mm", "depth_mm", "quantity", "material_code",
    "coating_type", "display_color", "formula_discount", "quick_discount",
    "freight_fee", "final_remark", "formula", "quick", "quote_display",
    "attachments", "auxiliary_detail", "cost_detail_rows", "ganged_cabinets",
    "ganged_cabinet_count", "scheme2_cost_settings",
)
FORBIDDEN_KEYS = (
    "password", "secret", "token", "api_key", "authorization", "database_url",
    "source_path", "file_path", "local_path", "source_pdf_name", "drawing_context",
    "image_data", "raw_pdf", "pdf_bytes", "base64",
)


def _safe(value, depth=0):
    if depth > 10:
        return "[层级已截断]"
    if isinstance(value, dict):
        return {
            str(key)[:80]: _safe(item, depth + 1)
            for key, item in list(value.items())[:300]
            if not any(marker in str(key).lower() for marker in FORBIDDEN_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item, depth + 1) for item in value[:500]]
    if isinstance(value, str):
        value = re.sub(r"(?i)\b(api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+",
                       r"\1=[已隐藏]", value)
        value = re.sub(r"(?<!\w)[a-zA-Z]:[\\/][^\s\"'，；,;]+", "[本地路径已隐藏]", value)
        if re.match(r"^[a-zA-Z]:[\\/]|^\\\\|^/(?:home|Users|tmp)/", value):
            return "[本地路径已隐藏]"
        return value[:1000]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:1000]


def record_event(window, action, **details):
    history = getattr(window, "_diagnostic_events", None)
    if history is None:
        history = deque(maxlen=MAX_EVENTS)
        window._diagnostic_events = history
    history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "action": str(action)[:80],
        "details": _safe(details),
    })


def build_report(window, items, *, client_version=""):
    """Freeze exactly the current quote state; avoid credentials and file paths."""
    safe_items = [
        _safe({key: item[key] for key in ITEM_FIELDS if key in item})
        for item in items if isinstance(item, dict)
    ]
    current = {
        "product_code": getattr(getattr(window, "product_combo", None), "currentData", lambda: None)(),
        "specification": getattr(getattr(window, "quote_spec_edit", None), "text", lambda: "")(),
        "quantity": getattr(getattr(window, "quantity_spin", None), "value", lambda: None)(),
        "material": getattr(getattr(window, "material_combo", None), "currentText", lambda: "")(),
    }
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "client_version": str(client_version)[:80],
        "order_number": getattr(getattr(window, "scheme2_order_number", None), "text", lambda: "")()[:100],
        "company_name": getattr(getattr(window, "scheme2_company", None), "currentText", lambda: "")()[:200],
        "current_selection": _safe(current),
        "quote_items": safe_items,
        "events": list(getattr(window, "_diagnostic_events", []))[-MAX_EVENTS:],
        "last_request_id": str(getattr(window, "_quote_progress_request_id", ""))[:64],
    }
    data = json.dumps(report, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("诊断报告超过 4 MB，请减少报价清单行数后重试。")
    return report


def diagnostic_endpoint(api_url):
    url = urlsplit(str(api_url))
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")):
        raise ValueError("诊断报告只能提交至 HTTPS 或本机 API。")
    if not url.netloc:
        raise ValueError("报价 API 地址无效。")
    return urlunsplit((url.scheme, url.netloc, "/api/diagnostics/reports", "", ""))


def submit_report(api_url, headers, report, timeout=30):
    payload = json.dumps({"confirmed_by_operator": True, "report": report},
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("诊断报告超过 4 MB。")
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update({key: value for key, value in headers.items()
                            if key.lower() == "x-ai-quote-key"})
    operation = request.Request(diagnostic_endpoint(api_url), data=payload,
                                headers=request_headers, method="POST")
    with request.urlopen(operation, timeout=timeout) as response:
        result = json.load(response)
    if not result.get("submitted") or not result.get("report_id"):
        raise ValueError("服务器未返回诊断报告编号。")
    return str(result["report_id"])
