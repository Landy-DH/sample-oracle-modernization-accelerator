"""
사전 검증 가이드 생성 모듈

MapperScanner의 검출 결과(PreflightReport)를 받아, 각 이슈를 "어디에 무엇을
반영해야 하는지" 구체적으로 안내하는 가이드를 생성한다.

산출물 2종:
  1. build_config_stubs(): 사용자가 값을 채울 설정 스텁 (JSON)
     - special_variables.json에 붙여넣을 변수/OGNL 항목
     - 타입 별칭 매핑 항목
  2. build_markdown_guide(): 사람이 읽는 조치 가이드 (Markdown)
     - 각 이슈 유형별로 어느 파일/설정을 어떻게 수정하는지

이렇게 해서 preflight 스캔이 "이슈가 있다"에 그치지 않고 "이렇게 반영하라"까지
연결한다.

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - build_config_stubs / build_markdown_guide
"""

from typing import Any, Dict

# 각 이슈 유형별 조치 가이드 (파일/방법)
_GUIDE_OGNL = (
    "OGNL 정적 메서드(@Class@method)는 MyBatis가 getBoundSql 시 해당 클래스를 "
    "classpath에서 찾아 평가합니다. 두 가지 중 선택:\n"
    "  (A) 실전: 고객 프로젝트의 해당 클래스(JAR)를 Java Validator classpath에 등록.\n"
    "      → java -cp \"oma-validator.jar:/path/to/customer-libs/*\" ... 로 실행하도록 구성.\n"
    "  (B) 테스트: scripts/special_variables.json 의 ognl_methods 에 각 메서드를 "
    "MyBatis 기본 OGNL(예: != null / == null)로 매핑해 선치환.\n"
    "      → SUBSTITUTE_OGNL=true (기본)일 때 Phase2에서 자동 치환됨."
)
_GUIDE_DOLLAR = (
    "${} 동적 변수는 런타임에 값이 정해져 바인딩이 불가합니다. 프레임워크가 주입하는 "
    "고정 변수(페이징/정렬 등)라면 scripts/special_variables.json 의 variables 에 "
    "oracle/postgres 리터럴을 지정해 Phase2에서 선치환하세요.\n"
    "  → 테이블명/컬럼명 같은 진짜 동적 값이면 TC 파라미터로 값을 제공해야 합니다."
)
_GUIDE_ALIAS = (
    "resultType/parameterType의 미지 타입 별칭(camelMap 등)은 mybatis-config에 등록된 "
    "프로젝트 고유 별칭입니다. 검증은 resultType 클래스를 쓰지 않으므로(결과를 Map으로 "
    "직접 읽음) Java Validator의 LenientConfiguration이 자동으로 HashMap 폴백합니다.\n"
    "  → 대부분 조치 불필요. 단, resultMap 파싱 실패가 잦으면 해당 매퍼는 부분검증 "
    "제외될 수 있으니 리포트의 parse_errors 를 확인하세요."
)
_GUIDE_PARSE = (
    "엄격 XML 파서로 파싱 실패한 매퍼입니다. 흔한 원인은 이스케이프 안 된 '<'(예: "
    "WHERE ROWNUM < 10)나 '&' 입니다.\n"
    "  → 원본 매퍼에서 < → &lt;, & → &amp; 로 수정하거나 CDATA로 감싸야 합니다. "
    "(자동 변환 대상에서 제외되므로 수동 확인 필요)"
)
_GUIDE_PROC = (
    "프로시저 호출(CALL/EXEC 등)은 데이터 변경 위험으로 검증에서 실행하지 않고 "
    "skip 처리됩니다.\n  → 프로시저 변환/검증은 수동 검토 대상입니다."
)


class PreflightGuide:
    """PreflightReport → 설정 스텁 + Markdown 가이드 생성기."""

    @staticmethod
    def build_config_stubs(report: Any) -> Dict[str, Any]:
        """
        검출값을 채운 설정 스텁을 만든다 (special_variables.json 형식과 호환).

        Args:
            report: PreflightReport

        Returns:
            {variables, ognl_methods, type_aliases} 스텁 (값은 사용자가 채움)
        """
        return {
            "_comment": (
                "preflight 스캔이 생성한 스텁. 값을 채워 scripts/special_variables.json "
                "및 매퍼 처리에 반영하세요. 빈 값은 사용자 입력 필요."
            ),
            "variables": {
                var: {"oracle": "", "postgres": ""}
                for var in report.dollar_variables
            },
            "ognl_methods": {
                method: " != null  # 또는 == null / 적절한 MyBatis OGNL 식"
                for method in report.ognl_methods
            },
            "type_aliases": {
                alias: "java.util.HashMap"
                for alias in report.unknown_type_aliases
            },
        }

    @staticmethod
    def build_markdown_guide(report: Any) -> str:
        """
        검출 결과에 대한 조치 가이드(Markdown)를 만든다.

        Args:
            report: PreflightReport

        Returns:
            Markdown 문자열
        """
        lines = [
            "# Pre-flight 조치 가이드",
            "",
            f"- 스캔 매퍼: {report.mapper_count}개 (파싱 성공 {report.parsed_ok})",
            "",
            "검출된 각 이슈를 아래 안내대로 설정/매퍼에 반영한 뒤 변환을 진행하세요.",
            "",
        ]

        lines += PreflightGuide._section(
            "OGNL 정적 메서드", report.ognl_methods, _GUIDE_OGNL,
            item_fmt=lambda k, v: f"  - `{k}` ({v}회)",
        )
        lines += PreflightGuide._section(
            "${} 동적 변수", report.dollar_variables, _GUIDE_DOLLAR,
            item_fmt=lambda k, v: f"  - `${{{k}}}` ({v}회)",
        )
        lines += PreflightGuide._section(
            "미지 타입 별칭", report.unknown_type_aliases, _GUIDE_ALIAS,
            item_fmt=lambda k, v: f"  - `{k}` ({v}회)",
        )
        lines += PreflightGuide._section(
            "XML 파싱 실패", {e["file"]: e["error"] for e in report.parse_errors},
            _GUIDE_PARSE, item_fmt=lambda k, v: f"  - `{k}`: {v}",
        )
        lines += PreflightGuide._section(
            "프로시저 호출", {p: "" for p in report.procedure_calls}, _GUIDE_PROC,
            item_fmt=lambda k, v: f"  - `{k}`",
        )
        return "\n".join(lines)

    @staticmethod
    def _section(title: str, items: Dict[str, Any], guide: str, item_fmt) -> list:
        """가이드 한 섹션을 만든다 (항목 없으면 '없음')."""
        out = [f"## {title} ({len(items)}종)", ""]
        if not items:
            out += ["검출 없음.", ""]
            return out
        out += ["**검출 항목**:"]
        for k, v in items.items():
            out.append(item_fmt(k, v))
        out += ["", "**조치 방법**:", guide, ""]
        return out
