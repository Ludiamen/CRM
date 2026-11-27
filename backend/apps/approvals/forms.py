"""Формы шаблона согласования (PLAN-014, T-14013)."""
import json

from django import forms

from .models import ApprovalTemplate


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


class TemplateForm(forms.ModelForm):
    stages_text = forms.CharField(
        label="Этапы (JSON)", required=True, widget=forms.Textarea(attrs={"rows": 12}),
        help_text='[{"title": "...", "mode": "sequential", "rule": "all", "deadline_hours": 24, '
                  '"participants": [{"kind": "employee", "user_id": 1}]}]')

    class Meta:
        model = ApprovalTemplate
        fields = ("name", "subject_type", "description", "enabled")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        if self.instance and self.instance.pk and not self.is_bound:
            self.fields["stages_text"].initial = json.dumps(_stages_json(self.instance), ensure_ascii=False)

    def clean_stages_text(self):
        raw = (self.cleaned_data.get("stages_text") or "").strip()
        if not raw:
            raise forms.ValidationError("Добавьте хотя бы один этап")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Этапы должны быть JSON-списком")
        if not isinstance(value, list) or not value:
            raise forms.ValidationError("Этапы должны быть непустым списком")
        for stage in value:
            if not isinstance(stage, dict):
                raise forms.ValidationError("Этап должен быть объектом")
            if not stage.get("title") or stage.get("mode") not in ("sequential", "parallel"):
                raise forms.ValidationError("У этапа нужны название и режим")
            if stage.get("rule") not in ("all", "any"):
                raise forms.ValidationError("Правило этапа — all или any")
            if not isinstance(stage.get("participants"), list) or not stage["participants"]:
                raise forms.ValidationError("У этапа должен быть хотя бы один участник")
            for part in stage["participants"]:
                if not isinstance(part, dict) or part.get("kind") not in ("employee", "unit_head", "queue_head"):
                    raise forms.ValidationError("Неизвестный вид участника")
        return value


def _stages_json(template) -> list:
    result = []
    for stage in template.stages.order_by("order", "pk"):
        result.append({
            "title": stage.title,
            "mode": stage.mode,
            "rule": stage.rule,
            "deadline_hours": stage.deadline_hours,
            "participants": [
                {"kind": part.kind, "user_id": part.user_id, "unit_id": part.unit_id}
                for part in stage.participants.order_by("order", "pk")
            ],
        })
    return result
