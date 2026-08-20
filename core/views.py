from datetime import date as date_cls, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db.models import F, Sum
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from .email_verification import is_email_verified, issue_email_verification
from .forms import UserProfileForm
from .services.file_security import (
    rescan_quarantined_layout_file,
    scan_and_handle_layout_file,
    validate_layout_file,
)
from .services.invoice_qr import build_russian_payment_qr_data_url
from .models import (
    Contract,
    ContractVersion,
    CustomerInvoice,
    AdminInvite,
    EmailVerification,
    Employee,
    LaborTimeLog,
    Organization,
    Order,
    OrderItem,
    Product,
    ProductionRequest,
    ProductionRequestMessage,
    UserProfile,
)
from .storefront_roles import (
    ALLOWED_PREVIEW_ROLES,
    ROLE_PREVIEW_SESSION_KEY,
    can_preview_roles,
    get_effective_role,
)


def _post_login_redirect(request):
    role = get_effective_role(request)
    if role in {"employee", "employee_admin"}:
        return redirect("order_list")
    return redirect("catalog")


def _safe_next_redirect(request):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


def _parse_ru_date(value: str) -> date_cls:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty")
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError("invalid")


def dashboard(request):
    total_orders = Order.objects.count()
    total_products = Product.objects.count()
    total_revenue = (
        OrderItem.objects.annotate(
            line_revenue=F("quantity") * F("planned_price"),
        )
        .aggregate(total=Sum("line_revenue"))
        .get("total")
        or 0
    )
    context = {
        "total_orders": total_orders,
        "total_products": total_products,
        "total_revenue": total_revenue,
    }
    return render(request, "core/dashboard.html", context)


def account_login(request):
    if request.user.is_authenticated:
        return _post_login_redirect(request)
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields["username"].widget.attrs.update({"class": "form-control"})
    form.fields["password"].widget.attrs.update({"class": "form-control"})
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        if get_effective_role(request) == "client" and not is_email_verified(user):
            messages.info(
                request,
                "Подтвердите e-mail: вкладка 'Заказ на производство' станет доступна после подтверждения.",
            )
        next_url = _safe_next_redirect(request)
        if next_url:
            return redirect(next_url)
        return _post_login_redirect(request)
    return render(request, "core/account_login.html", {"form": form, "next_url": _safe_next_redirect(request)})


def account_register(request):
    if request.user.is_authenticated:
        return _post_login_redirect(request)
    form = UserCreationForm(request.POST or None)
    email_value = (request.POST.get("email") or "").strip().lower()
    form.fields["username"].widget.attrs.update({"class": "form-control"})
    form.fields["password1"].widget.attrs.update({"class": "form-control"})
    form.fields["password2"].widget.attrs.update({"class": "form-control"})
    if request.method == "POST":
        has_errors = False
        if not email_value:
            messages.error(request, "Укажите e-mail.")
            has_errors = True
        elif User.objects.filter(email__iexact=email_value).exists():
            messages.error(request, "Пользователь с таким e-mail уже существует.")
            has_errors = True

        if not has_errors and form.is_valid():
            user = form.save(commit=False)
            user.email = email_value
            user.save()
            verification_url = issue_email_verification(request, user)
            login(request, user)
            messages.success(
                request,
                (
                    "Аккаунт создан. Подтвердите e-mail из письма, "
                    "после этого станет доступна вкладка 'Заказ на производство'. "
                    f"Ссылка подтверждения: {verification_url}"
                ),
            )
            return redirect("catalog")
    return render(
        request,
        "core/account_register.html",
        {"form": form, "next_url": _safe_next_redirect(request), "email_value": email_value},
    )


@login_required
def account_resend_verification(request):
    if is_email_verified(request.user):
        messages.info(request, "Ваш e-mail уже подтвержден.")
        return redirect("catalog")

    verification_url = issue_email_verification(request, request.user)
    messages.success(request, f"Письмо для подтверждения e-mail отправлено повторно. Ссылка: {verification_url}")
    return redirect("catalog")


def account_verify_email(request, token):
    verification = get_object_or_404(EmailVerification, token=token)
    if verification.is_verified:
        messages.info(request, "E-mail уже был подтвержден ранее.")
        return redirect("catalog")

    verification.is_verified = True
    verification.verified_at = timezone.now()
    verification.token = uuid4().hex
    verification.save(update_fields=["is_verified", "verified_at", "token", "updated_at"])

    messages.success(request, "E-mail подтвержден. Теперь доступен заказ на производство.")
    if request.user.is_authenticated:
        return _post_login_redirect(request)
    return redirect("account_login")


def _generate_username_from_email(email: str) -> str:
    base = (email.split("@", 1)[0] if "@" in email else email).strip().lower()
    base = "".join(ch if ch.isalnum() else "_" for ch in base).strip("_")
    if not base:
        base = "user"

    username = base
    i = 1
    while User.objects.filter(username__iexact=username).exists():
        username = f"{base}{i}"
        i += 1
    return username


def account_admin_invite_accept(request, token: str):
    invite = get_object_or_404(AdminInvite, token=token, accepted_at__isnull=True)
    email_value = (invite.email or "").strip().lower()
    next_url = _safe_next_redirect(request) or "/admin/"

    if request.method == "POST":
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        if not password1 or not password2:
            messages.error(request, "Введите пароль в оба поля.")
            return render(
                request,
                "core/account_admin_invite_accept.html",
                {"invite": invite, "next_url": next_url},
            )

        if password1 != password2:
            messages.error(request, "Пароли не совпадают.")
            return render(
                request,
                "core/account_admin_invite_accept.html",
                {"invite": invite, "next_url": next_url},
            )

        # Валидация пароля по тем же правилам, что и при создании пользователя.
        temp_username = _generate_username_from_email(email_value)
        temp_user = User(username=temp_username, email=email_value)
        try:
            validate_password(password1, temp_user)
        except ValidationError as e:
            messages.error(request, e.messages[0] if getattr(e, "messages", None) else "Некорректный пароль.")
            return render(
                request,
                "core/account_admin_invite_accept.html",
                {"invite": invite, "next_url": next_url},
            )

        user = User.objects.filter(email__iexact=email_value).first()
        if user is None:
            if invite.role == AdminInvite.ROLE_SUPERUSER:
                user = User.objects.create_superuser(
                    username=temp_username,
                    email=email_value,
                    password=password1,
                )
            else:
                user = User.objects.create_user(
                    username=temp_username,
                    email=email_value,
                    password=password1,
                )
                user.is_staff = True
                user.save(update_fields=["is_staff"])
        else:
            user.set_password(password1)

        # Присваиваем права в зависимости от роли приглашения.
        if invite.role == AdminInvite.ROLE_SUPERUSER:
            user.is_staff = True
            user.is_superuser = True
        else:
            user.is_staff = True
            # Не "даунгрейдим" уже существующих суперпользователей.
        user.email = email_value
        user.save()

        # Чтобы staff/superuser гарантированно считались "email verified".
        EmailVerification.objects.update_or_create(
            user=user,
            defaults={
                "is_verified": True,
                "verified_at": timezone.now(),
                "token": uuid4().hex,
            },
        )

        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])

        login(request, user)
        messages.success(request, "Приглашение принято. Доступ в админку активирован.")
        return redirect(next_url)

    return render(
        request,
        "core/account_admin_invite_accept.html",
        {"invite": invite, "next_url": next_url},
    )


@login_required
def account_logout(request):
    logout(request)
    messages.info(request, "Вы вышли из аккаунта.")
    return redirect("catalog")


@login_required
def account_profile(request):
    profile, _created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Кабинет обновлён.")
            return redirect("account_profile")
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    return render(
        request,
        "core/account_profile.html",
        {
            "form": form,
            "profile": profile,
        },
    )


def product_list(request):
    products = Product.objects.all()
    return render(request, "core/product_list.html", {"products": products})


@login_required
def order_list(request):
    if get_effective_role(request) == "client":
        return redirect("account_orders")
    orders = (
        Order.objects.prefetch_related("items", "items__product")
        .all()
        .order_by("-created_at")
    )
    return render(request, "core/order_list.html", {"orders": orders})


def _catalog_queryset():
    return (
        Product.objects.filter(product_kind=Product.PRODUCT_KIND_GOODS)
        .exclude(name="")
        .order_by("name")
    )


def _session_cart(request):
    cart = request.session.get("store_cart")
    if not isinstance(cart, dict):
        cart = {}
    cleaned = {}
    for key, value in cart.items():
        try:
            pid = int(key)
            qty = int(value)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            cleaned[str(pid)] = qty
    if cleaned != cart:
        request.session["store_cart"] = cleaned
    return cleaned


def _cart_items(cart):
    if not cart:
        return []
    product_ids = [int(pid) for pid in cart.keys()]
    products = Product.objects.in_bulk(product_ids)
    items = []
    for pid_str, qty in cart.items():
        product = products.get(int(pid_str))
        if not product:
            continue
        price = product.planned_price or Decimal("0")
        items.append(
            {
                "product": product,
                "quantity": qty,
                "price": price,
                "line_total": price * qty,
            }
        )
    return items


def _cart_totals(items):
    total_qty = sum(item["quantity"] for item in items)
    total_amount = sum(item["line_total"] for item in items)
    return {"total_qty": total_qty, "total_amount": total_amount}


def _delivery_lead_time_text(product):
    # В MVP не показываем остатки, только ориентировочный срок поставки.
    if product.product_kind == Product.PRODUCT_KIND_SERVICE:
        return "Срок уточняется менеджером"
    if product.purchase_price:
        return "Ориентировочно 2-5 рабочих дней"
    return "Ориентировочно 1-3 рабочих дня"


def _parse_order_comment_meta(comment: str):
    meta = {}
    for chunk in (comment or "").split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            meta[key] = value
    return meta


def _append_user_marker_to_order(order: Order, user: User):
    marker = f"user_id={user.pk}"
    comment = order.comment or ""
    if marker in comment:
        return
    suffix = f"; {marker}; username={user.get_username()}"
    order.comment = f"{comment}{suffix}" if comment else marker
    order.save(update_fields=["comment"])


def _status_badge_class(status_code: str) -> str:
    return {
        Order.STATUS_NEW: "secondary",
        Order.STATUS_IN_PROGRESS: "warning",
        Order.STATUS_DONE: "success",
        Order.STATUS_CANCELLED: "danger",
    }.get(status_code, "secondary")


def catalog(request):
    query = (request.GET.get("q") or "").strip()
    sort = (request.GET.get("sort") or "name").strip()
    products_qs = _catalog_queryset()
    if query:
        products_qs = products_qs.filter(name__icontains=query)

    if sort == "price_asc":
        products_qs = products_qs.order_by("planned_price", "name")
    elif sort == "price_desc":
        products_qs = products_qs.order_by("-planned_price", "name")
    else:
        products_qs = products_qs.order_by("name")

    products = list(products_qs[:200])
    return render(
        request,
        "core/catalog.html",
        {
            "products": products,
            "query": query,
            "sort": sort,
        },
    )


def product_detail(request, product_id):
    product = get_object_or_404(_catalog_queryset(), pk=product_id)
    return render(
        request,
        "core/product_detail.html",
        {
            "product": product,
            "lead_time_text": _delivery_lead_time_text(product),
        },
    )


@login_required
def production_request_create(request):
    if get_effective_role(request) != "client":
        return redirect("order_list")
    if not is_email_verified(request.user):
        messages.warning(
            request,
            "Для создания заказа на производство подтвердите e-mail. "
            "Откройте ссылку из письма или отправьте письмо повторно.",
        )
        return redirect("account_resend_verification")

    products = _catalog_queryset()[:300]
    if request.method == "POST":
        customer_name = (request.POST.get("customer_name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        request_title = (request.POST.get("request_title") or "").strip()
        quantity_raw = (request.POST.get("quantity") or "1").strip()
        deadline_raw = (request.POST.get("deadline") or "").strip()
        product_id_raw = (request.POST.get("product_id") or "").strip()
        layout_file = request.FILES.get("layout_file")
        specs = (request.POST.get("specs") or "").strip()
        material_preferences = (request.POST.get("material_preferences") or "").strip()
        comment = (request.POST.get("comment") or "").strip()

        errors = []
        try:
            quantity = int(quantity_raw)
        except ValueError:
            quantity = 0
        if quantity <= 0:
            errors.append("Количество должно быть больше нуля.")
        if not customer_name:
            errors.append("Укажите имя или компанию.")
        if not phone:
            errors.append("Укажите телефон.")
        if not email:
            errors.append("Укажите email.")
        if not request_title:
            errors.append("Укажите наименование заказа на производство.")
        if layout_file:
            errors.extend(validate_layout_file(layout_file))

        product = None
        if product_id_raw:
            try:
                product = Product.objects.get(pk=int(product_id_raw))
            except (ValueError, Product.DoesNotExist):
                errors.append("Выбранный товар не найден.")

        deadline = None
        if deadline_raw:
            try:
                from datetime import date

                deadline = date.fromisoformat(deadline_raw)
            except ValueError:
                errors.append("Некорректная дата желаемого срока.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(
                request,
                "core/production_request_form.html",
                {
                    "products": products,
                    "form_data": request.POST,
                },
            )

        req = ProductionRequest.objects.create(
            user=request.user,
            customer_name=customer_name,
            phone=phone,
            email=email,
            request_title=request_title,
            product=product,
            quantity=quantity,
            deadline=deadline,
            layout_file=layout_file,
            specs=specs,
            material_preferences=material_preferences,
            comment=comment,
        )
        if req.layout_file:
            scan_status, _scan_result = scan_and_handle_layout_file(req)
            if scan_status == ProductionRequest.SCAN_INFECTED:
                messages.error(
                    request,
                    "Файл макета заблокирован и помещен в карантин: обнаружена потенциальная угроза.",
                )
            elif scan_status == ProductionRequest.SCAN_FAILED:
                messages.warning(
                    request,
                    "Антивирусная проверка завершилась ошибкой. Файл заблокирован политикой безопасности.",
                )
            elif scan_status == ProductionRequest.SCAN_SKIPPED:
                messages.warning(
                    request,
                    "Файл сохранен без антивирусной проверки (проверка отключена в настройках).",
                )
        messages.success(request, "Запрос на производство отправлен.")
        return redirect("production_request_success", request_id=req.pk)

    initial = {}
    if request.user.is_authenticated:
        initial = {
            "customer_name": request.user.get_full_name() or request.user.get_username(),
            "email": request.user.email or "",
        }
    return render(
        request,
        "core/production_request_form.html",
        {
            "products": products,
            "form_data": initial,
        },
    )


@login_required
def production_request_success(request, request_id):
    req = get_object_or_404(ProductionRequest, pk=request_id)
    role = get_effective_role(request)
    if role == "client" and req.user_id != request.user.pk:
        return redirect("account_production_requests")
    return render(request, "core/production_request_success.html", {"request_obj": req})


def cart_view(request):
    cart = _session_cart(request)
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "add":
            try:
                product_id = int(request.POST.get("product_id") or "0")
                quantity = int(request.POST.get("quantity") or "1")
            except ValueError:
                product_id = 0
                quantity = 1
            if product_id > 0:
                if Product.objects.filter(pk=product_id, product_kind=Product.PRODUCT_KIND_GOODS).exists():
                    key = str(product_id)
                    cart[key] = cart.get(key, 0) + max(1, quantity)
                    request.session["store_cart"] = cart
                    messages.success(request, "Товар добавлен в корзину.")
            if (request.POST.get("next") or "").strip() == "checkout":
                return redirect("checkout")
            return redirect("cart")

        if action == "remove":
            key = str(request.POST.get("product_id") or "")
            if key in cart:
                del cart[key]
                request.session["store_cart"] = cart
                messages.info(request, "Позиция удалена из корзины.")
            return redirect("cart")

        if action == "update":
            remove_id = (request.POST.get("remove_id") or "").strip()
            if remove_id:
                key = str(remove_id)
                if key in cart:
                    del cart[key]
                    request.session["store_cart"] = cart
                    messages.info(request, "Позиция удалена из корзины.")
                return redirect("cart")
            updated = {}
            for key, _val in cart.items():
                raw = request.POST.get(f"qty_{key}")
                try:
                    qty = int(raw or "0")
                except ValueError:
                    qty = 0
                if qty > 0:
                    updated[key] = qty
            request.session["store_cart"] = updated
            messages.success(request, "Корзина обновлена.")
            return redirect("cart")

    items = _cart_items(cart)
    totals = _cart_totals(items)
    return render(
        request,
        "core/cart.html",
        {
            "items": items,
            "totals": totals,
        },
    )


def checkout(request):
    cart = _session_cart(request)
    items = _cart_items(cart)
    if not items:
        messages.info(request, "Корзина пуста. Добавьте товары из каталога.")
        return redirect("catalog")

    totals = _cart_totals(items)
    checkout_token = request.session.get("checkout_token")
    submitted_tokens = request.session.get("checkout_submitted", {})
    if not isinstance(submitted_tokens, dict):
        submitted_tokens = {}
    if request.method == "GET" or not checkout_token:
        checkout_token = uuid4().hex
        request.session["checkout_token"] = checkout_token

    initial_form_data = {}
    if request.user.is_authenticated:
        initial_form_data = {
            "customer_name": request.user.get_full_name() or request.user.get_username(),
            "email": request.user.email or "",
        }

    if request.method == "POST":
        posted_token = (request.POST.get("checkout_token") or "").strip()
        if not posted_token or posted_token != checkout_token:
            messages.error(request, "Сессия оформления устарела. Попробуйте ещё раз.")
            return redirect("checkout")

        if posted_token in submitted_tokens:
            return redirect("order_success", order_id=submitted_tokens[posted_token])

        customer_name = (request.POST.get("customer_name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        email = (request.POST.get("email") or "").strip()
        payment_method = (request.POST.get("payment_method") or "").strip()
        delivery_method = (request.POST.get("delivery_method") or "").strip()
        comment = (request.POST.get("comment") or "").strip()
        agreed = (request.POST.get("agree_terms") or "").strip() == "1"
        delivery_address = (request.POST.get("delivery_address") or "").strip()
        delivery_city = (request.POST.get("delivery_city") or "").strip()
        transport_company = (request.POST.get("transport_company") or "").strip()

        errors = []
        if not customer_name:
            errors.append("Укажите имя или название компании.")
        if not phone:
            errors.append("Укажите телефон.")
        if not email:
            errors.append("Укажите email.")
        if payment_method not in {"online_card", "manager"}:
            errors.append("Выберите способ оплаты.")
        if delivery_method not in {"pickup", "courier", "transport_company"}:
            errors.append("Выберите способ доставки.")
        if delivery_method == "courier" and not delivery_address:
            errors.append("Для курьерской доставки укажите адрес.")
        if delivery_method == "transport_company" and (not delivery_city or not transport_company):
            errors.append("Для доставки ТК укажите город и транспортную компанию.")
        if not agreed:
            errors.append("Подтвердите согласие с условиями оформления заказа.")

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(
                request,
                "core/checkout.html",
                {
                    "items": items,
                    "totals": totals,
                    "checkout_token": checkout_token,
                    "form_data": request.POST,
                },
            )

        payment_display = {
            "online_card": "Онлайн картой",
            "manager": "Через менеджера / по счету",
        }.get(payment_method, payment_method)
        delivery_display = {
            "pickup": "Самовывоз",
            "courier": "Курьер",
            "transport_company": "Транспортная компания",
        }.get(delivery_method, delivery_method)

        comment_parts = [
            f"phone={phone}",
            f"email={email}",
            f"payment_method={payment_method}",
            f"delivery_method={delivery_method}",
        ]
        if request.user.is_authenticated:
            comment_parts.append(f"user_id={request.user.pk}")
            comment_parts.append(f"username={request.user.get_username()}")
        if delivery_address:
            comment_parts.append(f"delivery_address={delivery_address}")
        if delivery_city:
            comment_parts.append(f"delivery_city={delivery_city}")
        if transport_company:
            comment_parts.append(f"transport_company={transport_company}")
        if comment:
            comment_parts.append(f"client_comment={comment}")

        order = Order.objects.create(
            customer_name=customer_name,
            comment="; ".join(comment_parts),
        )
        for item in items:
            OrderItem.objects.create(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
                planned_price=item["price"],
            )

        submitted_tokens[posted_token] = order.pk
        request.session["checkout_submitted"] = submitted_tokens
        request.session["store_cart"] = {}
        request.session["checkout_token"] = ""

        request.session["checkout_summary"] = {
            "order_id": order.pk,
            "payment_display": payment_display,
            "delivery_display": delivery_display,
        }
        return redirect("order_success", order_id=order.pk)

    return render(
        request,
        "core/checkout.html",
        {
            "items": items,
            "totals": totals,
            "checkout_token": checkout_token,
            "form_data": initial_form_data,
        },
    )


def order_success(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("items", "items__product"), pk=order_id)
    summary = request.session.get("checkout_summary", {})
    if not isinstance(summary, dict) or summary.get("order_id") != order.id:
        summary = {}

    can_claim_account = not request.user.is_authenticated and bool(summary)
    if request.method == "POST" and can_claim_account:
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        errors = []
        if len(username) < 3:
            errors.append("Логин должен быть не короче 3 символов.")
        if not email:
            errors.append("Укажите email.")
        if len(password1) < 8:
            errors.append("Пароль должен быть не короче 8 символов.")
        if password1 != password2:
            errors.append("Пароли не совпадают.")
        if User.objects.filter(username__iexact=username).exists():
            errors.append("Пользователь с таким логином уже существует.")
        if User.objects.filter(email__iexact=email).exists():
            errors.append("Пользователь с таким email уже существует.")

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            user = User.objects.create_user(username=username, email=email, password=password1)
            _append_user_marker_to_order(order, user)
            login(request, user)
            messages.success(request, "Аккаунт создан. Заказ привязан к вашему профилю.")
            return redirect("account_orders")

    return render(
        request,
        "core/order_success.html",
        {
            "order": order,
            "payment_display": summary.get("payment_display", "—"),
            "delivery_display": summary.get("delivery_display", "—"),
            "can_claim_account": can_claim_account,
            "prefill_email": _parse_order_comment_meta(order.comment).get("email", ""),
        },
    )


@login_required
def account_orders(request):
    if get_effective_role(request) != "client":
        return redirect("order_list")
    marker = f"user_id={request.user.pk}"
    selected_status = (request.GET.get("status") or "").strip().upper()
    orders_qs = (
        Order.objects.filter(comment__icontains=marker)
        .prefetch_related("items", "items__product")
        .order_by("-created_at")
    )
    if selected_status in {Order.STATUS_NEW, Order.STATUS_IN_PROGRESS, Order.STATUS_DONE, Order.STATUS_CANCELLED}:
        orders_qs = orders_qs.filter(status=selected_status)
    orders = []
    for order in orders_qs:
        meta = _parse_order_comment_meta(order.comment)
        payment_label = {
            "online_card": "Онлайн картой",
            "manager": "Через менеджера / по счету",
        }.get(meta.get("payment_method"), "—")
        delivery_label = {
            "pickup": "Самовывоз",
            "courier": "Курьер",
            "transport_company": "Транспортная компания",
        }.get(meta.get("delivery_method"), "—")
        order_total = sum(
            (item.planned_price or Decimal("0")) * item.quantity
            for item in order.items.all()
        )
        orders.append(
            {
                "order": order,
                "payment_label": payment_label,
                "delivery_label": delivery_label,
                "order_total": order_total,
                "status_badge": _status_badge_class(order.status),
            }
        )
    status_filters = [
        {"code": "", "label": "Все"},
        {"code": Order.STATUS_NEW, "label": "Новые"},
        {"code": Order.STATUS_IN_PROGRESS, "label": "В работе"},
        {"code": Order.STATUS_DONE, "label": "Завершенные"},
        {"code": Order.STATUS_CANCELLED, "label": "Отмененные"},
    ]
    return render(
        request,
        "core/account_orders.html",
        {
            "orders": orders,
            "status_filters": status_filters,
            "selected_status": selected_status,
        },
    )


@login_required
def account_production_requests(request):
    if get_effective_role(request) != "client":
        return redirect("order_list")
    requests_qs = (
        ProductionRequest.objects.filter(user_id=request.user.pk)
        .select_related("product")
        .order_by("-created_at")
    )
    return render(
        request,
        "core/account_production_requests.html",
        {"requests_list": requests_qs},
    )


@login_required
def employee_production_requests(request):
    if get_effective_role(request) == "client":
        return redirect("account_production_requests")

    requests_qs = (
        ProductionRequest.objects.select_related("product", "user")
        .order_by("-created_at")
    )
    return render(
        request,
        "core/employee_production_requests.html",
        {"requests_list": requests_qs},
    )


@login_required
def employee_contracts(request):
    if get_effective_role(request) == "client":
        return redirect("catalog")
    contracts_qs = (
        Contract.objects.select_related("our_organization", "counterparty")
        .all()
        .order_by("-contract_date", "-id")
    )
    return render(request, "core/employee_contracts.html", {"contracts": contracts_qs})


@login_required
def employee_contract_create(request):
    if get_effective_role(request) == "client":
        return redirect("catalog")
    if request.method != "POST":
        return redirect("employee_contracts")

    org = Organization.objects.order_by("name").first()
    if not org:
        messages.error(request, "Сначала создайте хотя бы одну организацию/контрагента.")
        return redirect("employee_contracts")

    contract_type = (request.POST.get("contract_type") or Contract.TYPE_SUPPLIER).strip()
    if contract_type not in {code for code, _ in Contract.TYPE_CHOICES}:
        contract_type = Contract.TYPE_SUPPLIER

    now = timezone.now()
    contract = Contract.objects.create(
        number=f"Д-{now:%Y%m%d}-{now:%H%M%S}",
        contract_date=timezone.localdate(),
        contract_type=contract_type,
        status=Contract.STATUS_DRAFT,
        our_organization=org,
        counterparty=org,
    )
    messages.success(request, "Черновик договора создан.")
    return redirect("employee_contract_detail", contract_id=contract.pk)


@login_required
def employee_contract_detail(request, contract_id):
    if get_effective_role(request) == "client":
        return redirect("catalog")

    contract = get_object_or_404(
        Contract.objects.select_related("our_organization", "counterparty"),
        pk=contract_id,
    )
    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()
        if action == "generate_version":
            last_version = contract.versions.order_by("-version_number").first()
            next_version = (last_version.version_number if last_version else 0) + 1
            generated_text = (
                f"ДОГОВОР № {contract.number}\n"
                f"Дата: {contract.contract_date:%d.%m.%Y}\n"
                f"Тип: {contract.get_contract_type_display()}\n"
                f"Статус: {contract.get_status_display()}\n\n"
                f"Наша организация: {contract.our_organization.name}\n"
                f"ИНН/КПП: {contract.our_organization.inn} / {contract.our_organization.kpp}\n"
                f"Контрагент: {contract.counterparty.name}\n"
                f"ИНН/КПП: {contract.counterparty.inn} / {contract.counterparty.kpp}\n\n"
                f"Предмет: {contract.subject or '—'}\n"
                f"Условия оплаты: {contract.payment_terms or '—'}\n"
                f"Условия поставки: {contract.delivery_terms or '—'}\n"
            )
            version = ContractVersion(
                contract=contract,
                version_number=next_version,
                generated_text=generated_text,
                created_by=request.user if request.user.is_authenticated else None,
            )
            filename = f"contract_{contract.pk}_v{next_version}.txt"
            version.generated_file.save(filename, ContentFile(generated_text.encode("utf-8")), save=False)
            version.save()
            messages.success(request, f"Сгенерирована версия договора v{next_version}.")
            return redirect("employee_contract_detail", contract_id=contract.pk)

        number = (request.POST.get("number") or "").strip()
        contract_date_raw = (request.POST.get("contract_date") or "").strip()
        valid_until_raw = (request.POST.get("valid_until") or "").strip()
        contract_type = (request.POST.get("contract_type") or "").strip()
        status = (request.POST.get("status") or "").strip()
        our_org_raw = (request.POST.get("our_organization") or "").strip()
        counterparty_raw = (request.POST.get("counterparty") or "").strip()
        payment_terms = (request.POST.get("payment_terms") or "").strip()
        delivery_terms = (request.POST.get("delivery_terms") or "").strip()
        subject = (request.POST.get("subject") or "").strip()
        amount_limit_raw = (request.POST.get("amount_limit") or "").strip().replace(",", ".")
        comment = (request.POST.get("comment") or "").strip()

        errors = []
        if not number:
            errors.append("Укажите номер договора.")
        if contract_type not in {code for code, _ in Contract.TYPE_CHOICES}:
            errors.append("Выберите корректный тип договора.")
        if status not in {code for code, _ in Contract.STATUS_CHOICES}:
            errors.append("Выберите корректный статус договора.")
        try:
            contract_date = date_cls.fromisoformat(contract_date_raw)
        except ValueError:
            errors.append("Укажите корректную дату договора.")
            contract_date = None
        valid_until = None
        if valid_until_raw:
            try:
                valid_until = date_cls.fromisoformat(valid_until_raw)
            except ValueError:
                errors.append("Укажите корректную дату окончания.")
        if not our_org_raw.isdigit():
            errors.append("Выберите нашу организацию.")
        if not counterparty_raw.isdigit():
            errors.append("Выберите контрагента.")
        amount_limit = None
        if amount_limit_raw:
            try:
                amount_limit = Decimal(amount_limit_raw)
            except Exception:
                errors.append("Лимит суммы указан некорректно.")

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            contract.number = number
            contract.contract_date = contract_date
            contract.valid_until = valid_until
            contract.contract_type = contract_type
            contract.status = status
            contract.our_organization_id = int(our_org_raw)
            contract.counterparty_id = int(counterparty_raw)
            contract.payment_terms = payment_terms
            contract.delivery_terms = delivery_terms
            contract.subject = subject
            contract.amount_limit = amount_limit
            contract.comment = comment
            contract.save()
            messages.success(request, "Договор сохранен.")
            return redirect("employee_contract_detail", contract_id=contract.pk)

    orgs = Organization.objects.order_by("name")
    versions = contract.versions.select_related("created_by").all()
    return render(
        request,
        "core/employee_contract_detail.html",
        {
            "contract": contract,
            "organizations": orgs,
            "versions": versions,
            "contract_types": Contract.TYPE_CHOICES,
            "contract_statuses": Contract.STATUS_CHOICES,
        },
    )


@login_required
def employee_quarantine_files(request):
    if get_effective_role(request) == "client":
        return redirect("account_production_requests")

    if request.method == "POST":
        req_id_raw = (request.POST.get("request_id") or "").strip()
        try:
            req_id = int(req_id_raw)
        except ValueError:
            req_id = 0
        req = get_object_or_404(ProductionRequest, pk=req_id)
        scan_status, _scan_result = rescan_quarantined_layout_file(req)
        if scan_status == ProductionRequest.SCAN_CLEAN:
            messages.success(request, f"Файл заявки №{req.pk} повторно проверен и восстановлен.")
        elif scan_status == ProductionRequest.SCAN_INFECTED:
            messages.error(request, f"Повторная проверка: в заявке №{req.pk} снова обнаружена угроза.")
        elif scan_status == ProductionRequest.SCAN_FAILED:
            messages.warning(request, f"Повторная проверка заявки №{req.pk} завершилась ошибкой.")
        else:
            messages.info(request, f"Повторная проверка заявки №{req.pk}: {req.get_layout_scan_status_display()}.")
        return redirect("employee_quarantine_files")

    quarantined_qs = (
        ProductionRequest.objects.select_related("user", "product")
        .filter(
            Q(layout_is_quarantined=True)
            | Q(layout_scan_status=ProductionRequest.SCAN_INFECTED)
            | Q(layout_scan_status=ProductionRequest.SCAN_FAILED)
        )
        .order_by("-updated_at", "-created_at")
    )
    return render(
        request,
        "core/employee_quarantine_files.html",
        {"requests_list": quarantined_qs},
    )


@login_required
def production_request_detail(request, request_id):
    role = get_effective_role(request)
    request_qs = ProductionRequest.objects.select_related("product", "user")
    if role == "client":
        req = get_object_or_404(request_qs, pk=request_id, user_id=request.user.pk)
    else:
        req = get_object_or_404(request_qs, pk=request_id)
        if req.status == ProductionRequest.STATUS_NEW:
            req.status = ProductionRequest.STATUS_IN_REVIEW
            req.save(update_fields=["status", "updated_at"])

    can_manage_status = role != "client"
    if request.method == "POST" and can_manage_status:
        new_status = (request.POST.get("status") or "").strip()
        allowed_statuses = {code for code, _label in ProductionRequest.STATUS_CHOICES}
        if new_status not in allowed_statuses:
            messages.error(request, "Некорректный статус запроса.")
            return redirect("production_request_detail", request_id=req.pk)
        req.status = new_status
        req.save(update_fields=["status", "updated_at"])
        messages.success(request, "Статус запроса обновлен.")
        return redirect("production_request_detail", request_id=req.pk)

    chat_messages = req.messages.select_related("author").order_by("created_at")
    customer_invoices = (
        CustomerInvoice.objects.filter(production_request_id=req.pk)
        .exclude(status=CustomerInvoice.STATUS_CANCELLED)
        .order_by("-created_at")
    )
    default_issue_date = timezone.localdate()
    # Срок оплаты по умолчанию: +5 рабочих дней от даты счёта.
    default_due_date = default_issue_date
    added = 0
    while added < 5:
        default_due_date += timedelta(days=1)
        if default_due_date.weekday() < 5:
            added += 1
    return render(
        request,
        "core/production_request_detail.html",
        {
            "request_obj": req,
            "chat_messages": chat_messages,
            "customer_invoices": customer_invoices,
            "status_choices": ProductionRequest.STATUS_CHOICES,
            "can_manage_status": can_manage_status,
            "is_client_view": role == "client",
            "our_organizations": Organization.objects.filter(is_buyer=True).order_by("name"),
            "default_issue_date": default_issue_date.strftime("%d.%m.%Y"),
            "default_due_date": default_due_date.strftime("%d.%m.%Y"),
        },
    )


@login_required
def production_request_issue_invoice(request, request_id):
    if request.method != "POST":
        return redirect("production_request_detail", request_id=request_id)
    role = get_effective_role(request)
    if role == "client":
        return HttpResponseForbidden("Недостаточно прав")

    req = get_object_or_404(ProductionRequest.objects.select_related("user"), pk=request_id)
    amount_raw = (request.POST.get("amount") or "").strip().replace(",", ".")
    issue_date_raw = (request.POST.get("issue_date") or "").strip()
    due_date_raw = (request.POST.get("due_date") or "").strip()
    our_org_raw = (request.POST.get("our_organization_id") or "").strip()
    purpose = (request.POST.get("purpose") or "").strip()
    if not purpose:
        purpose = f"Оплата по заявке на производство №{req.pk}"

    try:
        amount = Decimal(amount_raw)
    except Exception:
        messages.error(request, "Укажите корректную сумму счёта.")
        return redirect("production_request_detail", request_id=req.pk)
    if amount <= 0:
        messages.error(request, "Сумма счёта должна быть больше нуля.")
        return redirect("production_request_detail", request_id=req.pk)

    issue_date = timezone.localdate()
    if issue_date_raw:
        try:
            issue_date = _parse_ru_date(issue_date_raw)
        except ValueError:
            messages.error(request, "Некорректная дата счёта. Используйте формат ДД.ММ.ГГГГ.")
            return redirect("production_request_detail", request_id=req.pk)

    due_date = None
    if due_date_raw:
        try:
            due_date = _parse_ru_date(due_date_raw)
        except ValueError:
            messages.error(request, "Некорректная дата оплаты. Используйте формат ДД.ММ.ГГГГ.")
            return redirect("production_request_detail", request_id=req.pk)

    if not our_org_raw.isdigit():
        messages.error(request, "Выберите нашу организацию для подстановки реквизитов.")
        return redirect("production_request_detail", request_id=req.pk)
    org = (
        Organization.objects.filter(pk=int(our_org_raw), is_buyer=True)
        .only("id", "name", "inn", "kpp", "bank_account", "bank_name", "bank_bik", "bank_corr_account")
        .first()
    )
    if not org:
        messages.error(request, "Выбранная организация не найдена.")
        return redirect("production_request_detail", request_id=req.pk)
    missing = []
    if not (org.bank_name or "").strip():
        missing.append("Банк")
    if not (org.bank_bik or "").strip():
        missing.append("БИК")
    if not (org.bank_account or "").strip():
        missing.append("Расчётный счёт")

    invoice = CustomerInvoice.objects.create(
        production_request=req,
        customer_name=req.customer_name,
        customer_email=req.email or "",
        customer_phone=req.phone or "",
        our_organization=org,
        issue_date=issue_date,
        amount=amount,
        due_date=due_date,
        purpose=purpose,
        status=CustomerInvoice.STATUS_DRAFT,
        created_by=request.user if request.user.is_authenticated else None,
    )

    # Для одной заявки оставляем один актуальный неоплаченный счёт:
    # прошлые черновики/отправленные помечаем как отменённые уже ПОСЛЕ успешного создания нового.
    CustomerInvoice.objects.filter(
        production_request_id=req.pk,
        status__in=[CustomerInvoice.STATUS_DRAFT, CustomerInvoice.STATUS_SENT],
    ).exclude(pk=invoice.pk).update(status=CustomerInvoice.STATUS_CANCELLED)

    if missing:
        messages.warning(
            request,
            "Счёт создан, но у выбранной организации не заполнены реквизиты: "
            + ", ".join(missing)
            + ". Заполните их, чтобы печатная форма и QR были корректными.",
        )
    messages.success(request, f"Счёт №{invoice.number} сформирован. Проверьте и отправьте клиенту из карточки счёта.")
    return redirect("customer_invoice_detail", invoice_id=invoice.pk)


@login_required
def customer_invoice_detail(request, invoice_id):
    role = get_effective_role(request)
    invoice_qs = CustomerInvoice.objects.select_related("production_request", "our_organization")
    if role == "client":
        invoice = get_object_or_404(invoice_qs, pk=invoice_id, production_request__user_id=request.user.pk)
    else:
        invoice = get_object_or_404(invoice_qs, pk=invoice_id)
    return render(
        request,
        "core/customer_invoice_detail.html",
        {
            "invoice": invoice,
            "can_manage_invoice": role != "client",
        },
    )


@login_required
def customer_invoice_print(request, invoice_id):
    role = get_effective_role(request)
    invoice_qs = CustomerInvoice.objects.select_related("production_request", "our_organization")
    if role == "client":
        invoice = get_object_or_404(invoice_qs, pk=invoice_id, production_request__user_id=request.user.pk)
    else:
        invoice = get_object_or_404(invoice_qs, pk=invoice_id)

    quantity = 1
    item_name = "Услуги/работы по заказу"
    if invoice.production_request_id:
        quantity = max(1, invoice.production_request.quantity or 1)
        item_name = invoice.production_request.request_title or item_name
    unit_price = (invoice.amount / Decimal(quantity)).quantize(Decimal("0.01"))
    vat_note = "Без НДС (АУСН)"
    qr_payload, qr_data_url = build_russian_payment_qr_data_url(invoice)

    return render(
        request,
        "core/customer_invoice_print.html",
        {
            "invoice": invoice,
            "item_name": item_name,
            "quantity": quantity,
            "unit_price": unit_price,
            "vat_note": vat_note,
            "now_dt": timezone.localtime(),
            "qr_payload": qr_payload,
            "qr_data_url": qr_data_url,
        },
    )


@login_required
def customer_invoice_mark_paid(request, invoice_id):
    if request.method != "POST":
        return redirect("customer_invoice_detail", invoice_id=invoice_id)
    role = get_effective_role(request)
    if role == "client":
        return HttpResponseForbidden("Недостаточно прав")

    invoice = get_object_or_404(CustomerInvoice.objects.select_related("production_request"), pk=invoice_id)
    if invoice.status != CustomerInvoice.STATUS_PAID:
        invoice.status = CustomerInvoice.STATUS_PAID
        invoice.save(update_fields=["status", "updated_at"])
        if invoice.production_request_id:
            ProductionRequestMessage.objects.create(
                production_request=invoice.production_request,
                author=request.user,
                is_employee_message=True,
                text=f"Оплата по счёту №{invoice.number} подтверждена менеджером.",
            )
        messages.success(request, "Счёт отмечен как оплаченный.")
    else:
        messages.info(request, "Счёт уже имеет статус «Оплачен».")
    return redirect("customer_invoice_detail", invoice_id=invoice.pk)


@login_required
def customer_invoice_send_to_chat(request, invoice_id):
    if request.method != "POST":
        return redirect("customer_invoice_detail", invoice_id=invoice_id)
    role = get_effective_role(request)
    if role == "client":
        return HttpResponseForbidden("Недостаточно прав")

    invoice = get_object_or_404(CustomerInvoice.objects.select_related("production_request"), pk=invoice_id)
    if not invoice.production_request_id:
        messages.error(request, "Этот счёт не привязан к заявке, отправка в чат недоступна.")
        return redirect("customer_invoice_detail", invoice_id=invoice.pk)
    if invoice.status == CustomerInvoice.STATUS_PAID:
        messages.info(request, "Счёт уже оплачен.")
        return redirect("customer_invoice_detail", invoice_id=invoice.pk)
    if invoice.status == CustomerInvoice.STATUS_SENT:
        messages.info(request, "Счёт уже отправлен клиенту в чат.")
        return redirect("customer_invoice_detail", invoice_id=invoice.pk)

    invoice.status = CustomerInvoice.STATUS_SENT
    invoice.sent_to_chat_at = timezone.now()
    invoice.save(update_fields=["status", "sent_to_chat_at", "updated_at"])

    invoice_url = request.build_absolute_uri(reverse("customer_invoice_print", args=[invoice.pk]))
    ProductionRequestMessage.objects.create(
        production_request=invoice.production_request,
        author=request.user,
        is_employee_message=True,
        text=(
            f"Выставлен счёт на оплату №{invoice.number} на сумму {invoice.amount} руб.\n"
            f"Печатная форма счёта: {invoice_url}"
        ),
    )
    messages.success(request, "Печатная форма счёта отправлена клиенту в мини-чат.")
    return redirect("customer_invoice_detail", invoice_id=invoice.pk)


@login_required
def production_request_add_message(request, request_id):
    if request.method != "POST":
        if get_effective_role(request) == "client":
            return redirect("account_production_requests")
        return redirect("employee_production_requests")

    text = (request.POST.get("text") or "").strip()
    role = get_effective_role(request)
    next_url = _safe_next_redirect(request)

    request_qs = ProductionRequest.objects.select_related("user")
    if role == "client":
        req = get_object_or_404(request_qs, pk=request_id, user_id=request.user.pk)
        redirect_name = "account_production_requests"
    else:
        req = get_object_or_404(request_qs, pk=request_id)
        redirect_name = "employee_production_requests"

    if not text:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Введите сообщение в чат."}, status=400)
        messages.error(request, "Введите сообщение в чат.")
        if next_url:
            return redirect(next_url)
        return redirect(redirect_name)

    ProductionRequestMessage.objects.create(
        production_request=req,
        author=request.user,
        is_employee_message=(role != "client"),
        text=text,
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, "Сообщение отправлено.")
    if next_url:
        return redirect(next_url)
    return redirect(redirect_name)


@login_required
def production_request_chat_messages(request, request_id):
    role = get_effective_role(request)
    request_qs = ProductionRequest.objects.select_related("user")
    if role == "client":
        req = get_object_or_404(request_qs, pk=request_id, user_id=request.user.pk)
    else:
        req = get_object_or_404(request_qs, pk=request_id)

    messages_qs = req.messages.select_related("author").order_by("created_at")
    payload = []
    now = timezone.now()
    for msg in messages_qs:
        is_within_edit_window = (now - msg.created_at) <= timedelta(minutes=3)
        if role == "client":
            author_label = "Менеджер" if msg.is_employee_message else "Вы"
            can_edit = (msg.author_id == request.user.pk) and (not msg.is_employee_message) and is_within_edit_window
        else:
            author_label = (
                (msg.author.get_username() if msg.author_id else "Сотрудник")
                if msg.is_employee_message
                else "Клиент"
            )
            can_edit = (msg.author_id == request.user.pk) and msg.is_employee_message and is_within_edit_window
        payload.append(
            {
                "id": msg.pk,
                "created_at": timezone.localtime(msg.created_at).strftime("%d.%m.%Y %H:%M"),
                "author_label": author_label,
                "text": msg.text,
                "can_edit": can_edit,
                "edit_url": request.build_absolute_uri(
                    f"/production-request/{req.pk}/chat/messages/{msg.pk}/edit/"
                ),
            }
        )
    return JsonResponse({"messages": payload})


@login_required
def production_request_edit_message(request, request_id, message_id):
    if request.method != "POST":
        return HttpResponseForbidden("Method not allowed")

    role = get_effective_role(request)
    next_url = _safe_next_redirect(request)
    request_qs = ProductionRequest.objects.select_related("user")
    if role == "client":
        req = get_object_or_404(request_qs, pk=request_id, user_id=request.user.pk)
        redirect_name = "account_production_requests"
    else:
        req = get_object_or_404(request_qs, pk=request_id)
        redirect_name = "employee_production_requests"

    msg = get_object_or_404(
        ProductionRequestMessage.objects.select_related("production_request"),
        pk=message_id,
        production_request_id=req.pk,
    )
    can_edit = msg.author_id == request.user.pk and (
        (role == "client" and not msg.is_employee_message)
        or (role != "client" and msg.is_employee_message)
    )
    is_within_edit_window = (timezone.now() - msg.created_at) <= timedelta(minutes=3)
    if can_edit and not is_within_edit_window:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"ok": False, "error": "Редактирование доступно только в течение 3 минут после отправки."},
                status=403,
            )
        return HttpResponseForbidden("Edit window expired")
    if not can_edit:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Редактировать можно только свои сообщения."}, status=403)
        return HttpResponseForbidden("You can edit only your own message")

    text = (request.POST.get("text") or "").strip()
    if not text:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Текст сообщения не должен быть пустым."}, status=400)
        messages.error(request, "Текст сообщения не должен быть пустым.")
        if next_url:
            return redirect(next_url)
        return redirect(redirect_name)

    msg.text = text
    msg.save(update_fields=["text"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, "Сообщение обновлено.")
    if next_url:
        return redirect(next_url)
    return redirect(redirect_name)


@login_required
def account_order_detail(request, order_id):
    marker = f"user_id={request.user.pk}"
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "items__product"),
        pk=order_id,
        comment__icontains=marker,
    )
    meta = _parse_order_comment_meta(order.comment)
    payment_label = {
        "online_card": "Онлайн картой",
        "manager": "Через менеджера / по счету",
    }.get(meta.get("payment_method"), "—")
    delivery_label = {
        "pickup": "Самовывоз",
        "courier": "Курьер",
        "transport_company": "Транспортная компания",
    }.get(meta.get("delivery_method"), "—")
    line_items = []
    order_total = Decimal("0")
    for item in order.items.all():
        line_total = (item.planned_price or Decimal("0")) * item.quantity
        order_total += line_total
        line_items.append({"item": item, "line_total": line_total})
    return render(
        request,
        "core/account_order_detail.html",
        {
            "order": order,
            "payment_label": payment_label,
            "delivery_label": delivery_label,
            "order_total": order_total,
            "meta": meta,
            "line_items": line_items,
            "status_badge": _status_badge_class(order.status),
        },
    )


@login_required
def account_repeat_order(request, order_id):
    if request.method != "POST":
        return redirect("account_order_detail", order_id=order_id)
    if get_effective_role(request) != "client":
        return redirect("order_list")
    marker = f"user_id={request.user.pk}"
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
        comment__icontains=marker,
    )
    cart = _session_cart(request)
    for item in order.items.all():
        key = str(item.product_id)
        cart[key] = cart.get(key, 0) + int(item.quantity)
    request.session["store_cart"] = cart
    messages.success(request, f"Позиции из заказа №{order.id} добавлены в корзину.")
    return redirect("cart")


@login_required
def set_storefront_preview_role(request, role):
    if not can_preview_roles(request.user):
        return _post_login_redirect(request)

    if role == "reset":
        request.session.pop(ROLE_PREVIEW_SESSION_KEY, None)
    elif role in ALLOWED_PREVIEW_ROLES:
        request.session[ROLE_PREVIEW_SESSION_KEY] = role

    next_url = (request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return _post_login_redirect(request)


@login_required
def my_work(request):
    """
    Страница сотрудника: трудозатраты и заработок.
    Доступна если у пользователя привязан сотрудник (Employee).
    """
    try:
        employee = request.user.employee
    except (Employee.DoesNotExist, AttributeError):
        return render(request, "core/my_work.html", {"employee": None})
    all_logs = LaborTimeLog.objects.filter(employee=employee)
    total_minutes = all_logs.aggregate(s=Sum("minutes_spent"))["s"] or Decimal("0")
    total_earnings = Decimal("0")
    for log in all_logs.select_related("operation_type"):
        rate = employee.hourly_rate or (log.operation_type.hourly_rate or 0)
        total_earnings += (log.minutes_spent / Decimal("60")) * rate
    total_earnings = total_earnings.quantize(Decimal("0.01"))
    logs = (
        LaborTimeLog.objects.filter(employee=employee)
        .select_related("operation_type", "production_assignment", "production_assignment_item", "batch")
        .order_by("-date")
    )[:100]
    return render(
        request,
        "core/my_work.html",
        {
            "employee": employee,
            "logs": logs,
            "total_minutes": total_minutes,
            "total_earnings": total_earnings,
        },
    )
