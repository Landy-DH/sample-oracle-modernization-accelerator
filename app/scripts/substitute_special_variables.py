"""
특수 바인드 변수 선치환 스크립트

프레임워크가 런타임에 주입하는 특수 변수(PAGING_ROWNUM_*, sysdate)는 테스트 케이스
파라미터로 바인딩할 수 없다. 따라서 원본 매퍼 복사본(projects/<app>/mappers/original)
에서 이 변수 토큰을 리터럴 SQL로 미리 치환한다. 이후 split→convert→merge 파이프라인이
치환된 SQL을 그대로 반영한다.

치환 방식 (정규식 아님, str 스캔):
  - #{VAR} / ${VAR} 및 옵션이 붙은 형태(#{sysdate,mode=IN,jdbcType=VARCHAR})까지
  - 토큰 내부의 루트 이름(콤마/공백 이전)을 대소문자 무시로 매칭
  - 매칭되면 토큰 전체를 special_variables.json의 값(현재 oracle)으로 교체

주의: 원본(source/)이 아니라 복사본(projects/.../original)에서만 실행할 것.

사용법:
  python3.11 scripts/substitute_special_variables.py <mapper_dir> [--dialect oracle]

변경 이력:
2026-07-27 | OMA Team | 초기 생성 (검증용, 오케스트레이터 통합 전 임시)
"""

import argparse
import json
import logging
import os
import sys
from typing import Dict, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("substitute")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "special_variables.json")


def load_config() -> dict:
    """special_variables.json 전체를 로드한다."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_variables(dialect: str) -> Dict[str, str]:
    """
    치환 규칙을 로드해 {소문자 변수명: 리터럴 SQL} 맵을 만든다.

    Args:
        dialect: 'oracle' 또는 'postgres'

    Returns:
        소문자 변수명 → 치환 리터럴
    """
    config = load_config()
    result = {}
    for name, values in config["variables"].items():
        if dialect not in values:
            continue
        # XML 텍스트 노드에 넣으므로 <, >, & 를 이스케이프
        result[name.lower()] = _xml_escape(values[dialect])
    return result


def _xml_escape(text: str) -> str:
    """
    치환 리터럴을 XML 텍스트 노드에 안전하게 넣도록 이스케이프한다.

    특수 변수 값에 SQL 비교 연산자(<, >)나 &가 들어갈 수 있는데(예:
    "WHERE ROWNUM <= 1000"), 이를 그대로 XML에 넣으면 파서가 태그로 오인한다.
    &를 먼저 처리해 이중 이스케이프를 방지한다. MyBatis/DB로 갈 때 원래 문자로 복원됨.

    Args:
        text: 치환 리터럴

    Returns:
        XML-이스케이프된 문자열
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _token_root(inner: str) -> str:
    """#{...} 내부 문자열에서 루트 변수명을 뽑는다 (콤마/공백 이전, 소문자)."""
    for sep in (",", " ", "\t", "\n"):
        idx = inner.find(sep)
        if idx != -1:
            inner = inner[:idx]
    return inner.strip().lower()


def substitute_content(content: str, variables: Dict[str, str]) -> Tuple[str, int]:
    """
    문자열 내 #{...}/${...} 특수 변수 토큰을 리터럴로 치환한다 (정규식 미사용).

    Args:
        content: 매퍼 XML 문자열
        variables: load_variables 결과

    Returns:
        (치환된 문자열, 치환 건수)
    """
    result = []
    i = 0
    count = 0
    length = len(content)

    while i < length:
        # 다음 토큰 시작(#{ 또는 ${) 탐색
        hash_idx = content.find("#{", i)
        dollar_idx = content.find("${", i)
        candidates = [x for x in (hash_idx, dollar_idx) if x != -1]
        if not candidates:
            result.append(content[i:])
            break

        start = min(candidates)
        end = content.find("}", start + 2)
        if end == -1:
            result.append(content[i:])
            break

        result.append(content[i:start])
        inner = content[start + 2 : end]
        root = _token_root(inner)

        if root in variables:
            result.append(variables[root])
            count += 1
        else:
            # 특수 변수가 아니면 토큰 원형 유지
            result.append(content[start : end + 1])
        i = end + 1

    return "".join(result), count


def substitute_ognl(content: str, ognl_methods: Dict[str, str]) -> Tuple[str, int]:
    """
    OGNL 정적 메서드 호출을 MyBatis 기본 OGNL(null 체크)로 치환한다 (정규식 미사용).

    "@Class@method(ARG)" → "(ARG <op>)" 형태로 변환한다.
    예) @com.example...StringUtil@isNotEmpty(owkey) → (owkey != null)
    인자는 단순 식별자 전제(중첩 괄호 없음)로 첫 ')'까지를 인자로 본다.

    테스트 목적 치환이며, 실전에서는 고객 OGNL 클래스를 classpath에 등록하고
    이 치환을 사용하지 않는다.

    Args:
        content: 매퍼 XML 문자열
        ognl_methods: {메서드 프리픽스(@Class@method): 연산자 문자열}

    Returns:
        (치환된 문자열, 치환 건수)
    """
    count = 0
    for prefix, op in ognl_methods.items():
        result = []
        i = 0
        while True:
            idx = content.find(prefix, i)
            if idx == -1:
                result.append(content[i:])
                break
            open_paren = content.find("(", idx + len(prefix))
            close_paren = content.find(")", open_paren + 1) if open_paren != -1 else -1
            if open_paren == -1 or close_paren == -1:
                # 형태가 예상과 다르면 원형 유지
                result.append(content[i:idx + len(prefix)])
                i = idx + len(prefix)
                continue
            arg = content[open_paren + 1 : close_paren].strip()
            result.append(content[i:idx])
            result.append(f"({arg}{op})")
            count += 1
            i = close_paren + 1
        content = "".join(result)
    return content, count


def process_directory(mapper_dir: str, dialect: str, ognl: bool = True) -> None:
    """
    디렉토리 내 모든 매퍼 XML을 치환한다 (._ 파일 제외).

    Args:
        mapper_dir: 매퍼 디렉토리 (복사본!)
        dialect: 치환 방언
        ognl: OGNL 정적 메서드도 null 체크로 치환할지 (테스트용, 기본 True)
    """
    variables = load_variables(dialect)
    ognl_methods = load_config().get("ognl_methods", {}) if ognl else {}
    logger.info("변수 치환 규칙(%s): %s", dialect, list(variables.keys()))
    if ognl_methods:
        logger.info("OGNL 치환 규칙: %s", list(ognl_methods.keys()))

    total_files = 0
    changed_files = 0
    total_subs = 0
    total_ognl = 0

    for dirpath, _dirs, files in os.walk(mapper_dir):
        for fname in files:
            if not fname.endswith(".xml") or fname.startswith("._"):
                continue
            path = os.path.join(dirpath, fname)
            total_files += 1

            with open(path, "r", encoding="utf-8") as f:
                original = f.read()
            replaced, count = substitute_content(original, variables)
            replaced, ognl_count = substitute_ognl(replaced, ognl_methods)

            if count > 0 or ognl_count > 0:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(replaced)
                changed_files += 1
                total_subs += count
                total_ognl += ognl_count

    logger.info("OGNL 치환: %d건", total_ognl)
    logger.info(
        "완료: 파일 %d개 중 %d개 변경, 총 %d건 치환",
        total_files, changed_files, total_subs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="특수 바인드 변수 선치환")
    parser.add_argument("mapper_dir", help="매퍼 디렉토리 (복사본!)")
    parser.add_argument("--dialect", default="oracle", choices=["oracle", "postgres"])
    parser.add_argument(
        "--no-ognl", action="store_true",
        help="OGNL 정적 메서드 치환 비활성화 (실전: 고객 클래스 classpath 등록 시)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.mapper_dir):
        logger.error("디렉토리를 찾을 수 없습니다: %s", args.mapper_dir)
        return 1
    # 안전장치: source 원본 경로에서 실행 금지
    if "/source/" in os.path.abspath(args.mapper_dir):
        logger.error("원본(source) 경로에서는 실행 금지. 복사본에서만 실행하세요.")
        return 1

    process_directory(args.mapper_dir, args.dialect, ognl=not args.no_ognl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
