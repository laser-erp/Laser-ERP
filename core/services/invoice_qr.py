import base64
from io import BytesIO
from urllib.parse import quote_plus

import qrcode


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _sum_in_kopecks(amount) -> str:
    try:
        # Формат QR для банков: сумма в копейках целым числом
        return str(int((amount or 0) * 100))
    except Exception:
        return "0"


def build_russian_payment_qr_payload(invoice) -> str:
    """
    Формирует payload для банковского QR (СТ00012) по счету.
    """
    org = invoice.our_organization
    if not org:
        return ""
    name = _clean(getattr(org, "name", ""))
    acc = _clean(getattr(org, "bank_account", ""))
    bank_name = _clean(getattr(org, "bank_name", ""))
    bik = _clean(getattr(org, "bank_bik", ""))
    corr = _clean(getattr(org, "bank_corr_account", ""))
    inn = _clean(getattr(org, "inn", ""))
    kpp = _clean(getattr(org, "kpp", ""))
    purpose = _clean(getattr(invoice, "purpose", "")) or f"Оплата по счету {invoice.number}"
    if not (name and acc and bank_name and bik):
        return ""

    fields: list[str] = [
        "ST00012",
        f"Name={name}",
        f"PersonalAcc={acc}",
        f"BankName={bank_name}",
        f"BIC={bik}",
        f"PayeeINN={inn}",
        f"Purpose={purpose}",
        f"Sum={_sum_in_kopecks(invoice.amount)}",
    ]
    if corr:
        fields.append(f"CorrespAcc={corr}")
    if kpp:
        fields.append(f"KPP={kpp}")
    return "|".join(fields)


def build_russian_payment_qr_data_url(invoice) -> tuple[str, str]:
    """
    Возвращает (payload, data_url PNG).
    """
    payload = build_russian_payment_qr_payload(invoice)
    if not payload:
        return "", ""

    img = qrcode.make(payload)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return payload, f"data:image/png;base64,{b64}"


def payment_qr_debug_link(payload: str) -> str:
    if not payload:
        return ""
    return "https://example.invalid/qr?data=" + quote_plus(payload)
