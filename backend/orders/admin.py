from collections import Counter

from django.contrib import admin, messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils.html import format_html

from .models import Order, OrderItem
from .services import (
    OrderTransitionError,
    cancel_and_restore,
    collect_and_complete as collect_and_complete_order,
    complete_order,
    confirm_payment,
    dispatch_or_ready,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "variant",
        "product_name",
        "variant_name",
        "unit_price",
        "quantity",
        "line_total",
    )


def _run_transition(request, queryset, transition, success_label):
    changed = 0
    unchanged = 0
    errors = Counter()
    for order_id in queryset.values_list("pk", flat=True):
        try:
            result = transition(order_id)
        except OrderTransitionError as exc:
            errors[str(exc)] += 1
        else:
            if result.changed:
                changed += 1
            else:
                unchanged += 1
    if changed:
        messages.success(request, f"{changed} orden(es) {success_label}.")
    if unchanged:
        messages.info(request, f"{unchanged} orden(es) ya estaban en ese estado.")
    for reason, count in errors.items():
        messages.error(request, f"{count} orden(es) no se modificaron: {reason}")


@admin.action(description="Confirmar pago y avisar al cliente", permissions=["change"])
def mark_paid(modeladmin, request, queryset):
    _run_transition(request, queryset, confirm_payment, "marcadas como pagadas")


@admin.action(
    description="Despachar / dejar listas para retirar y avisar", permissions=["change"]
)
def mark_dispatched(modeladmin, request, queryset):
    _run_transition(
        request, queryset, dispatch_or_ready, "actualizadas para la entrega"
    )


@admin.action(description="Marcar como entregadas / retiradas", permissions=["change"])
def mark_completed(modeladmin, request, queryset):
    _run_transition(request, queryset, complete_order, "completadas")


@admin.action(description="Cobrar y completar", permissions=["change"])
def collect_and_complete(modeladmin, request, queryset):
    _run_transition(
        request,
        queryset,
        collect_and_complete_order,
        "cobradas y completadas",
    )


@admin.action(description="Cancelar y devolver stock", permissions=["change"])
def cancel_and_restore_stock(modeladmin, request, queryset):
    _run_transition(request, queryset, cancel_and_restore, "canceladas")


class SituationFilter(admin.SimpleListFilter):
    title = "situación"
    parameter_name = "situacion"

    def lookups(self, request, model_admin):
        return (
            ("cobro_pendiente", "Cobro pendiente"),
            ("preparar", "Para preparar"),
            ("en_curso", "En camino / listas para retirar"),
            ("completada", "Completadas"),
            ("revision", "Requieren revisión"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "cobro_pendiente":
            return queryset.filter(payment_status="pending").exclude(
                fulfillment_status="cancelled"
            )
        if value == "preparar":
            return queryset.filter(fulfillment_status="pending").filter(
                Q(payment_status="approved")
                | Q(payment_method="cod", payment_status="pending")
            )
        if value == "en_curso":
            return queryset.filter(
                fulfillment_status__in=("shipped", "ready_for_pickup")
            )
        if value == "completada":
            return queryset.filter(fulfillment_status="completed")
        if value == "revision":
            return queryset.filter(
                payment_status__in=(
                    "review",
                    "rejected",
                    "refunded",
                    "partially_refunded",
                    "charged_back",
                )
            )
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    change_form_template = "admin/orders/order/change_form.html"
    list_display = (
        "id",
        "created_at",
        "full_name",
        "situation_badge",
        "payment_badge",
        "fulfillment_badge",
        "payment_method",
        "delivery_method",
        "payment_discount_percent",
        "payment_discount_amount",
        "total_amount",
        "mp_refunded_amount",
    )
    list_filter = (
        SituationFilter,
        "payment_status",
        "fulfillment_status",
        "payment_method",
        "delivery_method",
        "created_at",
    )
    date_hierarchy = "created_at"
    search_fields = (
        "full_name",
        "email",
        "mp_preference_id",
        "mp_payment_id",
        "pickup_point_label",
    )
    readonly_fields = (
        "situation_summary",
        "payment_status",
        "fulfillment_status",
        "completed_at",
        "payment_discount_percent",
        "payment_discount_amount",
        "mp_refunded_amount",
        "mp_preference_id",
        "mp_payment_id",
        "mp_status",
        "stock_deducted",
        "stock_restored",
        "confirmation_email_sent",
        "paid_email_sent",
        "shipped_email_sent",
        "completion_email_sent",
    )
    fieldsets = (
        (
            "Situación de la orden",
            {
                "fields": (
                    "situation_summary",
                    "payment_status",
                    "fulfillment_status",
                    "completed_at",
                )
            },
        ),
        (
            "Datos generales",
            {"fields": ("created_at", "payment_method", "delivery_method")},
        ),
        ("Cliente", {"fields": ("full_name", "email", "phone")}),
        (
            "Entrega",
            {
                "fields": (
                    "pickup_point",
                    "pickup_point_label",
                    "address_line",
                    "address_extra",
                    "city",
                    "postal_code",
                    "shipping_cost",
                    "shipping_zone",
                    "shipping_carrier_arranged",
                )
            },
        ),
        (
            "Importes",
            {
                "fields": (
                    "payment_discount_percent",
                    "payment_discount_amount",
                    "total_amount",
                    "mp_refunded_amount",
                )
            },
        ),
        (
            "Mercado Pago",
            {"fields": ("mp_preference_id", "mp_payment_id", "mp_status")},
        ),
        (
            "Control interno",
            {
                "classes": ("collapse",),
                "fields": (
                    "stock_deducted",
                    "stock_restored",
                    "confirmation_email_sent",
                    "paid_email_sent",
                    "shipped_email_sent",
                    "completion_email_sent",
                ),
            },
        ),
    )
    inlines = [OrderItemInline]
    actions = [
        mark_paid,
        mark_dispatched,
        mark_completed,
        collect_and_complete,
        cancel_and_restore_stock,
    ]

    _FORM_TRANSITIONS = {
        "_mark_paid": (confirm_payment, "Pago confirmado."),
        "_mark_dispatched": (dispatch_or_ready, "Entrega actualizada."),
        "_mark_completed": (complete_order, "Orden completada."),
        "_collect_and_complete": (
            collect_and_complete_order,
            "Pago y entrega completados.",
        ),
    }

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and (
            obj.payment_status != "pending" or obj.fulfillment_status != "pending"
        ):
            fields.extend(["payment_method", "delivery_method"])
        return tuple(dict.fromkeys(fields))

    def render_change_form(self, request, context, *args, **kwargs):
        order = context.get("original")
        buttons = []
        if order and self.has_change_permission(request, order):
            active = (
                order.fulfillment_status != "cancelled"
                and order.payment_status
                not in {
                    "cancelled",
                    "review",
                    "rejected",
                    "refunded",
                    "partially_refunded",
                    "charged_back",
                }
            )
            if (
                active
                and order.payment_method != "mp"
                and order.payment_status == "pending"
            ):
                buttons.append(("_mark_paid", "Confirmar pago"))
                buttons.append(("_collect_and_complete", "Cobrar y completar"))
            can_dispatch = order.payment_status == "approved" or (
                order.payment_method == "cod" and order.payment_status == "pending"
            )
            if active and order.fulfillment_status == "pending" and can_dispatch:
                label = (
                    "Dejar listo para retirar"
                    if order.delivery_method == "pickup"
                    else "Marcar como despachado"
                )
                buttons.append(("_mark_dispatched", label))
            if (
                active
                and order.payment_status == "approved"
                and order.fulfillment_status != "completed"
            ):
                label = (
                    "Marcar como retirado"
                    if order.delivery_method == "pickup"
                    else "Marcar como entregado"
                )
                buttons.append(("_mark_completed", label))
        context["order_transition_buttons"] = buttons
        return super().render_change_form(request, context, *args, **kwargs)

    def response_change(self, request, obj):
        for key, (transition, success_message) in self._FORM_TRANSITIONS.items():
            if key not in request.POST:
                continue
            try:
                result = transition(obj.pk)
            except OrderTransitionError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                message = (
                    success_message
                    if result.changed
                    else "La orden ya estaba en ese estado."
                )
                self.message_user(request, message, level=messages.SUCCESS)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    @admin.display(description="Situación")
    def situation_badge(self, obj):
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.situation_tone,
            obj.situation_label,
        )

    @admin.display(description="Situación actual")
    def situation_summary(self, obj):
        if obj is None:
            return "Se definirá al crear la orden."
        return self.situation_badge(obj)

    @admin.display(description="Pago", ordering="payment_status")
    def payment_badge(self, obj):
        label = obj.get_payment_status_display()
        if obj.payment_status == "review" and not obj.stock_deducted:
            label = "REINTEGRO REQUERIDO"
        elif obj.payment_status == "review":
            label = "REVISIÓN DE PAGO"
        elif obj.payment_status == "refunded":
            label = "REINTEGRADO"
        elif obj.payment_status == "partially_refunded":
            label = "REINTEGRO PARCIAL"
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.payment_status,
            label,
        )

    @admin.display(description="Entrega", ordering="fulfillment_status")
    def fulfillment_badge(self, obj):
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.fulfillment_status,
            obj.fulfillment_label,
        )
