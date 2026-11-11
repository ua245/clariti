import json
from pathlib import Path

from app.checklist.models import ChecklistTemplate


def load_default_template() -> ChecklistTemplate:
    path = Path(__file__).with_name("default_checklist.json")
    return ChecklistTemplate.model_validate(json.loads(path.read_text(encoding="utf-8")))
