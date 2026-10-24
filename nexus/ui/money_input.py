"""Local monetary input: client-side formatting and numeric session state."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
from math import isfinite
import re

import streamlit as st
from streamlit.components.v2 import component


ASSETS = Path(__file__).with_name("money_input_assets")
# Below 2**52 cents, float spacing in currency units remains below one cent.
# The domain contract is float, so use this conservative bound on both sides.
MAX_SAFE_CENTS = 4503599627370495


def parse_money(text):
    """Validate the component's Argentine amount; never turn a negative positive."""
    if text is None or text == "":
        return None
    if not isinstance(text, str):
        raise ValueError("El importe debe ser texto en formato argentino.")
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{0,2})?", text):
        raise ValueError("Ingresá un importe válido, sin signo y con hasta dos decimales.")
    try:
        amount = Decimal(text.replace(".", "").replace(",", "."))
        if amount * 100 > MAX_SAFE_CENTS:
            raise ValueError("El importe excede la precisión admitida.")
        value = float(amount)
        if not isfinite(value):
            raise ValueError("Ingresá un importe finito.")
        return value
    except InvalidOperation as exc:
        raise ValueError("Ingresá un importe válido.") from exc


def format_money(value):
    if value is None:
        return ""
    return f"{value:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")


_money_component = component(
    "nexus_money_input",
    html='<div class="money-field"><label for="money-amount"></label><input id="money-amount" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" aria-describedby="money-help money-error" /><div id="money-help"></div><div id="money-error" role="status" aria-live="polite"></div></div>',
    css=(ASSETS / "money_input.css").read_text(encoding="utf-8"),
    js=(ASSETS / "money_input.js").read_text(encoding="utf-8"),
)


def money_input(label, *, key, on_change):
    """Commit on blur/Enter, before subsequent Streamlit actions are sent.

    ``key`` remains a float/None, separate from the component's wire state.
    Client edits don't rerun Python or interrupt the caret on each keystroke.
    """
    component_key = f"{key}_money_control"

    def commit():
        payload = st.session_state.get(component_key, {})
        try:
            st.session_state[key] = parse_money(payload.get("value"))
            st.session_state[f"{key}_money_error"] = ""
        except ValueError as exc:
            st.session_state[key] = None
            st.session_state[f"{key}_money_error"] = str(exc)
        st.session_state[f"{key}_money_raw"] = payload.get("value", "")
        on_change()

    value = st.session_state.get(key)
    error = st.session_state.get(f"{key}_money_error", "") if value is None else ""
    display = st.session_state.get(f"{key}_money_raw", "") if error else format_money(value)
    _money_component(
        key=component_key,
        data={"label": label, "value": display, "error": error},
        default={"value": format_money(value)},
        on_value_change=commit,
    )
    return value
