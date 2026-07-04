import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def send_payment_order_to_bank(payload: dict) -> tuple[bool, str, str]:
    """
    Отправка платежного поручения в банк.
    Возвращает: (успех, внешний_id, текст_ответа)
    """
    endpoint = (os.getenv("BANK_PAYMENT_API_URL") or "").strip()
    token = (os.getenv("BANK_PAYMENT_API_TOKEN") or "").strip()
    if not endpoint:
        return False, "", "Интеграция с банком не настроена: отсутствует BANK_PAYMENT_API_URL."

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            operation_id = str(data.get("operation_id") or data.get("id") or "").strip()
            return True, operation_id, raw[:2000]
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return False, "", f"HTTP {exc.code}: {text[:1800]}"
    except URLError as exc:
        return False, "", f"Ошибка соединения с банком: {exc.reason}"
    except Exception as exc:
        return False, "", f"Ошибка отправки в банк: {exc}"
