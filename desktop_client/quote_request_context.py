"""One immutable client-side request guard for ordinary and ganged quotes."""
from copy import deepcopy
import json
import logging
from uuid import uuid4

LOGGER = logging.getLogger("ai_quote.client")


def attachment_inputs(window):
    # Include manual costs, prices and custom rows, not just catalogue IDs.
    return json.dumps(getattr(window, "attachments", []), sort_keys=True, default=str)


def calculation_environment(window):
    values = {}
    for name in ("cabinet_body_thickness_spin", "waste_factor_spin", "quantity_spin", "labor_multiplier"):
        control = getattr(window, name, None)
        if control is not None:
            values[name] = control.value()
    quote_date = getattr(window, "quote_date", None)
    if quote_date is not None:
        values["quote_date"] = quote_date.date().toString("yyyy-MM-dd")
    return values


def quote_signature(window):
    builder = getattr(window, "quote_input_signature", None)
    if callable(builder):
        return builder()
    # The source-only MainWindow predates the recovered core signature API.
    values = {}
    for name, accessor in (("model_edit", "text"), ("quote_spec_edit", "text"),
                           ("material_combo", "currentData"), ("coating_combo", "currentData"),
                           ("width_spin", "value"), ("height_spin", "value"), ("depth_spin", "value"),
                           ("freight_spin", "value")):
        control = getattr(window, name, None)
        if control is not None:
            values[name] = getattr(control, accessor)()
    for name in ("selected_product_code", "selected_variant_code", "door_counts"):
        method = getattr(window, name, None)
        if callable(method):
            values[name] = method()
    values["ganged_cabinets"] = getattr(window, "ganged_cabinets", [])
    return json.dumps(values, sort_keys=True, default=str)


def bind_quote_request(window, worker, quote_id, expects_v2=False):
    signature = quote_signature(window)
    context = {
        "token": uuid4().hex, "quote_id": quote_id,
        "epoch": getattr(window, "_scheme2_calculation_epoch", 0),
        "signature": signature, "attachments": attachment_inputs(window),
        "environment": calculation_environment(window),
        "custom_rows": deepcopy([row for row in getattr(window, "attachments", []) if row.get("custom")]),
        "expects_v2": expects_v2, "state": "pending",
    }
    window._quote_request_context = context
    worker._client_request_token = context["token"]
    window.pending_quote_signature = signature
    # Retire the old, ordinary-only guards. Neither mode may inherit them.
    window._v2_request_environment = None
    window._v2_request_quote_id = None
    window._v2_custom_attachments = deepcopy(context["custom_rows"])
    window._v2_preview_generation = getattr(window, "_v2_preview_generation", 0) + 1
    timer = getattr(window, "_v2_environment_timer", None)
    if timer is not None:
        timer.stop()
    LOGGER.info("quote guard bound quote_id=%s token=%s epoch=%s", quote_id, context["token"], context["epoch"])
    return context


def stamp_quote_response(worker, result):
    token = getattr(worker, "_client_request_token", None)
    if token is not None:
        result["_client_request_token"] = token
    return result


def quote_request_is_current(window, worker):
    token = getattr(worker, "_client_request_token", None)
    if token is None:
        return True
    context = getattr(window, "_quote_request_context", None)
    return bool(context and token == context["token"]
                and context["epoch"] == getattr(window, "_scheme2_calculation_epoch", 0))


def check_quote_response(window, result):
    """Return (current request, rejection reason); stale replies stay silent."""
    context = getattr(window, "_quote_request_context", None)
    if not context:
        return result.get("_client_request_token") is None, None
    token = result.get("_client_request_token")
    if (token is not None and token != context["token"]) or context["epoch"] != getattr(window, "_scheme2_calculation_epoch", 0):
        return False, None
    if result.get("quote_id") != context["quote_id"]:
        if token is None:
            return False, None
        return True, "报价返回编号与本次请求不一致，请重试。"
    if context["expects_v2"] and result.get("attachment_contract") != 2:
        return True, "报价未返回完整附件快照，请更新服务后重试。"
    if (quote_signature(window) != context["signature"]
            or attachment_inputs(window) != context["attachments"]
            or calculation_environment(window) != context["environment"]):
        return True, "计算期间配置或附件已变化，本次结果未采用；请重新加入报价。"
    return True, None


def settle_quote_request(window, state):
    context = getattr(window, "_quote_request_context", None)
    if context:
        context["state"] = state
        LOGGER.info("quote guard settled quote_id=%s token=%s state=%s", context["quote_id"], context["token"], state)


def retire_quote_request(window):
    window._quote_request_context = None
    window._v2_request_environment = None
    window._v2_request_quote_id = None
    window._v2_preview_generation = getattr(window, "_v2_preview_generation", 0) + 1
    timer = getattr(window, "_v2_environment_timer", None)
    if timer is not None:
        timer.stop()
