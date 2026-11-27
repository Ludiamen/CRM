"""NFR-741: проверка 200 правил на событие (срез 013). Запуск через standtools shell."""
import statistics
import time

from apps.automation.models import Rule, RuleRun
from apps.automation.services import rules
from apps.core.models import User
from apps.servicedesk.models import Ticket

author = User.objects.filter(state="active").order_by("pk").first()
ticket = Ticket.objects.order_by("pk").first()
prefix = f"LOAD13-{time.time_ns()}"
if author is None or ticket is None:
    raise SystemExit("нет сотрудника или заявки для замера")

for index in range(200):
    Rule.objects.create(name=f"{prefix}-{index}", subject_type="ticket", scope="global", author=author,
                        trigger="ticket_created",
                        conditions=[{"field": "priority", "op": "=", "value": 999999}], enabled=True)
times = []
try:
    for index in range(30):
        rules.on_event("ticket", ticket.pk, "ticket_created", f"{prefix}:warm:{index}")
    for index in range(100):
        started = time.perf_counter()
        rules.on_event("ticket", ticket.pk, "ticket_created", f"{prefix}:event:{index}")
        times.append((time.perf_counter() - started) * 1000)
finally:
    RuleRun.objects.filter(rule__name__startswith=prefix).delete()
    Rule.objects.filter(name__startswith=prefix).delete()

times.sort()
p95 = times[int(len(times) * 0.95) - 1]
print(f"NFR-741 rules=200 events={len(times)} p95={p95:.1f}ms median={statistics.median(times):.1f}ms max={max(times):.1f}ms top={[round(x,1) for x in times[-10:]]}")
if p95 > 100:
    raise SystemExit(1)
