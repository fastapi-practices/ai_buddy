from backend.plugin.ai_buddy.model.skill import AIBuddySkill
from backend.plugin.ai_buddy.utils.skill_parser import load_builtin_skill_payloads, parse_skill_upload


def test_builtin_skills_fit_skill_columns() -> None:
    columns = AIBuddySkill.__table__.c
    payloads = load_builtin_skill_payloads()
    assert payloads
    for files in payloads:
        upload = parse_skill_upload(files=files)
        assert len(upload.name) <= columns.name.type.length, upload.name
        assert len(upload.description) <= columns.description.type.length, upload.name
        assert len(upload.version) <= columns.version.type.length, upload.name
