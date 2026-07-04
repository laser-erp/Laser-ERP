"""
Миксин для админки: после сохранения формы — редирект на предыдущую страницу
и подстановка сохранённого объекта в поле на той форме.
В режиме попапа (_popup=1) всегда возвращаем страницу закрытия попапа с подстановкой в родительское окно.
"""
import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme


def _redirect_with_selected(referrer, obj):
    """Добавляет к URL параметры _selected_id и _selected_model для подстановки на форме."""
    parsed = urlparse(referrer)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["_selected_id"] = [str(obj.pk)]
    query["_selected_model"] = [obj.__class__._meta.label_lower]
    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _referrer_differs_from_current(referrer: str, request) -> bool:
    """True, если Referer — другая страница, чем текущий add/change (без учёта query и хвостового /)."""
    if not (referrer or "").strip():
        return False
    try:
        current = request.build_absolute_uri(request.path)
    except Exception:
        return True
    ref = referrer.strip()
    if ref == current:
        return False
    p_ref = urlparse(ref)
    p_cur = urlparse(current)
    ref_path = (p_ref.path or "").rstrip("/") or "/"
    cur_path = (p_cur.path or "").rstrip("/") or "/"
    if (p_ref.scheme or "").lower() != (p_cur.scheme or "").lower():
        return True
    if (p_ref.netloc or "").lower() != (p_cur.netloc or "").lower():
        return True
    return ref_path != cur_path


def _build_popup_response_data(request, obj, action="add"):
    """Формирует JSON для закрытия попапа и подстановки в родительское окно."""
    to_field = request.POST.get("_to_field") or request.GET.get("_to_field") or "id"
    attr = getattr(obj._meta.pk, "attname", "pk")
    if to_field != "id" and hasattr(obj._meta, "get_field"):
        try:
            f = obj._meta.get_field(to_field)
            attr = f.attname
        except Exception:
            pass
    value = getattr(obj, attr, obj.pk)
    data = {
        "value": str(value),
        "obj": str(obj),
        "model": obj.__class__._meta.label_lower,
    }
    if action == "change":
        data["action"] = "change"
        data["new_value"] = str(value)
    return json.dumps(data)


class ReturnToReferrerMixin:
    """После «Сохранить» возвращает на страницу, с которой открыли форму, и подставляет новое значение в поле."""

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        """На GET кладём Referer в контекст — при POST он уходит в скрытом поле (см. templates/admin/change_form.html)."""
        extra = dict(extra_context or {})
        if request.method == "GET":
            ref = (request.META.get("HTTP_REFERER") or "").strip()
            if ref and _referrer_differs_from_current(ref, request) and url_has_allowed_host_and_scheme(
                ref, allowed_hosts={request.get_host()}
            ):
                extra["admin_redirect_back_url"] = ref
        else:
            posted = (request.POST.get("_redirect_back_url") or "").strip()
            if posted and url_has_allowed_host_and_scheme(
                posted, allowed_hosts={request.get_host()}
            ):
                extra["admin_redirect_back_url"] = posted
        return super().changeform_view(request, object_id, form_url, extra or None)

    def response_add(self, request, obj, post_url_continue=None):
        resp = super().response_add(request, obj, post_url_continue)
        is_popup = request.GET.get("_popup") or request.POST.get("_popup")
        if is_popup:
            # В режиме попапа всегда отдаём страницу закрытия попапа (не редирект)
            if isinstance(resp, HttpResponseRedirect):
                popup_response_data = _build_popup_response_data(request, obj, action="add")
                # URL возврата: из скрытого поля (форма открыта в той же вкладке) или referrer
                redirect_back_url = (request.POST.get("_redirect_back_url") or "").strip()
                if not redirect_back_url and request.META.get("HTTP_REFERER"):
                    redirect_back_url = request.META.get("HTTP_REFERER")
                return TemplateResponse(
                    request,
                    "admin/popup_response.html",
                    {
                        "popup_response_data": popup_response_data,
                        "redirect_back_url": redirect_back_url,
                    },
                )
            if getattr(resp, "context_data", None) and "popup_response_data" in resp.context_data:
                data = json.loads(resp.context_data["popup_response_data"])
                data["model"] = obj.__class__._meta.label_lower
                resp.context_data["popup_response_data"] = json.dumps(data)
                redirect_back_url = (request.POST.get("_redirect_back_url") or "").strip()
                if redirect_back_url:
                    resp.context_data["redirect_back_url"] = redirect_back_url
            return resp
        back = (request.POST.get("_redirect_back_url") or "").strip()
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
            return HttpResponseRedirect(_redirect_with_selected(back, obj))
        referrer = request.META.get("HTTP_REFERER")
        if (
            referrer
            and _referrer_differs_from_current(referrer, request)
            and url_has_allowed_host_and_scheme(referrer, allowed_hosts={request.get_host()})
        ):
            return HttpResponseRedirect(_redirect_with_selected(referrer, obj))
        return resp

    def response_change(self, request, obj):
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return super().response_change(request, obj)
        back = (request.POST.get("_redirect_back_url") or "").strip()
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
            return HttpResponseRedirect(back)
        referrer = request.META.get("HTTP_REFERER")
        if (
            referrer
            and _referrer_differs_from_current(referrer, request)
            and url_has_allowed_host_and_scheme(referrer, allowed_hosts={request.get_host()})
        ):
            return HttpResponseRedirect(referrer)
        return super().response_change(request, obj)
