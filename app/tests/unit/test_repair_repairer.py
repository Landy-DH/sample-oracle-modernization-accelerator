"""
조각 수정기(repairer) 단위 테스트

가짜 LLM으로 수정 흐름(저장/백업/report 이력/XML 검증/멱등/스킵)을 검증한다.

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - repair_type 유형선택/action검증/중복제거, repair_fragment 저장·백업·이력·XML검증
"""

import json

import pytest

from oma.repair.repairer import FragmentRepairer, RepairOutcome
from oma.utils.exceptions import LLMError

_FRAG = "<select id=\"getOrder\">SELECT to_char(x) FROM t</select>"
_FIXED = "<select id=\"getOrder\">SELECT x::text FROM t</select>"


class FakeLLM:
    """invoke_json을 흉내내는 가짜 LLM."""

    def __init__(self, result=None, raise_error=False):
        self._result = result or {}
        self._raise = raise_error
        self.calls = 0

    def invoke_json(self, prompt, system=None, max_tokens=None):
        self.calls += 1
        if self._raise:
            raise LLMError("boom")
        return self._result


def _make_repairer(tmp_path, llm):
    converted = tmp_path / "converted"
    fragmented = tmp_path / "fragmented"
    converted.mkdir()
    fragmented.mkdir()
    (converted / "OrderMapper__select__getOrder.xml").write_text(_FRAG, encoding="utf-8")
    return FragmentRepairer(str(converted), str(fragmented), llm), converted


def _frag_ref(error="target: ERROR: function to_char does not exist"):
    return {"frag_id": "OrderMapper__select__getOrder", "error": error}


def test_repair_fragment_writes_backup_and_history(tmp_path):
    """수정 성공 시 파일 덮어쓰기 + .bak 백업 + report repair_history 기록."""
    llm = FakeLLM({"fixed_sql": _FIXED, "fix_summary": "to_char→::text", "changed": True})
    repairer, converted = _make_repairer(tmp_path, llm)

    outcome = repairer.repair_fragment(_frag_ref())

    assert outcome.status == "repaired"
    xml = (converted / "OrderMapper__select__getOrder.xml").read_text(encoding="utf-8")
    assert "::text" in xml
    assert (converted / "OrderMapper__select__getOrder.xml.bak").exists()
    report = json.loads(
        (converted / "OrderMapper__select__getOrder.report.json").read_text(encoding="utf-8")
    )
    assert report["repair_history"][0]["fix_summary"] == "to_char→::text"
    assert report["status"] == "repaired"


def test_repair_fragment_skips_when_unchanged(tmp_path):
    """LLM이 동일 내용을 반환하면 스킵(백업 없음)."""
    llm = FakeLLM({"fixed_sql": _FRAG, "fix_summary": "no change", "changed": False})
    repairer, converted = _make_repairer(tmp_path, llm)

    outcome = repairer.repair_fragment(_frag_ref())

    assert outcome.status == "skipped"
    assert not (converted / "OrderMapper__select__getOrder.xml.bak").exists()


def test_repair_fragment_rejects_invalid_xml(tmp_path):
    """수정 결과가 잘못된 XML이면 실패로 처리하고 저장하지 않는다."""
    llm = FakeLLM({"fixed_sql": "<select>unclosed", "fix_summary": "x", "changed": True})
    repairer, converted = _make_repairer(tmp_path, llm)

    outcome = repairer.repair_fragment(_frag_ref())

    assert outcome.status == "failed"
    assert "XML" in (outcome.error or "")
    # 원본 유지
    assert (converted / "OrderMapper__select__getOrder.xml").read_text(
        encoding="utf-8"
    ) == _FRAG


def test_repair_fragment_missing_file(tmp_path):
    """변환 조각 파일이 없으면 실패."""
    llm = FakeLLM({"fixed_sql": _FIXED})
    repairer, _ = _make_repairer(tmp_path, llm)
    outcome = repairer.repair_fragment({"frag_id": "Nope__select__x", "error": "e"})
    assert outcome.status == "failed"


def test_repair_fragment_llm_error(tmp_path):
    """LLM 예외는 failed로 감싼다."""
    llm = FakeLLM(raise_error=True)
    repairer, _ = _make_repairer(tmp_path, llm)
    outcome = repairer.repair_fragment(_frag_ref())
    assert outcome.status == "failed"


def _plan(action="repair"):
    return {
        "types": [{
            "no": 1, "group": "A_미변환_Oracle함수", "action": action,
            "fragments": [
                _frag_ref(), _frag_ref(),  # 같은 frag_id 중복
            ],
        }]
    }


def test_repair_type_dedups_by_frag_id(tmp_path):
    """같은 frag_id는 중복 제거되어 한 번만 수정한다."""
    llm = FakeLLM({"fixed_sql": _FIXED, "fix_summary": "s", "changed": True})
    repairer, _ = _make_repairer(tmp_path, llm)
    outcomes = repairer.repair_type(_plan(), 1)
    assert len(outcomes) == 1
    assert llm.calls == 1


def test_repair_type_rejects_non_repair_action(tmp_path):
    """action이 repair가 아닌 유형은 ValueError."""
    llm = FakeLLM({})
    repairer, _ = _make_repairer(tmp_path, llm)
    with pytest.raises(ValueError):
        repairer.repair_type(_plan(action="none"), 1)


def test_repair_type_unknown_number(tmp_path):
    """존재하지 않는 유형 번호는 ValueError."""
    llm = FakeLLM({})
    repairer, _ = _make_repairer(tmp_path, llm)
    with pytest.raises(ValueError):
        repairer.repair_type(_plan(), 99)


def test_repair_type_excludes_fragments_without_error(tmp_path):
    """note(에러)가 빈 조각은 수정 대상에서 제외한다(값/행수 불일치)."""
    llm = FakeLLM({"fixed_sql": _FIXED, "fix_summary": "s", "changed": True})
    repairer, converted = _make_repairer(tmp_path, llm)
    (converted / "OrderMapper__select__noerr.xml").write_text(_FRAG, encoding="utf-8")
    plan = {"types": [{
        "no": 1, "group": "A", "action": "repair",
        "fragments": [
            {"frag_id": "OrderMapper__select__getOrder", "error": "target: ERROR: x"},
            {"frag_id": "OrderMapper__select__noerr", "error": ""},
        ],
    }]}
    outcomes = repairer.repair_type(plan, 1)
    assert len(outcomes) == 1
    assert outcomes[0].frag_id == "OrderMapper__select__getOrder"


def test_repair_type_promotes_error_bearing_ref(tmp_path):
    """같은 조각에 빈 note와 에러 note가 섞이면 에러 있는 참조를 대표로 쓴다."""
    llm = FakeLLM({"fixed_sql": _FIXED, "fix_summary": "s", "changed": True})
    repairer, _ = _make_repairer(tmp_path, llm)
    plan = {"types": [{
        "no": 1, "group": "A", "action": "repair",
        "fragments": [
            {"frag_id": "OrderMapper__select__getOrder", "error": ""},
            {"frag_id": "OrderMapper__select__getOrder",
             "error": "target: ERROR: operator does not exist"},
        ],
    }]}
    outcomes = repairer.repair_type(plan, 1)
    assert len(outcomes) == 1
    assert outcomes[0].status == "repaired"


def test_repair_type_limit(tmp_path):
    """limit로 샘플 수를 제한한다."""
    llm = FakeLLM({"fixed_sql": _FIXED, "fix_summary": "s", "changed": True})
    repairer, converted = _make_repairer(tmp_path, llm)
    # 두 개의 서로 다른 조각
    (converted / "OrderMapper__select__other.xml").write_text(_FRAG, encoding="utf-8")
    plan = {"types": [{
        "no": 1, "group": "A", "action": "repair",
        "fragments": [
            {"frag_id": "OrderMapper__select__getOrder", "error": "e"},
            {"frag_id": "OrderMapper__select__other", "error": "e"},
        ],
    }]}
    outcomes = repairer.repair_type(plan, 1, limit=1)
    assert len(outcomes) == 1
