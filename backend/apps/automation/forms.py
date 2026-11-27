"""Формы правил автоматизации (PLAN-013, T-13040)."""
import json

from django import forms
from django.forms import inlineformset_factory

from .action_registry import ACTIONS
from .models import Rule, RuleAction
from .services.validation import TRIGGERS


TRIGGER_LABELS = {"ticket_created": "Заявка создана", "reply_received": "Ответ заявителя",
                  "ticket_field_changed": "Изменено поле заявки", "ticket_status_changed": "Изменён статус заявки",
                  "ticket_transferred": "Заявка передана", "ticket_closed": "Заявка закрыта",
                  "sla_threshold": "Порог SLA", "task_created": "Задача создана",
                  "task_field_changed": "Изменено поле задачи", "task_status_changed": "Изменён статус задачи",
                  "task_threshold": "Порог срока задачи",
                  "approval_started": "Согласование запущено", "approval_stage_completed": "Этап согласования завершён",
                  "approval_completed": "Маршрут согласован", "approval_rejected": "Маршрут отклонён",
                  "approval_returned": "Маршрут возвращён", "approval_cancelled": "Маршрут отменён"}
ACTION_LABELS = {code: title for code, title, _ in ACTIONS}


def _action_choices() -> list[tuple[str, str]]:
    from apps.automation import extensions

    choices = {code: title for code, title in ACTION_LABELS.items()}
    for descriptor in extensions.actions().values():
        choices[descriptor.code] = descriptor.title
    return list(choices.items())



def _bootstrap(form) -> None:
    from django import forms as dj_forms

    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, dj_forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, dj_forms.Select):
            widget.attrs.setdefault("class", "form-select")
        else:
            widget.attrs.setdefault("class", "form-control")

class RuleForm(forms.ModelForm):
    trigger = forms.ChoiceField(label="Событие", choices=[
        (code, TRIGGER_LABELS.get(code, code)) for codes in TRIGGERS.values() for code in sorted(codes)])
    conditions_text = forms.CharField(label="Условия (JSON)", required=False, widget=forms.Textarea(attrs={"rows": 3}),
                                      help_text='Список [{"field": "...", "op": "=", "value": ...}]')

    class Meta:
        model = Rule
        fields = ("name", "subject_type", "scope", "queue", "trigger", "priority", "enabled")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.servicedesk.services import queues

        self.fields["trigger"].choices = [
            (code, TRIGGER_LABELS.get(code, code))
            for codes in TRIGGERS.values() for code in sorted(codes)]
        self.fields["queue"].choices = [("", "—")] + [(unit.id, unit.name) for unit in queues.marked_units()]
        _bootstrap(self)
        if self.instance and self.instance.pk and not self.is_bound:
            self.fields["conditions_text"].initial = json.dumps(self.instance.conditions, ensure_ascii=False)

    def clean_conditions_text(self):
        raw = (self.cleaned_data.get("conditions_text") or "").strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Условия должны быть JSON-списком")
        if not isinstance(value, list):
            raise forms.ValidationError("Условия должны быть списком")
        return value

    def save(self, commit=True):
        rule = super().save(commit=False)
        rule.conditions = self.cleaned_data.get("conditions_text") or []
        if commit:
            rule.save()
        return rule


class RuleActionForm(forms.ModelForm):
    kind = forms.ChoiceField(label="Действие", choices=[(code, title) for code, title in ACTION_LABELS.items()])
    params_text = forms.CharField(label="Параметры (JSON)", required=False,
                                  widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = RuleAction
        fields = ("order", "kind", "delay_seconds")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = _action_choices()
        _bootstrap(self)
        if self.instance and self.instance.pk and not self.is_bound:
            self.fields["params_text"].initial = json.dumps(self.instance.params, ensure_ascii=False)

    def clean_params_text(self):
        raw = (self.cleaned_data.get("params_text") or "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Параметры должны быть JSON-объектом")
        if not isinstance(value, dict):
            raise forms.ValidationError("Параметры должны быть объектом")
        return value

    def save(self, commit=True):
        action = super().save(commit=False)
        action.params = self.cleaned_data.get("params_text") or {}
        if commit:
            action.save()
        return action


RuleActionFormSet = inlineformset_factory(Rule, RuleAction, form=RuleActionForm, extra=1, can_delete=True)
