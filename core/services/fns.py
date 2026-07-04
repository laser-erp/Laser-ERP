"""
Поиск контрагентов по ИНН или наименованию.
Источники: API-ФНС (api-fns.ru), при поиске по ИНН — резерв egrul.itsoft.ru (бесплатно, без ключа).
"""
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

FNS_API_URL = "https://api-fns.ru/api/search"
FNS_EGR_API_URL = "https://api-fns.ru/api/egr"
EGRUL_ITSOFT_URL = "https://egrul.itsoft.ru"  # резерв по ИНН, без ключа, до ~100 запросов/сутки
REQUEST_TIMEOUT_SECONDS = 15
RETRY_DELAY_SECONDS = 0.6
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_api_key():
    return getattr(settings, "FNS_API_KEY", "") or ""


def _normalize_inn(inn: str) -> str:
    """Оставить только цифры ИНН (10 или 12 символов)."""
    digits = re.sub(r"\D", "", str(inn))
    return digits[:12] if len(digits) >= 10 else digits


def _raw_to_contragent(raw: dict, is_individual: bool = False) -> dict:
    """Один объект ЕГРЮЛ/ЕГРИП -> словарь контрагента. raw должен быть dict."""
    if not isinstance(raw, dict):
        raw = {}
    def _str(v):
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        return str(v).strip()
    inn_val = _str(raw.get("ИНН") or raw.get("ИННИП"))
    name = _str(
        raw.get("НаимСокрЮЛ") or raw.get("НаимПолнЮЛ")
        or raw.get("ФИОПолн")
        or raw.get("НаимПолнНР")
    ) or "—"
    return {
        "name": name,
        "inn": inn_val,
        "kpp": _str(raw.get("КПП")),
        "ogrn": _str(raw.get("ОГРН") or raw.get("ОГРНИП")),
        "legal_address": _str(raw.get("АдресПолн")),
        "is_individual": bool(is_individual or raw.get("ФИОПолн")),
        "status": _str(raw.get("Статус")),
        "raw": raw,
    }


def _parse_response(data: dict) -> list:
    """Преобразовать ответ API ФНС в список словарей контрагентов."""
    items = data.get("items") or []
    result = []
    for item in items:
        raw = item.get("ЮЛ") or item.get("ИП") or item.get("НР") or {}
        if not raw:
            continue
        result.append(_raw_to_contragent(raw, "ИП" in item or "ФИОПолн" in raw))
    return result


def _is_timeout_error(exc: Exception) -> bool:
    """Определить сетевой таймаут (в т.ч. SSL handshake timeout)."""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, ssl.SSLError) and "timed out" in str(exc).lower():
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return True
        if isinstance(reason, ssl.SSLError) and "timed out" in str(reason).lower():
            return True
        if reason and "timed out" in str(reason).lower():
            return True
    return "timed out" in str(exc).lower()


def _urlopen_json_with_retry(req: urllib.request.Request, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict:
    """
    Открыть URL и распарсить JSON.
    При таймауте делает одну повторную попытку.
    """
    last_exc = None
    for attempt in (1, 2):
        try:
            # В ряде окружений urllib автоматически использует системный proxy (Privoxy),
            # что приводит к SSL timeout/EOF для api-fns.ru и egrul.itsoft.ru.
            # Сначала идём напрямую, затем (при неудаче) пробуем стандартный путь.
            try:
                resp_ctx = DIRECT_OPENER.open(req, timeout=timeout)
            except Exception:
                resp_ctx = urllib.request.urlopen(req, timeout=timeout)
            with resp_ctx as resp:
                raw = resp.read()
                enc_candidates = []
                header_enc = None
                try:
                    header_enc = resp.headers.get_content_charset()
                except Exception:
                    header_enc = None
                if header_enc:
                    enc_candidates.append(header_enc)
                enc_candidates.extend(["utf-8", "utf-8-sig", "cp1251"])
                last_decode_exc = None
                for enc in enc_candidates:
                    try:
                        return json.loads(raw.decode(enc))
                    except (UnicodeDecodeError, json.JSONDecodeError) as dec_exc:
                        last_decode_exc = dec_exc
                        continue
                if last_decode_exc:
                    raise last_decode_exc
                raise ValueError("Не удалось декодировать JSON-ответ")
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ssl.SSLError, socket.timeout, TimeoutError) as exc:
            last_exc = exc
            if attempt == 1 and _is_timeout_error(exc):
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise
    if last_exc:
        raise last_exc
    return {}


def _fetch_contragents_egrul(inn: str) -> list:
    """
    Поиск контрагента по ИНН через egrul.itsoft.ru (резервный источник, без ключа).
    :param inn: 10 или 12 цифр ИНН
    :return: list[dict] в том же формате, что и ФНС
    """
    inn = _normalize_inn(inn)
    if len(inn) not in (10, 12):
        return []
    url = f"{EGRUL_ITSOFT_URL}/{inn}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "LaserERP/1.0"})
    try:
        data = _urlopen_json_with_retry(req)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ssl.SSLError, socket.timeout, TimeoutError):
        return []
    if not isinstance(data, dict):
        return []
    # Ответ может быть в формате ФНС: один объект ЮЛ или ИП на верхнем уровне
    for top_key in ("ЮЛ", "ИП", "НР"):
        raw = data.get(top_key)
        if isinstance(raw, dict):
            try:
                return [_raw_to_contragent(raw, top_key == "ИП" or "ФИОПолн" in raw)]
            except (TypeError, AttributeError, KeyError):
                continue
    # Вложенная структура (выписка ФНС в JSON): один вложенный dict с ИНН/Наим*
    for key in ("СвЮЛ", "СвИП", "ЮЛ", "ИП", "НР"):
        candidate = data.get(key)
        if isinstance(candidate, dict) and (candidate.get("ИНН") or candidate.get("ИННИП") or candidate.get("НаимСокрЮЛ") or candidate.get("НаимПолнЮЛ") or candidate.get("ФИОПолн")):
            try:
                return [_raw_to_contragent(candidate, key in ("СвИП", "ИП") or "ФИОПолн" in candidate)]
            except (TypeError, AttributeError, KeyError):
                continue
    # Или массив items как у ФНС
    if "items" in data:
        return _parse_response(data)
    # Краткий формат short_data: name, inn, kpp, ogrn, address и т.д.
    if "inn" in data or "ИНН" in data:
        inn_val = str(data.get("inn") or data.get("ИНН") or "").strip()
        name = str(data.get("name") or data.get("НаимСокрЮЛ") or data.get("НаимПолнЮЛ") or data.get("ФИОПолн") or "").strip() or "—"
        return [{
            "name": name,
            "inn": inn_val,
            "kpp": str(data.get("kpp") or data.get("КПП") or "").strip(),
            "ogrn": str(data.get("ogrn") or data.get("ОГРН") or data.get("ОГРНИП") or "").strip(),
            "legal_address": str(data.get("address") or data.get("АдресПолн") or data.get("legal_address") or "").strip(),
            "is_individual": bool(data.get("is_individual") or data.get("ИП") or (len(inn_val) == 12)),
            "status": str(data.get("Статус") or data.get("status") or "").strip(),
            "raw": data,
        }]
    return []


def fetch_contragents(query: str):
    """
    Поиск контрагентов по ИНН или по наименованию организации.
    По ИНН: сначала API-ФНС (если задан ключ), при ошибке или отсутствии ключа — egrul.itsoft.ru.
    По наименованию: только API-ФНС (требуется FNS_API_KEY).

    :param query: ИНН (10 или 12 цифр) либо часть названия / ФИО ИП
    :return: list[dict] — список найденных организаций/ИП
    :raises ValueError: при ошибке или пустом запросе (для поиска по наименованию — при отсутствии ключа)
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("Укажите ИНН или наименование для поиска")

    digits_only = re.sub(r"\D", "", query)
    is_inn_search = bool(
        digits_only
        and len(digits_only) in (10, 12)
        and digits_only == re.sub(r"\D", "", query)
    )
    search_q = digits_only[:12] if is_inn_search else query

    if not is_inn_search:
        # Поиск по наименованию — только ФНС
        if len(query) < 2:
            raise ValueError("Для поиска по наименованию введите не менее 2 символов")
        key = _get_api_key().strip()
        if not key:
            raise ValueError("Не задан FNS_API_KEY в настройках. Для поиска по наименованию нужен ключ api-fns.ru")
        return _fetch_contragents_fns(search_q, key)

    # Поиск по ИНН: пробуем ФНС, при неудаче — egrul.itsoft.ru
    key = _get_api_key().strip()
    if key:
        try:
            return _fetch_contragents_fns(search_q, key)
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ssl.SSLError, socket.timeout, TimeoutError) as e:
            fallback = _fetch_contragents_egrul(search_q)
            if fallback:
                return fallback
            if _is_timeout_error(e):
                raise ValueError(
                    "Сервис ФНС временно не отвечает (таймаут соединения). "
                    "Проверьте интернет/фаервол и повторите поиск. "
                    "Резервный источник по ИНН тоже не вернул запись."
                )
            raise ValueError(f"Ошибка API ФНС и по ИНН ничего не найдено в резервном источнике: {e!s}")
    # Ключа нет — сразу egrul.itsoft.ru
    result = _fetch_contragents_egrul(search_q)
    if result:
        return result
    raise ValueError(
        "Не задан FNS_API_KEY. По ИНН можно искать через резервный источник (egrul.itsoft.ru), но по данному ИНН запись не найдена."
    )


def _fetch_contragents_fns(search_q: str, key: str) -> list:
    """Запрос к API ФНС. search_q — ИНН или строка поиска по наименованию."""
    params = urllib.parse.urlencode(
        {"q": search_q, "key": key},
        encoding="utf-8",
    )
    url = f"{FNS_API_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "LaserERP/1.0"})
    data = _urlopen_json_with_retry(req)
    if isinstance(data, dict) and data.get("message") and "items" not in data:
        raise ValueError(data.get("message", "Ответ API без списка результатов"))
    return _parse_response(data)


def fetch_contragents_by_inn(inn: str):
    """
    Поиск контрагентов по ИНН в базе ФНС (API-ФНС).
    Для поиска по наименованию используйте fetch_contragents(query).
    """
    normalized = _normalize_inn(inn)
    if len(normalized) not in (10, 12):
        raise ValueError("ИНН должен содержать 10 (ЮЛ) или 12 (ИП) цифр")
    return fetch_contragents(normalized)


def fetch_contragent_egr_payload(inn: str) -> dict:
    """
    Получить расширенный профиль компании через метод egr API-ФНС.
    Возвращает raw-объект ЮЛ/ИП/НР или пустой dict.
    """
    normalized = _normalize_inn(inn)
    if len(normalized) not in (10, 12):
        return {}
    key = _get_api_key().strip()
    if not key:
        return {}

    params = urllib.parse.urlencode({"req": normalized, "key": key}, encoding="utf-8")
    url = f"{FNS_EGR_API_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "LaserERP/1.0"})
    data = _urlopen_json_with_retry(req)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}

    first_raw = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("ЮЛ") or item.get("ИП") or item.get("НР") or item.get("ИН") or {}
        if not isinstance(raw, dict):
            continue
        if not first_raw:
            first_raw = raw
        inn_val = _normalize_inn(raw.get("ИНН") or raw.get("ИННИП") or "")
        if inn_val == normalized:
            return raw
    return first_raw
