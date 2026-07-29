"""
특수 바인드 변수 / OGNL 선치환 모듈

프레임워크가 런타임 주입하는 특수 변수(PAGING_ROWNUM_*, sysdate 등)와 OGNL 정적 메서드
(@Class@method)를 원본 매퍼 복사본에서 선치환한다. TC로 바인딩·평가할 수 없는 것들을
리터럴/기본 OGNL로 바꿔 split→convert→merge 파이프라인이 처리할 수 있게 한다.

치환 규칙은 config JSON(기본 scripts/special_variables.json)에서 로드한다.
정규식이 아닌 str 스캔으로 치환한다 (15-coding-guidelines.md).

주의: 원본(source/)이 아니라 복사본(projects/.../original)에서만 적용할 것.

변경 이력:
2026-07-27 | OMA Team | scripts에서 정식 모듈로 이관
  - SpecialVariableSubstitutor: 변수/OGNL 치환, XML 이스케이프, 디렉토리 처리
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "scripts", "special_variables.json",
)


@dataclass
class SubstitutionResult:
    """치환 요약"""

    total_files: int = 0
    changed_files: int = 0
    variable_subs: int = 0
    ognl_subs: int = 0


def _xml_escape(text: str) -> str:
    """치환 리터럴을 XML 텍스트에 안전하게 넣도록 &,<,> 이스케이프 (& 먼저)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _token_root(inner: str) -> str:
    """#{...}/${...} 내부에서 루트 변수명 추출 (콤마/공백 이전, 소문자)."""
    for sep in (",", " ", "\t", "\n"):
        idx = inner.find(sep)
        if idx != -1:
            inner = inner[:idx]
    return inner.strip().lower()


class SpecialVariableSubstitutor:
    """
    특수 변수/OGNL 선치환기

    Attributes:
        dialect: 치환 방언 (oracle/postgres)
        variables: {소문자 변수명: XML이스케이프된 리터럴}
        ognl_methods: {@Class@method: 연산자 문자열}
    """

    def __init__(
        self,
        dialect: str = "oracle",
        config_path: Optional[str] = None,
        enable_ognl: bool = True,
    ) -> None:
        """
        초기화

        Args:
            dialect: 'oracle' 또는 'postgres'
            config_path: 치환 규칙 JSON 경로 (없으면 기본)
            enable_ognl: OGNL 정적 메서드 치환 여부 (실전에선 False + classpath 등록)
        """
        self.dialect = dialect
        config = self._load_config(config_path or _DEFAULT_CONFIG)
        self.variables = {
            name.lower(): _xml_escape(vals[dialect])
            for name, vals in config.get("variables", {}).items()
            if dialect in vals
        }
        self.ognl_methods = config.get("ognl_methods", {}) if enable_ognl else {}

    @staticmethod
    def _load_config(path: str) -> dict:
        """치환 규칙 JSON을 로드한다."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def substitute_variables(self, content: str) -> Tuple[str, int]:
        """
        #{...}/${...} 특수 변수를 리터럴로 치환한다 (정규식 미사용).

        Args:
            content: 매퍼 XML 문자열

        Returns:
            (치환된 문자열, 치환 건수)
        """
        result = []
        i = 0
        count = 0
        length = len(content)
        while i < length:
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
            root = _token_root(content[start + 2 : end])
            if root in self.variables:
                result.append(self.variables[root])
                count += 1
            else:
                result.append(content[start : end + 1])
            i = end + 1
        return "".join(result), count

    def substitute_ognl(self, content: str) -> Tuple[str, int]:
        """
        OGNL 정적 메서드 @Class@method(arg) 를 (arg <op>) 로 치환한다.

        Args:
            content: 매퍼 XML 문자열

        Returns:
            (치환된 문자열, 치환 건수)
        """
        count = 0
        for prefix, op in self.ognl_methods.items():
            result = []
            i = 0
            while True:
                idx = content.find(prefix, i)
                if idx == -1:
                    result.append(content[i:])
                    break
                open_paren = content.find("(", idx + len(prefix))
                close_paren = (
                    content.find(")", open_paren + 1) if open_paren != -1 else -1
                )
                if open_paren == -1 or close_paren == -1:
                    result.append(content[i : idx + len(prefix)])
                    i = idx + len(prefix)
                    continue
                arg = content[open_paren + 1 : close_paren].strip()
                result.append(content[i:idx])
                result.append(f"({arg}{op})")
                count += 1
                i = close_paren + 1
            content = "".join(result)
        return content, count

    def substitute_file(self, path: str) -> Tuple[int, int]:
        """
        파일 하나를 치환한다 (변경 시에만 저장).

        Args:
            path: 매퍼 파일 경로

        Returns:
            (변수 치환 건수, OGNL 치환 건수)
        """
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        replaced, var_count = self.substitute_variables(original)
        replaced, ognl_count = self.substitute_ognl(replaced)
        if var_count or ognl_count:
            with open(path, "w", encoding="utf-8") as f:
                f.write(replaced)
        return var_count, ognl_count

    def substitute_directory(self, mapper_dir: str) -> SubstitutionResult:
        """
        디렉토리 내 모든 매퍼 XML을 치환한다 (._ 제외).

        Args:
            mapper_dir: 매퍼 디렉토리 (복사본!)

        Returns:
            SubstitutionResult
        """
        if "/source/" in os.path.abspath(mapper_dir):
            raise ValueError("원본(source) 경로에서는 실행 금지. 복사본에서만.")

        result = SubstitutionResult()
        for dirpath, _dirs, files in os.walk(mapper_dir):
            for fname in files:
                if not fname.endswith(".xml") or fname.startswith("._"):
                    continue
                path = os.path.join(dirpath, fname)
                result.total_files += 1
                var_c, ognl_c = self.substitute_file(path)
                if var_c or ognl_c:
                    result.changed_files += 1
                    result.variable_subs += var_c
                    result.ognl_subs += ognl_c

        logger.info(
            "특수변수 치환: 파일 %d/%d 변경, 변수 %d건, OGNL %d건",
            result.changed_files, result.total_files,
            result.variable_subs, result.ognl_subs,
        )
        return result
