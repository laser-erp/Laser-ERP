import json
from html import unescape
from urllib.parse import urlencode
from urllib.request import urlopen
import xml.etree.ElementTree as ET


CBR_BIK_XML_URL = "https://www.cbr.ru/scripts/XML_bic.asp"
BIK_INFO_JSON_URL = "https://bik-info.ru/api.html"


def _normalized_bik(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def fetch_bank_details_by_bik(bik: str) -> dict:
    """
    Возвращает реквизиты банка по БИК из справочника ЦБ РФ.
    Результат: {"bank_name": str, "corr_account": str}
    """
    bik_digits = _normalized_bik(bik)
    if len(bik_digits) != 9:
        raise ValueError("БИК должен содержать 9 цифр.")

    # 1) Пытаемся получить полные реквизиты из открытого справочника bik-info.
    try:
        api_url = f"{BIK_INFO_JSON_URL}?{urlencode({'type': 'json', 'bik': bik_digits})}"
        with urlopen(api_url, timeout=15) as resp:
            raw = resp.read()
        parsed = None
        for enc in ("utf-8", "cp1251"):
            try:
                parsed = json.loads(raw.decode(enc))
                break
            except Exception:
                continue
        if isinstance(parsed, dict) and parsed.get("bik"):
            bank_name = unescape((parsed.get("name") or parsed.get("namemini") or "").strip())
            corr_account = (parsed.get("ks") or "").strip()
            if bank_name or corr_account:
                return {
                    "bank_name": bank_name,
                    "corr_account": corr_account,
                }
    except Exception:
        # Тихий fallback на ЦБ.
        pass

    # 2) Fallback на XML ЦБ РФ.
    url = f"{CBR_BIK_XML_URL}?{urlencode({'bic': bik_digits})}"
    try:
        with urlopen(url, timeout=15) as resp:
            raw = resp.read()
    except Exception as exc:
        raise ValueError(f"Не удалось получить данные по БИК: {exc}") from exc

    try:
        root = ET.fromstring(raw)
    except Exception as exc:
        raise ValueError("Сервис БИК вернул некорректный ответ.") from exc

    record = root.find(".//Record")
    if record is None:
        raise ValueError("По указанному БИК ничего не найдено.")

    bank_name = (
        (record.attrib.get("NameP") or "")
        or (record.attrib.get("ShortName") or "")
        or (record.attrib.get("ParticipantName") or "")
    ).strip()
    if not bank_name:
        bank_name = "Банк по БИК"

    corr_account = (
        (record.attrib.get("Account") or "")
        or (record.attrib.get("CorrAccount") or "")
        or (record.attrib.get("CorrespAcc") or "")
    ).strip()

    # В некоторых ответах коррсчет может лежать в дочерних узлах.
    if not corr_account:
        for tag_name in ("Account", "CorrAccount", "CorrespAcc"):
            node = record.find(f".//{tag_name}")
            if node is not None:
                corr_account = (node.attrib.get("Account") or node.attrib.get("Value") or node.text or "").strip()
                if corr_account:
                    break

    return {
        "bank_name": bank_name,
        "corr_account": corr_account,
    }
