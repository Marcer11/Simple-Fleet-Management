"""Nepojízdnost vozidla podle poznámek.

Začíná poznámkou "Nepojízdné", končí poznámkou "Opět pojízdné" nebo vyzvednutím ze servisu
(zapsaným datem vyzvednutí po začátku nepojízdnosti).
"""
from dataclasses import dataclass
from datetime import datetime, time

from .vehicle_note import OUT_OF_ORDER, BACK_IN_ORDER


@dataclass
class OutOfOrderPeriod:
    start: object               # poznámka "Nepojízdné"
    end: datetime = None        # None = vozidlo je pořád nepojízdné
    end_has_time: bool = True
    end_key: tuple = None       # ("note", id) | ("service", id) - čím nepojízdnost skončila

    @property
    def duration(self):
        if self.end is None:
            return None
        if not self.end_has_time:  # vyzvednutí bez času: jen ve dnech
            return days_text(max((self.end.date() - self.start.note_datetime.date()).days, 1))
        return duration_text(self.end - self.start.note_datetime)


def days_text(days):
    return f"{days} {'den' if days == 1 else ('dny' if 1 < days < 5 else 'dní')}"


def duration_text(delta):
    minutes = max(int(delta.total_seconds() // 60), 0)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    parts = [days_text(days)] if days else []
    if hours:
        parts.append(f"{hours} h")
    if mins and not days:
        parts.append(f"{mins} min")
    return " ".join(parts) or "0 min"


def out_of_order_periods(vehicle):
    marks = []  # (kdy, pořadí ve stejném okamžiku, druh, objekt, má čas)
    for note in vehicle.notes:
        category = (note.category or "").strip().lower()
        if category == OUT_OF_ORDER.lower():
            marks.append((note.note_datetime, 1, "start", note, True))
        elif category == BACK_IN_ORDER.lower():
            marks.append((note.note_datetime, 0, "note", note, True))
    for record in vehicle.service_records:
        if record.date_to is not None:
            has_time = record.time_to is not None
            # vyzvednutí bez času patří na konec dne
            marks.append((datetime.combine(record.date_to, record.time_to or time.max), 0, "service", record, has_time))
    marks.sort(key=lambda m: (m[0], m[1], m[3].id))

    periods, current = [], None
    for when, _, kind, obj, has_time in marks:
        if kind == "start":
            if current is None:
                current = OutOfOrderPeriod(obj)
                periods.append(current)
        elif current is not None:
            current.end, current.end_has_time, current.end_key = when, has_time, (kind, obj.id)
            current = None
    return periods
