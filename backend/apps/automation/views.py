"""Страница правил автоматизации (PLAN-013, T-13040)."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.views.common import flash, render_page

from .forms import RuleActionFormSet, RuleForm
from .models import Rule
from .services import access, journal, validation
from .services import tick


def _rule_or_404(user, pk):
    rule = Rule.objects.filter(pk=pk).prefetch_related("actions").first()
    if rule is None:
        raise Http404
    if not access.can_manage(user, rule):
        raise PermissionDenied
    return rule


@login_required
def rules_list(request):
    if not access.can_view_page(request.user):
        raise PermissionDenied
    rules = access.visible_rules(request.user).select_related("author", "queue").prefetch_related("actions")
    return render_page(request, "automation/list.html", {"rules": rules, "nav_active": "automation"})


@login_required
@require_http_methods(["GET", "POST"])
def rule_new(request):
    if not access.can_view_page(request.user):
        raise PermissionDenied
    form = RuleForm(request.POST or None)
    formset = RuleActionFormSet(request.POST or None)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                rule = form.save(commit=False)
                rule.author = request.user
                rule.save()
                if not access.can_manage(request.user, rule):
                    raise validation.RuleError("no_access", "Нельзя настроить правило этой области")
                formset.instance = rule
                formset.save()
                validation.validate_rule(rule)
                journal.rule_changed(rule, "automation.rule_created", actor=request.user)
                if not rule.enabled:
                    tick.cancel_rule(rule)
        except validation.RuleError as exc:
            form.add_error(None, exc.message)
        else:
            flash(request, "Правило создано")
            return HttpResponseRedirect("/automation/")
    return render_page(request, "automation/form.html", {"form": form, "formset": formset, "nav_active": "automation"})


@login_required
@require_http_methods(["GET", "POST"])
def rule_edit(request, pk: int):
    rule = _rule_or_404(request.user, pk)
    form = RuleForm(request.POST or None, instance=rule)
    formset = RuleActionFormSet(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                rule = form.save()
                formset.instance = rule
                formset.save()
                validation.validate_rule(rule)
                journal.rule_changed(rule, "automation.rule_updated", actor=request.user)
                if not rule.enabled:
                    tick.cancel_rule(rule)
        except validation.RuleError as exc:
            form.add_error(None, exc.message)
        else:
            flash(request, "Правило сохранено")
            return HttpResponseRedirect("/automation/")
    return render_page(request, "automation/form.html", {"form": form, "formset": formset, "rule": rule,
                                                         "nav_active": "automation"})


@login_required
@require_POST
def rule_toggle(request, pk: int):
    rule = _rule_or_404(request.user, pk)
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled", "updated_at"])
    if not rule.enabled:
        tick.cancel_rule(rule)
    journal.rule_changed(rule, "automation.rule_enabled" if rule.enabled else "automation.rule_disabled",
                         actor=request.user)
    flash(request, "Правило включено" if rule.enabled else "Правило выключено")
    return HttpResponseRedirect("/automation/")


@login_required
def runs(request):
    if not access.can_view_page(request.user):
        raise PermissionDenied
    from .models import RuleActionRun

    visible = access.visible_rules(request.user).values_list("pk", flat=True)
    rows = RuleActionRun.objects.filter(run__rule_id__in=visible).select_related("run", "run__rule").order_by(
        "-run__created_at", "run", "order")[:200]
    return render_page(request, "automation/runs.html", {"rows": rows, "nav_active": "automation"})
