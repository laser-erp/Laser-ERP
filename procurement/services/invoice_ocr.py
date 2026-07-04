import re
import subprocess
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader
import pypdfium2 as pdfium

from core.models import Organization
from procurement.models import SupplierInvoice, SupplierInvoiceCategoryMemory


_RU_MONTHS = {
    "янв": 1,
    "январ": 1,
    "фев": 2,
    "феврал": 2,
    "мар": 3,
    "март": 3,
    "апр": 4,
    "апрел": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июня": 6,
    "июл": 7,
    "июль": 7,
    "авг": 8,
    "август": 8,
    "сен": 9,
    "сентябр": 9,
    "окт": 10,
    "октябр": 10,
    "ноя": 11,
    "ноябр": 11,
    "дек": 12,
    "декабр": 12,
}


def _normalize_ocr_date(day: str, month: str, year: str) -> str:
    try:
        d = int(day)
        y = int(year)
    except (TypeError, ValueError):
        return ""
    month_str = str(month or "").strip().lower().replace("ё", "е")
    m = None
    if month_str.isdigit():
        try:
            m = int(month_str)
        except ValueError:
            m = None
    else:
        for key, value in _RU_MONTHS.items():
            if month_str.startswith(key):
                m = value
                break
    if not m:
        return ""
    try:
        return datetime(y, m, d).strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _extract_invoice_date(text: str) -> str:
    compact = " ".join((text or "").split())
    # Сначала ищем дату после "счёт ... от ...", это чаще всего дата документа.
    context_patterns = [
        re.compile(
            r"(?:счет|сч[её]т)[^.\n]{0,120}?\bот\b\s*(\d{1,2})[./-](\d{1,2})[./-](20\d{2})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?:счет|сч[её]т)[^.\n]{0,120}?\bот\b\s*(\d{1,2})\s+([А-Яа-яЁё]+)\s*,?\s*(20\d{2})",
            flags=re.IGNORECASE,
        ),
    ]
    for pattern in context_patterns:
        match = pattern.search(compact)
        if match:
            normalized = _normalize_ocr_date(match.group(1), match.group(2), match.group(3))
            if normalized:
                return normalized

    # Затем любые валидные даты в документе (включая "25 марта 2026").
    all_patterns = [
        re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b"),
        re.compile(r"\b(\d{1,2})\s+([А-Яа-яЁё]+)\s*,?\s*(20\d{2})\b", flags=re.IGNORECASE),
    ]
    for pattern in all_patterns:
        for match in pattern.finditer(compact):
            normalized = _normalize_ocr_date(match.group(1), match.group(2), match.group(3))
            if normalized:
                return normalized
    return ""


def _extract_invoice_date_from_filename(name: str) -> str:
    stem = Path(str(name or "")).stem.replace("_", " ").replace("-", " ")
    normalized = " ".join(stem.split())
    patterns = [
        re.compile(r"\b(\d{1,2})\s+(\d{1,2})\s+(20\d{2})\b"),
        re.compile(r"\b(\d{1,2})\s+([А-Яа-яЁё]+)\s+(20\d{2})\b", flags=re.IGNORECASE),
    ]
    for pattern in patterns:
        for match in pattern.finditer(normalized):
            value = _normalize_ocr_date(match.group(1), match.group(2), match.group(3))
            if value:
                return value
    return ""


def _ocr_settings():
    defaults = {
        "enabled": False,
        "tesseract_cmd": "tesseract",
        "timeout_seconds": 40,
    }
    cfg = getattr(settings, "INVOICE_OCR", {})
    return {
        "enabled": bool(cfg.get("enabled", defaults["enabled"])),
        "tesseract_cmd": str(cfg.get("tesseract_cmd", defaults["tesseract_cmd"])),
        "timeout_seconds": int(cfg.get("timeout_seconds", defaults["timeout_seconds"])),
    }


def _extract_fields(raw_text: str):
    text = raw_text or ""
    compact = " ".join(text.split())
    number_match = re.search(
        r"(?:счет|сч[её]т)[^\d]{0,16}(?:№|N|No|Номер)?\s*([A-Za-zА-Яа-я0-9\-\/]{1,32})",
        compact,
        flags=re.IGNORECASE,
    )
    invoice_date_raw = _extract_invoice_date(text)
    inn_match = re.search(r"ИНН[:\s]*([0-9]{10,12})", compact, flags=re.IGNORECASE)
    kpp_match = re.search(r"КПП[:\s]*([0-9]{9})", compact, flags=re.IGNORECASE)

    total_amount = ""
    amount_candidates: list[Decimal] = []
    for line in text.splitlines():
        if not re.search(r"(итого|к оплате|сумма)", line, flags=re.IGNORECASE):
            continue
        for match in re.finditer(
            r"([0-9]{1,3}(?:[ \u00A0]?[0-9]{3})*(?:[.,][0-9]{1,2})|[0-9]+(?:[.,][0-9]{1,2}))",
            line,
            flags=re.IGNORECASE,
        ):
            raw = match.group(1).replace(" ", "").replace("\u00A0", "").replace(",", ".")
            try:
                amount_candidates.append(Decimal(raw))
            except (InvalidOperation, ValueError):
                continue
    if not amount_candidates:
        for match in re.finditer(
            r"([0-9]{1,3}(?:[ \u00A0]?[0-9]{3})+(?:[.,][0-9]{1,2})|[0-9]+[.,][0-9]{1,2})",
            compact,
            flags=re.IGNORECASE,
        ):
            raw = match.group(1).replace(" ", "").replace("\u00A0", "").replace(",", ".")
            try:
                amount_candidates.append(Decimal(raw))
            except (InvalidOperation, ValueError):
                continue
    if amount_candidates:
        total_amount = str(max(amount_candidates).quantize(Decimal("0.01")))
    all_inns = list(dict.fromkeys(re.findall(r"\b\d{10,12}\b", compact)))
    purpose = ""
    stop_tokens_re = re.compile(
        r"^(инн|кпп|бик|сч\.?|р/с|кор\.?\s*сч|плательщик|получатель|банк|окпо|октмо|адрес|телефон|email|e-mail)\b",
        flags=re.IGNORECASE,
    )
    label_re = re.compile(r"назнач[еёеи]\w*\s+плат[её]ж\w*", flags=re.IGNORECASE)
    lines = text.splitlines()

    def _cleanup_purpose_line(
        value: str,
        strip_leading_index: bool = True,
        strip_trailing_amounts: bool = True,
    ) -> str:
        line = " ".join((value or "").split()).strip()
        if strip_leading_index:
            line = re.sub(r"^\d+\s+", "", line).strip()
        # В строках табличной части часто в конце идет сумма/кол-во — обрезаем хвост.
        if strip_trailing_amounts:
            for _ in range(2):
                line = re.sub(
                    r"\s-?\d{1,3}(?:[ \u00A0]?\d{3})*(?:[.,]\d{1,2})\s*$",
                    "",
                    line,
                ).strip()
        return line
    for idx, raw_line in enumerate(lines):
        line = " ".join(raw_line.split())
        if not line:
            continue
        if not label_re.search(line):
            continue

        # 1) Берем текст справа от "Назначение платежа: ..." в той же строке.
        same_line = label_re.split(line, maxsplit=1)
        tail = same_line[1] if len(same_line) > 1 else ""
        tail = re.sub(r"^[\s:.\-–—]+", "", tail).strip()

        parts: list[str] = []
        if tail:
            parts.append(tail)

        # 2) Если в той же строке текста мало — добираем следующие строки, пока не встретим стоп-поле.
        if len(" ".join(parts)) < 20:
            for next_raw in lines[idx + 1 : idx + 6]:
                next_line = " ".join(next_raw.split())
                if not next_line:
                    if parts:
                        break
                    continue
                if stop_tokens_re.match(next_line):
                    break
                if label_re.search(next_line):
                    break
                parts.append(next_line)
                if len(" ".join(parts)) >= 255:
                    break

        candidate = " ".join(parts).strip()
        if candidate:
            purpose = candidate[:255]
            break

    # Если явной метки нет, пробуем взять описание первой позиции из табличной части.
    if not purpose:
        table_header_re = re.compile(
            r"товары\s*\(.*работы.*услуг",
            flags=re.IGNORECASE,
        )
        stop_table_re = re.compile(
            r"^(итого|всего\s+к\s+оплате|сумма\s+ндс|в\s+том\s+числе|основание)\b",
            flags=re.IGNORECASE,
        )
        header_idx = -1
        for i, raw_line in enumerate(lines):
            if table_header_re.search(" ".join(raw_line.split())):
                header_idx = i
                break
        if header_idx >= 0:
            first_line = ""
            extra_parts: list[str] = []
            for raw_line in lines[header_idx + 1 : header_idx + 10]:
                line = " ".join(raw_line.split()).strip()
                if not line:
                    continue
                if stop_table_re.match(line):
                    break
                if not first_line:
                    candidate = _cleanup_purpose_line(line)
                    if len(candidate) >= 8 and re.search(r"[A-Za-zА-Яа-яЁё]", candidate):
                        first_line = candidate
                    continue
                if re.match(r"^\d+\s+", line):
                    break
                if stop_table_re.match(line):
                    break
                cont = _cleanup_purpose_line(line)
                if cont:
                    extra_parts.append(cont)
            if first_line:
                merged = " ".join([first_line] + extra_parts).strip()
                # Частый кейс OCR: год ("2026 г.") улетает на следующую короткую строку.
                if not re.search(r"\b20\d{2}\s*г\.?\b", merged, flags=re.IGNORECASE):
                    for raw_line in lines[header_idx + 1 : header_idx + 14]:
                        probe = " ".join(raw_line.split()).strip()
                        if re.fullmatch(r"\d{4}\s*г\.?", probe, flags=re.IGNORECASE):
                            merged = f"{merged} {probe}".strip()
                            break
                purpose = merged[:255]

    table_text = ""
    table_header_re = re.compile(r"товары\s*\(.*работы.*услуг", flags=re.IGNORECASE)
    table_stop_re = re.compile(
        r"^(итого|всего\s+к\s+оплате|сумма\s+ндс|в\s+том\s+числе|руководитель|бухгалтер|основание)\b",
        flags=re.IGNORECASE,
    )
    header_idx = -1
    for i, raw_line in enumerate(lines):
        if table_header_re.search(" ".join(raw_line.split())):
            header_idx = i
            break
    if header_idx >= 0:
        rows: list[dict] = []
        current_number = ""
        current_raw = ""
        unit_only_re = re.compile(r"^(мес|шт|кг|г|л|м|м2|м3|час|дн)\.?$", flags=re.IGNORECASE)
        unit_token_re = re.compile(r"^(мес|шт|кг|г|л|м|м2|м3|час|дн)\.?$", flags=re.IGNORECASE)
        num_token_re = re.compile(r"^-?\d+(?:[.,]\d+)?$")
        money_token_re = re.compile(r"^-?\d{1,3}(?:[ \u00A0]?\d{3})*(?:[.,]\d{1,2})$|^-?\d+(?:[.,]\d{1,2})$")
        metrics_line_re = re.compile(
            r"^(?:\d+(?:[.,]\d+)?\s+)?(?:мес|шт|кг|г|л|м|м2|м3|час|дн)\.?\s+"
            r"-?\d{1,3}(?:[ \u00A0]?\d{3})*(?:[.,]\d{1,2})\s+"
            r"-?\d{1,3}(?:[ \u00A0]?\d{3})*(?:[.,]\d{1,2})$",
            flags=re.IGNORECASE,
        )

        def _collapse_money_tokens(tokens: list[str]) -> list[str]:
            if not tokens:
                return []
            merged: list[str] = []
            i = 0
            while i < len(tokens):
                cur = tokens[i]
                if i + 1 < len(tokens):
                    nxt = tokens[i + 1]
                    if re.fullmatch(r"\d{1,3}", cur) and re.fullmatch(r"\d{3}(?:[.,]\d{1,2})?", nxt):
                        merged.append(f"{cur} {nxt}")
                        i += 2
                        continue
                merged.append(cur)
                i += 1
            return merged

        def _parse_row(raw_row: str) -> tuple[str, str, str, str, str]:
            prepared = " ".join((raw_row or "").split()).strip()
            tokens = _collapse_money_tokens(prepared.split(" ")) if prepared else []
            if len(tokens) < 3:
                return prepared, "", "", "", ""
            money_positions = [idx for idx, token in enumerate(tokens) if money_token_re.match(token)]
            if len(money_positions) < 2:
                return prepared, "", "", "", ""
            amount_idx = money_positions[-1]
            price_idx = money_positions[-2]
            amount = tokens[amount_idx]
            price = tokens[price_idx]

            unit = ""
            qty = ""
            desc_end = price_idx
            if price_idx > 0 and unit_token_re.match(tokens[price_idx - 1]):
                unit = tokens[price_idx - 1]
                desc_end = price_idx - 1
                if desc_end > 0 and num_token_re.match(tokens[desc_end - 1]):
                    qty = tokens[desc_end - 1]
                    desc_end -= 1

            description = " ".join(tokens[:desc_end]).strip()
            if not description:
                description = prepared
            return description, qty, unit, price, amount

        def _push_current():
            nonlocal current_number, current_raw
            if not current_raw:
                return
            desc, qty, unit, price, amount = _parse_row(current_raw)
            rows.append(
                {
                    "number": current_number or "",
                    "description": desc or current_raw.strip(),
                    "qty": qty,
                    "unit": unit,
                    "price": price,
                    "amount": amount,
                }
            )
            current_number = ""
            current_raw = ""

        for raw_line in lines[header_idx + 1 :]:
            line = " ".join(raw_line.split()).strip()
            if not line:
                continue
            if table_stop_re.match(line):
                break
            row_match = re.match(r"^(\d{1,2})\s+(.+)$", line)
            if row_match:
                rest = " ".join(row_match.group(2).split()).strip()
                # Строка типа "1 мес 518,63 518,63" — это продолжение текущей позиции (кол-во/ед/цена/сумма),
                # а не новая позиция таблицы.
                if current_raw and metrics_line_re.match(rest):
                    current_raw = (current_raw + " " + rest).strip()
                    continue
                _push_current()
                current_number = row_match.group(1)
                current_raw = _cleanup_purpose_line(
                    rest,
                    strip_leading_index=False,
                    strip_trailing_amounts=False,
                )
                continue
            if current_raw:
                cont = _cleanup_purpose_line(
                    line,
                    strip_leading_index=False,
                    strip_trailing_amounts=False,
                )
                if not cont:
                    continue
                if unit_only_re.match(cont):
                    continue
                if re.fullmatch(r"\d{4}\s*г\.?", cont, flags=re.IGNORECASE):
                    if not re.search(r"\b20\d{2}\s*г\.?\b", current_raw, flags=re.IGNORECASE):
                        current_raw = (current_raw + " " + cont).strip()
                    continue
                if len(cont) <= 3 and not re.search(r"[А-Яа-яЁё]", cont):
                    continue
                current_raw = (current_raw + " " + cont).strip()
        _push_current()
        rows = [
            r for r in rows
            if (r.get("description") or "").strip()
            and len((r.get("description") or "").strip()) >= 8
        ]
        if rows:
            header = "№ | Товары (работы, услуги) | Кол-во | Ед. | Цена | Сумма"
            out_rows = [header]
            for row in rows:
                out_rows.append(
                    f"{row['number']} | {row['description']} | {row['qty'] or ''} | {row['unit'] or ''} | {row['price'] or ''} | {row['amount'] or ''}"
                )
            table_text = "\n".join(out_rows)[:4000]

    if not purpose:
        candidate_keywords = (
            "аванс",
            "предоплат",
            "по договор",
            "за услуг",
            "за достав",
            "за товар",
            "за материал",
            "оплата услуг",
            "оплата поставки",
        )
        for raw_line in lines:
            line = " ".join(raw_line.split())
            if len(line) < 16:
                continue
            if stop_tokens_re.match(line):
                continue
            lower_line = line.lower()
            if "счет на оплату" in lower_line or "счёт на оплату" in lower_line:
                continue
            if any(k in lower_line for k in candidate_keywords):
                purpose = line[:255]
                break

    return {
        "number": number_match.group(1) if number_match else "",
        "invoice_date_raw": invoice_date_raw,
        "supplier_inn": inn_match.group(1) if inn_match else "",
        "supplier_kpp": kpp_match.group(1) if kpp_match else "",
        "total_amount": total_amount,
        "all_inns": all_inns,
        "payment_purpose": purpose,
        "payment_table_text": table_text,
    }


def _normalize_payment_purpose(value: str, ocr_text: str = "") -> str:
    purpose = " ".join((value or "").split()).strip()
    # Убираем ведущую нумерацию табличной строки: "1 ..." / "2 ..."
    purpose = re.sub(r"^\d+\s+", "", purpose).strip()
    # Часто OCR делит "за <месяц> 2026 г." на две строки; доклеиваем год из текста.
    if purpose and re.search(r"\bза\s+[А-Яа-яЁё]+\s*$", purpose):
        m = re.search(
            r"\bза\s+([А-Яа-яЁё]+)\s+(20\d{2})\s*г\.?",
            ocr_text or "",
            flags=re.IGNORECASE,
        )
        if m:
            month, year = m.group(1), m.group(2)
            purpose = re.sub(
                r"\bза\s+[А-Яа-яЁё]+\s*$",
                f"за {month} {year} г.",
                purpose,
                flags=re.IGNORECASE,
            )
    return purpose[:255]


def _extract_text_from_pdf(file_path: Path) -> str:
    try:
        reader = PdfReader(str(file_path))
    except Exception:
        return ""
    text_parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            text_parts.append(page_text.strip())
    return "\n".join(text_parts).strip()


def _run_tesseract(source_path: Path, cfg: dict) -> tuple[int, str]:
    proc = subprocess.run(
        [cfg["tesseract_cmd"], str(source_path), "stdout", "-l", "rus+eng"],
        capture_output=True,
        timeout=cfg["timeout_seconds"],
        check=False,
    )
    payload = proc.stdout or proc.stderr or b""
    raw_text = ""
    for enc in ("utf-8", "utf-8-sig", "cp1251", "cp866"):
        try:
            raw_text = payload.decode(enc).strip()
            if raw_text:
                break
        except Exception:
            continue
    return proc.returncode, raw_text


def _ocr_pdf_via_render(file_path: Path, cfg: dict) -> tuple[int, str]:
    page_texts: list[str] = []
    pdf_doc = pdfium.PdfDocument(str(file_path))
    max_pages = min(len(pdf_doc), 4)
    if max_pages <= 0:
        return 1, ""
    with tempfile.TemporaryDirectory(prefix="invoice_ocr_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for idx in range(max_pages):
            page = pdf_doc[idx]
            pil_image = page.render(scale=2.0).to_pil()
            img_path = tmp_root / f"page_{idx + 1}.png"
            pil_image.save(img_path)
            code, text = _run_tesseract(img_path, cfg)
            if code == 0 and text:
                page_texts.append(text)
    joined = "\n\n".join(page_texts).strip()
    return (0 if joined else 1), joined


def _normalize_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_purpose_text(value: str) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"[^\w\sа-яё-]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text, flags=re.IGNORECASE)
    return text[:255].strip()


def _learned_category_for_purpose(payment_purpose: str) -> str:
    normalized = normalize_purpose_text(payment_purpose)
    if not normalized:
        return ""
    memory = SupplierInvoiceCategoryMemory.objects.filter(normalized_name=normalized).first()
    if memory and memory.is_auto_ready:
        return memory.category
    return ""


def _classify_expense_category(payment_purpose: str) -> str:
    text = (payment_purpose or "").lower()
    if not text:
        return ""
    rules = [
        (SupplierInvoice.EXP_CAT_LOGISTICS, ("доставк", "логист", "перевоз", "транспорт", "курьер", "экспед")),
        (SupplierInvoice.EXP_CAT_RENT, ("аренд", "найм помещ", "лизинг помещ")),
        (SupplierInvoice.EXP_CAT_UTILITIES, ("электроэнерг", "водоснабж", "отоплен", "коммуналь", "жкх", "газ")),
        (SupplierInvoice.EXP_CAT_MARKETING, ("реклам", "маркет", "продвиж", "таргет", "контекст", "smm")),
        (SupplierInvoice.EXP_CAT_IT, ("хостинг", "домен", "лиценз", "программ", "по ", "интернет", "телефон", "связь", "crm")),
        (SupplierInvoice.EXP_CAT_EQUIPMENT, ("оборудован", "станок", "принтер", "компьютер", "оргтехник", "инструмент")),
        (SupplierInvoice.EXP_CAT_SERVICES, ("услуг", "работ", "монтаж", "настройк", "обслуживан", "ремонт")),
        (SupplierInvoice.EXP_CAT_MATERIALS, ("материал", "сырь", "бумаг", "картон", "краск", "пленк", "комплектующ", "расходн")),
    ]
    for category, needles in rules:
        if any(needle in text for needle in needles):
            return category
    return SupplierInvoice.EXP_CAT_OTHER


def _is_gsi_rent_case(invoice: SupplierInvoice, payment_purpose: str) -> bool:
    supplier = getattr(invoice, "supplier", None)
    supplier_name = " ".join(
        [
            str(getattr(supplier, "name", "") or "").strip(),
            str(getattr(supplier, "short_name", "") or "").strip(),
        ]
    ).lower()
    purpose_text = str(payment_purpose or "").lower()
    return "гси" in supplier_name and "арендной платы" in purpose_text


def _is_szuk_operating_services_case(invoice: SupplierInvoice, payment_purpose: str) -> bool:
    supplier = getattr(invoice, "supplier", None)
    supplier_name = " ".join(
        [
            str(getattr(supplier, "name", "") or "").strip(),
            str(getattr(supplier, "short_name", "") or "").strip(),
        ]
    ).lower()
    purpose_text = str(payment_purpose or "").lower()
    return "сзук" in supplier_name and "эксплуатационные услуги" in purpose_text


def apply_ocr_data_to_supplier_invoice(invoice: SupplierInvoice) -> list[str]:
    data = invoice.ocr_data or {}
    changed_fields: list[str] = []

    number = (data.get("number") or "").strip()
    if number and (not invoice.number or invoice.number.startswith("СП-")):
        invoice.number = number
        changed_fields.append("number")

    date_raw = (data.get("invoice_date_raw") or "").strip()
    if not date_raw and getattr(invoice, "invoice_file", None):
        date_raw = _extract_invoice_date_from_filename(getattr(invoice.invoice_file, "name", ""))
    if date_raw:
        try:
            parsed_date = datetime.strptime(date_raw, "%d.%m.%Y").date()
            if invoice.invoice_date != parsed_date:
                invoice.invoice_date = parsed_date
                changed_fields.append("invoice_date")
        except ValueError:
            pass

    total_amount_raw = (data.get("total_amount") or "").strip()
    if total_amount_raw:
        try:
            parsed_amount = Decimal(total_amount_raw).quantize(Decimal("0.01"))
            if invoice.total_amount != parsed_amount:
                invoice.total_amount = parsed_amount
                changed_fields.append("total_amount")
        except (InvalidOperation, ValueError):
            pass

    supplier_inn = _normalize_digits(data.get("supplier_inn") or "")
    if supplier_inn:
        suppliers = Organization.objects.filter(is_supplier=True).order_by("id")
        matched = next(
            (org for org in suppliers if _normalize_digits(org.inn) == supplier_inn),
            None,
        )
        if matched and invoice.supplier_id != matched.pk:
            invoice.supplier = matched
            changed_fields.append("supplier")

    if not invoice.our_organization_id:
        all_inns = [_normalize_digits(v) for v in (data.get("all_inns") or [])]
        buyer_candidates = list(Organization.objects.filter(is_buyer=True).order_by("id"))
        matched_buyer = next(
            (
                org
                for org in buyer_candidates
                if _normalize_digits(org.inn) in all_inns
                and _normalize_digits(org.inn) != supplier_inn
            ),
            None,
        )
        if not matched_buyer and len(buyer_candidates) == 1:
            matched_buyer = buyer_candidates[0]
        if matched_buyer:
            invoice.our_organization = matched_buyer
            changed_fields.append("our_organization")

    payment_purpose = _normalize_payment_purpose(
        (data.get("payment_purpose") or "").strip(),
        invoice.ocr_result_text or "",
    )
    parsed_from_raw = {}
    if invoice.ocr_result_text:
        parsed_from_raw = _extract_fields(invoice.ocr_result_text)
    payment_table_text = (parsed_from_raw.get("payment_table_text") or data.get("payment_table_text") or "").strip()
    if payment_table_text and (data.get("payment_table_text") or "").strip() != payment_table_text:
        data = dict(data)
        data["payment_table_text"] = payment_table_text
        invoice.ocr_data = data
        changed_fields.append("ocr_data")
    if not payment_purpose and invoice.ocr_result_text:
        payment_purpose = _normalize_payment_purpose(
            (parsed_from_raw.get("payment_purpose") or "").strip(),
            invoice.ocr_result_text or "",
        )
        if not payment_table_text:
            payment_table_text = (parsed_from_raw.get("payment_table_text") or "").strip()
        if payment_purpose or payment_table_text:
            data = dict(data)
            if payment_purpose:
                data["payment_purpose"] = payment_purpose
            if payment_table_text:
                data["payment_table_text"] = payment_table_text
            invoice.ocr_data = data
            changed_fields.append("ocr_data")
    comment_value = payment_table_text or payment_purpose
    if comment_value and comment_value != (invoice.comment or "").strip():
        invoice.comment = comment_value
        changed_fields.append("comment")

    category_text = payment_purpose or (invoice.comment or "").strip()
    # Жесткое бизнес-правило: счета ГСИ с формулировкой "арендной платы" всегда в аренду.
    forced_category = ""
    forced_subcategory_display = ""
    if _is_szuk_operating_services_case(invoice, category_text):
        forced_category = SupplierInvoice.EXP_CAT_RENT
        forced_subcategory_display = "Эксплуатационные услуги"
    elif _is_gsi_rent_case(invoice, category_text):
        forced_category = SupplierInvoice.EXP_CAT_RENT

    if forced_category and invoice.expense_category != forced_category:
        invoice.expense_category = forced_category
        changed_fields.append("expense_category")
    marker_data = dict(invoice.ocr_data or {})
    marker_changed = False
    current_marker = str(marker_data.get("forced_expense_subcategory_display") or "").strip()
    if forced_subcategory_display and current_marker != forced_subcategory_display:
        marker_data["forced_expense_subcategory_display"] = forced_subcategory_display
        marker_changed = True
    if not forced_subcategory_display and "forced_expense_subcategory_display" in marker_data:
        marker_data.pop("forced_expense_subcategory_display", None)
        marker_changed = True
    if marker_changed:
        invoice.ocr_data = marker_data
        changed_fields.append("ocr_data")
    learned_category = _learned_category_for_purpose(category_text) if not forced_category else ""
    if learned_category and invoice.expense_category != learned_category:
        invoice.expense_category = learned_category
        changed_fields.append("expense_category")
    elif not forced_category and not learned_category and not (invoice.expense_category or "").strip():
        suggestion = _classify_expense_category(category_text[:1200])
        if suggestion:
            data = dict(invoice.ocr_data or {})
            if data.get("suggested_expense_category") != suggestion:
                data["suggested_expense_category"] = suggestion
                invoice.ocr_data = data
                changed_fields.append("ocr_data")

    if changed_fields:
        invoice.ocr_status = SupplierInvoice.OCR_APPLIED
        invoice.ocr_reviewed_at = timezone.now()
        changed_fields.extend(["ocr_status", "ocr_reviewed_at"])
        invoice.save(update_fields=list(dict.fromkeys(changed_fields)))

    return changed_fields


def register_invoice_category_feedback(invoice: SupplierInvoice) -> tuple[int, bool]:
    payment_purpose = (invoice.comment or "").strip() or (invoice.ocr_data or {}).get("payment_purpose", "").strip()
    category = (invoice.expense_category or "").strip()
    normalized = normalize_purpose_text(payment_purpose)
    if not payment_purpose or not category or not normalized:
        return 0, False

    memory = SupplierInvoiceCategoryMemory.objects.filter(normalized_name=normalized).first()
    if not memory:
        SupplierInvoiceCategoryMemory.objects.create(
            normalized_name=normalized,
            source_name=payment_purpose[:255],
            category=category,
            confirmations=1,
        )
        return 1, False

    if memory.category == category:
        memory.confirmations += 1
        memory.source_name = payment_purpose[:255]
        memory.save(update_fields=["confirmations", "source_name", "updated_at"])
    else:
        memory.category = category
        memory.source_name = payment_purpose[:255]
        memory.confirmations = 1
        memory.save(update_fields=["category", "source_name", "confirmations", "updated_at"])
    return memory.confirmations, memory.is_auto_ready


def recognize_supplier_invoice(invoice: SupplierInvoice):
    if not invoice.invoice_file:
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = "Файл счёта не приложен."
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data

    try:
        source_path = Path(invoice.invoice_file.path)
    except Exception as exc:
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = f"Не удалось открыть файл: {exc}"
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data

    is_pdf = source_path.suffix.lower() == ".pdf"
    pdf_text = _extract_text_from_pdf(source_path) if is_pdf else ""

    cfg = _ocr_settings()
    if not cfg["enabled"]:
        if pdf_text:
            extracted = _extract_fields(pdf_text)
            invoice.ocr_status = SupplierInvoice.OCR_REVIEW
            invoice.ocr_result_text = (
                "Распознано из текстового слоя PDF (без OCR-движка).\n\n" + pdf_text
            )
            invoice.ocr_data = extracted
            invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
            return invoice.ocr_status, extracted
        invoice.ocr_status = SupplierInvoice.OCR_REVIEW
        invoice.ocr_result_text = (
            "OCR отключен в настройках. Для фото/сканов включите OCR и установите tesseract."
        )
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data

    if pdf_text:
        extracted = _extract_fields(pdf_text)
        invoice.ocr_status = SupplierInvoice.OCR_REVIEW
        invoice.ocr_result_text = "Распознано из текстового слоя PDF.\n\n" + pdf_text
        invoice.ocr_data = extracted
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, extracted

    try:
        return_code, raw_text = _run_tesseract(source_path, cfg)
    except FileNotFoundError:
        if pdf_text:
            extracted = _extract_fields(pdf_text)
            invoice.ocr_status = SupplierInvoice.OCR_REVIEW
            invoice.ocr_result_text = (
                "Tesseract не найден. Использован текстовый слой PDF.\n\n" + pdf_text
            )
            invoice.ocr_data = extracted
            invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
            return invoice.ocr_status, extracted
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = f"Tesseract не найден: {cfg['tesseract_cmd']}"
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data
    except subprocess.TimeoutExpired:
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = "OCR превысил лимит времени."
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data
    except Exception as exc:
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = f"Ошибка OCR: {exc}"
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data

    if (
        is_pdf
        and return_code != 0
        and "pdf reading is not supported" in raw_text.lower()
    ):
        try:
            return_code, raw_text = _ocr_pdf_via_render(source_path, cfg)
        except Exception as exc:
            invoice.ocr_status = SupplierInvoice.OCR_FAILED
            invoice.ocr_result_text = f"Ошибка OCR PDF: {exc}"
            invoice.ocr_data = {}
            invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
            return invoice.ocr_status, invoice.ocr_data

    if return_code != 0 and not raw_text:
        invoice.ocr_status = SupplierInvoice.OCR_FAILED
        invoice.ocr_result_text = f"OCR завершился с кодом {return_code}."
        invoice.ocr_data = {}
        invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
        return invoice.ocr_status, invoice.ocr_data

    extracted = _extract_fields(raw_text)
    invoice.ocr_status = SupplierInvoice.OCR_REVIEW
    invoice.ocr_result_text = raw_text
    invoice.ocr_data = extracted
    invoice.save(update_fields=["ocr_status", "ocr_result_text", "ocr_data"])
    return invoice.ocr_status, extracted
