// Pure formatter exported for regression tests. Dots are Argentine thousands.
export function formatMoneyEdit(raw, caret = raw.length) {
    const prefix = raw.match(/^\s*(?:US\$|ARS|USD|\$)?\s*/i)[0];
    raw = raw.slice(prefix.length);
    caret = Math.max(0, caret - prefix.length);
    if (/[^\d.,\s]/.test(raw) || (raw.match(/,/g) || []).length > 1) {
        return {text: raw, caret, valid: false, error: "Ingresá un importe sin signo, usando coma para los decimales."};
    }
    const comma = raw.indexOf(",");
    const integerRaw = (comma < 0 ? raw : raw.slice(0, comma)).replace(/\D/g, "");
    const integer = integerRaw.replace(/^0+(?=\d)/, "") || (comma >= 0 ? "0" : "");
    const removedZeros = integerRaw.length - integer.length;
    const decimal = comma < 0 ? "" : raw.slice(comma + 1).replace(/\D/g, "").slice(0, 2);
    const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const text = grouped + (comma < 0 ? "" : "," + decimal);
    let nextCaret;
    if (comma >= 0 && caret > comma) {
        nextCaret = grouped.length + 1 + Math.min(2, raw.slice(comma + 1, caret).replace(/\D/g, "").length);
    } else {
        const before = Math.max(0, raw.slice(0, caret).replace(/\D/g, "").length - Math.max(0, removedZeros));
        nextCaret = 0;
        let seen = 0;
        while (nextCaret < grouped.length && seen < before) {
            if (/\d/.test(grouped[nextCaret])) seen++;
            nextCaret++;
        }
    }
    const cents = BigInt(integer || "0") * 100n + BigInt(decimal.padEnd(2, "0") || "0");
    // Conservative cents bound: converting to the domain's float cannot erase
    // a cent (Number.MAX_SAFE_INTEGER cents would not provide that guarantee).
    if (cents > 4503599627370495n) {
        return {text, caret:nextCaret, valid:false, error:"El importe es demasiado grande. Ingresá uno menor para conservar su precisión."};
    }
    return {text, caret:nextCaret, valid:true, error:""};
}

export default function(component) {
    const {parentElement, data, setStateValue} = component;
    const input = parentElement.querySelector("input");
    const label = parentElement.querySelector("label");
    const error = parentElement.querySelector("#money-error");
    label.textContent = data.label;
    parentElement.querySelector("#money-help").textContent = "Ejemplo: 1.234.567,89 · Hasta dos decimales";
    // Python is authoritative after saving/discarding/navigation. On ordinary
    // typing there is no server event, so the element and caret stay untouched.
    input.value = data.value ?? "";
    error.textContent = data.error ?? "";
    input.setAttribute("aria-invalid", String(Boolean(data.error)));
    let lastCommitted = data.value ?? "";
    let composing = false;
    const apply = () => {
        const result = formatMoneyEdit(input.value, input.selectionStart ?? input.value.length);
        input.value = result.text;
        input.setSelectionRange(result.caret, result.caret);
        input.setAttribute("aria-invalid", String(!result.valid));
        error.textContent = result.error;
        return result;
    };
    const commit = () => {
        if (composing) return;
        const result = apply();
        if (result.text !== lastCommitted) {
            lastCommitted = result.text;
            setStateValue("value", result.text);
        }
    };
    input.onbeforeinput = (event) => {
        const start = input.selectionStart, end = input.selectionEnd;
        // Removing an automatic thousands dot must remove the adjacent digit,
        // rather than restoring the dot and making Backspace appear broken.
        if (start === end && event.inputType === "deleteContentBackward" && start > 0 && input.value[start - 1] === ".") {
            event.preventDefault();
            input.setRangeText("", Math.max(0, start - 2), start, "end");
            apply();
        } else if (start === end && event.inputType === "deleteContentForward" && input.value[start] === ".") {
            event.preventDefault();
            input.setRangeText("", start, start + 2, "end");
            apply();
        } else if (event.inputType === "insertText" && event.data === "." && !input.value.includes(",")) {
            // Decimal keys on some mobile keyboards emit '.' despite inputmode.
            event.preventDefault();
            input.setRangeText(",", start, end, "end");
            apply();
        }
    };
    input.oninput = () => { if (!composing) apply(); };
    input.oncompositionstart = () => { composing = true; };
    input.oncompositionend = () => { composing = false; apply(); };
    input.onblur = commit;
    input.onkeydown = (event) => {
        if (event.key === "Enter") { event.preventDefault(); commit(); }
    };
    return () => {
        input.oninput = input.onblur = input.onkeydown = input.onbeforeinput = null;
        input.oncompositionstart = input.oncompositionend = null;
    };
}
