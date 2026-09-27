from dataclasses import dataclass, field

from . import repository
from .models import ChargeStatus, Status


@dataclass
class Report:
    """The outcome of one reconciliation run."""

    checked: int = 0
    settled: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        return {"checked": self.checked, "settled": self.settled, "unresolved": self.unresolved}


def reconcile(service) -> Report:
    """Settles orders whose charge never got a definite answer from the provider."""
    pending = repository.list_orders_by_status(Status.PENDING)
    report = Report(checked=len(pending))
    for value in pending:
        charges = service.provider.list_charges(value.order_no)
        settled = False
        for charge in charges:
            if charge.reference != value.order_no:
                continue
            now = service.clock.now()
            repository.set_order_status(value.id, Status.PAID, now)
            stored = repository.list_charges(value.id)
            if stored:
                repository.update_charge(
                    stored[-1].id, charge.id, ChargeStatus.SUCCEEDED, stored[-1].attempts, "", now
                )
            report.settled.append(value.order_no)
            settled = True
            break
        if not settled:
            report.unresolved.append(value.order_no)
    return report
