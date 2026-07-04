import mimetypes
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from core.models import ProductionRequest


def _upload_security_settings():
    defaults = {
        "max_size_mb": 20,
        "allowed_extensions": {
            ".pdf",
            ".cdr",
            ".ai",
            ".eps",
            ".svg",
            ".dxf",
            ".dwg",
            ".zip",
            ".rar",
            ".7z",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        },
        "allowed_mime_types": {
            "application/pdf",
            "application/postscript",
            "application/zip",
            "application/x-zip-compressed",
            "application/x-rar-compressed",
            "application/octet-stream",
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/svg+xml",
        },
    }
    cfg = getattr(settings, "UPLOAD_SECURITY", {})
    return {
        "max_size_mb": int(cfg.get("max_size_mb", defaults["max_size_mb"])),
        "allowed_extensions": {str(x).lower() for x in cfg.get("allowed_extensions", defaults["allowed_extensions"])},
        "allowed_mime_types": {str(x).lower() for x in cfg.get("allowed_mime_types", defaults["allowed_mime_types"])},
    }


def _clamav_settings():
    defaults = {
        "enabled": False,
        "strict_mode": True,
        "executable": "clamscan",
        "timeout_seconds": 45,
    }
    cfg = getattr(settings, "CLAMAV_SECURITY", {})
    return {
        "enabled": bool(cfg.get("enabled", defaults["enabled"])),
        "strict_mode": bool(cfg.get("strict_mode", defaults["strict_mode"])),
        "executable": str(cfg.get("executable", defaults["executable"])),
        "timeout_seconds": int(cfg.get("timeout_seconds", defaults["timeout_seconds"])),
    }


def validate_layout_file(uploaded_file):
    if not uploaded_file:
        return []
    cfg = _upload_security_settings()
    errors = []
    ext = Path(uploaded_file.name or "").suffix.lower()
    if ext not in cfg["allowed_extensions"]:
        errors.append("Недопустимый тип файла. Разрешены только макеты и архивы из утвержденного списка.")

    max_bytes = cfg["max_size_mb"] * 1024 * 1024
    if int(getattr(uploaded_file, "size", 0)) > max_bytes:
        errors.append(f"Файл слишком большой. Максимальный размер: {cfg['max_size_mb']} МБ.")

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    guessed_type = (mimetypes.guess_type(uploaded_file.name or "")[0] or "").lower()
    allowed_mimes = cfg["allowed_mime_types"]
    if content_type and content_type not in allowed_mimes and guessed_type not in allowed_mimes:
        errors.append("Тип файла не прошел MIME-проверку.")
    return errors


def _scan_with_clamav(file_path: str):
    cfg = _clamav_settings()
    if not cfg["enabled"]:
        return ProductionRequest.SCAN_SKIPPED, "Антивирусная проверка отключена в настройках."

    executable = cfg["executable"]
    try:
        proc = subprocess.run(
            [executable, "--no-summary", file_path],
            capture_output=True,
            text=True,
            timeout=cfg["timeout_seconds"],
            check=False,
        )
    except FileNotFoundError:
        return ProductionRequest.SCAN_FAILED, f"ClamAV не найден: {executable}"
    except subprocess.TimeoutExpired:
        return ProductionRequest.SCAN_FAILED, "ClamAV не ответил вовремя."
    except Exception as exc:
        return ProductionRequest.SCAN_FAILED, f"Ошибка запуска ClamAV: {exc}"

    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0:
        return ProductionRequest.SCAN_CLEAN, output or "Проверка выполнена, угроз не найдено."
    if proc.returncode == 1:
        return ProductionRequest.SCAN_INFECTED, output or "ClamAV сообщил о найденной угрозе."
    return ProductionRequest.SCAN_FAILED, output or f"Неожиданный код возврата ClamAV: {proc.returncode}"


def _quarantine_layout_file(req: ProductionRequest):
    if not req.layout_file:
        return ""
    try:
        source_path = req.layout_file.path
    except Exception:
        return ""
    if not source_path or not os.path.exists(source_path):
        return ""

    quarantine_dir = Path(settings.MEDIA_ROOT) / "production_requests" / "quarantine" / timezone.now().strftime("%Y-%m-%d")
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid4().hex}_{Path(source_path).name}"
    target_path = quarantine_dir / target_name
    shutil.move(source_path, target_path)
    return str(target_path.relative_to(settings.MEDIA_ROOT)).replace("\\", "/")


def _quarantine_abs_path(req: ProductionRequest) -> Path | None:
    rel_path = (req.layout_quarantine_path or "").strip()
    if not rel_path:
        return None
    abs_path = Path(settings.MEDIA_ROOT) / rel_path
    if not abs_path.exists():
        return None
    return abs_path


def scan_and_handle_layout_file(req: ProductionRequest):
    if not req.layout_file:
        req.layout_scan_status = ProductionRequest.SCAN_SKIPPED
        req.layout_scan_result = "Файл не был приложен."
        req.layout_scanned_at = timezone.now()
        req.layout_is_quarantined = False
        req.layout_quarantine_path = ""
        req.save(
            update_fields=[
                "layout_scan_status",
                "layout_scan_result",
                "layout_scanned_at",
                "layout_is_quarantined",
                "layout_quarantine_path",
                "updated_at",
            ]
        )
        return req.layout_scan_status, req.layout_scan_result

    try:
        file_path = req.layout_file.path
    except Exception as exc:
        req.layout_scan_status = ProductionRequest.SCAN_FAILED
        req.layout_scan_result = f"Не удалось получить путь до файла: {exc}"
        req.layout_scanned_at = timezone.now()
        req.layout_is_quarantined = False
        req.layout_quarantine_path = ""
        req.save(
            update_fields=[
                "layout_scan_status",
                "layout_scan_result",
                "layout_scanned_at",
                "layout_is_quarantined",
                "layout_quarantine_path",
                "updated_at",
            ]
        )
        return req.layout_scan_status, req.layout_scan_result

    status, result = _scan_with_clamav(file_path)
    req.layout_scan_status = status
    req.layout_scan_result = result
    req.layout_scanned_at = timezone.now()
    req.layout_is_quarantined = False
    req.layout_quarantine_path = ""

    clam_cfg = _clamav_settings()
    should_quarantine = status == ProductionRequest.SCAN_INFECTED or (
        status == ProductionRequest.SCAN_FAILED and clam_cfg["strict_mode"]
    )
    if should_quarantine:
        quarantined_path = _quarantine_layout_file(req)
        req.layout_is_quarantined = bool(quarantined_path)
        req.layout_quarantine_path = quarantined_path
        req.layout_file = ""
        if status == ProductionRequest.SCAN_FAILED and not quarantined_path:
            req.layout_scan_result = (
                f"{result}\nФайл заблокирован политикой strict_mode, но перемещение в карантин не выполнено."
            )

    req.save(
        update_fields=[
            "layout_file",
            "layout_scan_status",
            "layout_scan_result",
            "layout_scanned_at",
            "layout_is_quarantined",
            "layout_quarantine_path",
            "updated_at",
        ]
    )
    return status, req.layout_scan_result


def rescan_quarantined_layout_file(req: ProductionRequest):
    abs_path = _quarantine_abs_path(req)
    if not abs_path:
        req.layout_scan_status = ProductionRequest.SCAN_FAILED
        req.layout_scan_result = "Файл в карантине не найден. Повторная проверка невозможна."
        req.layout_scanned_at = timezone.now()
        req.save(update_fields=["layout_scan_status", "layout_scan_result", "layout_scanned_at", "updated_at"])
        return req.layout_scan_status, req.layout_scan_result

    status, result = _scan_with_clamav(str(abs_path))
    req.layout_scan_status = status
    req.layout_scan_result = result
    req.layout_scanned_at = timezone.now()

    if status == ProductionRequest.SCAN_CLEAN:
        restored_name = abs_path.name
        if "_" in restored_name:
            restored_name = restored_name.split("_", 1)[1]
        with abs_path.open("rb") as fh:
            req.layout_file.save(restored_name, File(fh), save=False)
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        req.layout_is_quarantined = False
        req.layout_quarantine_path = ""
    else:
        req.layout_is_quarantined = True

    req.save(
        update_fields=[
            "layout_file",
            "layout_scan_status",
            "layout_scan_result",
            "layout_scanned_at",
            "layout_is_quarantined",
            "layout_quarantine_path",
            "updated_at",
        ]
    )
    return req.layout_scan_status, req.layout_scan_result
