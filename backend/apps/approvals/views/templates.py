"""Страницы шаблонов согласования (PLAN-014, T-14013)."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.views.common import flash, render_page

from ..forms import TemplateForm
from ..models import ApprovalTemplate
from ..services import access, templates
from ..services.errors import ApprovalError


def _template_or_404(user, pk):
    template = ApprovalTemplate.objects.filter(pk=pk).prefetch_related("stages__participants").first()
    if template is None:
        raise Http404
    if not access.can_manage_templates(user):
        raise PermissionDenied
    return template


@login_required
def templates_list(request):
    if not access.can_manage_templates(request.user):
        raise PermissionDenied
    rows = ApprovalTemplate.objects.select_related("author").prefetch_related("stages").order_by(
        "subject_type", "name")
    return render_page(request, "approvals/templates/list.html", {"templates": rows, "nav_active": "approvals"})


@login_required
@require_http_methods(["GET", "POST"])
def template_new(request):
    if not access.can_manage_templates(request.user):
        raise PermissionDenied
    form = TemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            template = form.save(commit=False)
            template.author = request.user
            templates.save_template(template, actor=request.user, stages=form.cleaned_data["stages_text"])
        except ApprovalError as error:
            form.add_error(None, error.message)
        else:
            flash(request, "Шаблон создан")
            return HttpResponseRedirect("/approvals/")
    return render_page(request, "approvals/templates/form.html", {"form": form, "nav_active": "approvals"})


@login_required
@require_http_methods(["GET", "POST"])
def template_edit(request, pk: int):
    template = _template_or_404(request.user, pk)
    form = TemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        try:
            template = form.save(commit=False)
            template.save()
            templates.save_template(template, actor=request.user, stages=form.cleaned_data["stages_text"])
        except ApprovalError as error:
            form.add_error(None, error.message)
        else:
            flash(request, "Шаблон сохранён")
            return HttpResponseRedirect("/approvals/")
    return render_page(request, "approvals/templates/form.html",
                       {"form": form, "template": template, "nav_active": "approvals"})


@login_required
@require_POST
def template_toggle(request, pk: int):
    template = _template_or_404(request.user, pk)
    templates.set_enabled(template, not template.enabled, actor=request.user)
    flash(request, "Шаблон включён" if template.enabled else "Шаблон выключен")
    return HttpResponseRedirect("/approvals/")
