"""
설정 파일 로더

oma.properties(INI 유사 형식)를 로드하고 설정 값을 제공한다.
지원 기능:
  - 섹션 헤더([COMMON] 등)는 무시하고 키를 평탄하게(flat) 관리
  - 전체 줄 주석(#, ; 로 시작) 및 인라인 주석( 값 뒤 " #...") 제거
  - 변수 치환 ${VAR}: 먼저 다른 설정 키, 없으면 환경 변수로 치환
  - get()에서 숫자 문자열 자동 형변환(int/float)

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - Config 클래스 구현: _load(), _resolve_variables(), get() 및 타입별 getter
  - 정규식 없이 str 메서드로 파싱 (코딩 가이드라인 준수)
  - ${VAR} 치환은 설정 키 우선, 환경 변수 후순위 (oma.properties의 ${OMA_BASE_DIR} 대응)
"""

import os
from typing import Any, Dict, List, Optional

from oma.utils.exceptions import ConfigError

# 전체 줄 주석 시작 문자
_COMMENT_PREFIXES = ("#", ";")
# 인라인 주석 구분자 (값과 주석 사이 공백 + '#')
_INLINE_COMMENT_SEP = " #"
# ${VAR} 치환 순환 참조 방지를 위한 최대 반복 횟수
_MAX_SUBSTITUTION_PASSES = 10


class Config:
    """
    OMA 설정 관리 클래스

    oma.properties 파일을 로드하고 설정 값을 제공한다.
    환경 변수 및 설정 키 상호 참조 치환(${VAR})을 지원한다.

    Attributes:
        config_file: 로드한 설정 파일 경로
        region: AWS region (선택)
        config: 파싱된 key -> value(str) 딕셔너리
    """

    def __init__(self, config_file: str, region: Optional[str] = None) -> None:
        """
        초기화 및 설정 로드

        Args:
            config_file: oma.properties 파일 경로
            region: AWS region (선택)

        Raises:
            ConfigError: 파일이 없거나 읽을 수 없을 때
        """
        self.config_file = config_file
        self.region = region
        self.config: Dict[str, str] = {}

        self._load()

    def _load(self) -> None:
        """
        설정 파일을 읽어 self.config에 저장한다.

        처리 순서:
          1. 파일을 한 번에 읽기
          2. 줄 단위로 주석/섹션 헤더/빈 줄 제거
          3. key=value 파싱 (첫 '='만 분리)
          4. 인라인 주석 제거 및 트리밍
          5. ${VAR} 치환 수행

        Raises:
            ConfigError: 파일 접근 실패 시
        """
        if not os.path.isfile(self.config_file):
            raise ConfigError(
                "설정 파일을 찾을 수 없습니다",
                {"config_file": self.config_file},
            )

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            raise ConfigError(
                "설정 파일을 읽을 수 없습니다",
                {"config_file": self.config_file, "error": str(e)},
            ) from e

        for raw_line in lines:
            line = raw_line.strip()

            # 빈 줄, 전체 줄 주석, 섹션 헤더 건너뛰기
            if not line or line.startswith(_COMMENT_PREFIXES):
                continue
            if line.startswith("[") and line.endswith("]"):
                continue
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = self._strip_inline_comment(value).strip()

            if key:
                self.config[key] = value

        self._resolve_variables()

    @staticmethod
    def _strip_inline_comment(value: str) -> str:
        """
        값에서 인라인 주석(" #...")을 제거한다.

        값 안에 '#'이 정상적으로 포함될 수 있으므로, 공백 뒤에 오는
        '#'만 주석으로 간주한다 (정규식 미사용).

        Args:
            value: 원본 값 문자열

        Returns:
            인라인 주석이 제거된 값
        """
        idx = value.find(_INLINE_COMMENT_SEP)
        if idx != -1:
            return value[:idx]
        return value

    def _resolve_variables(self) -> None:
        """
        모든 값의 ${VAR} 참조를 치환한다.

        치환 우선순위: 다른 설정 키 > 환경 변수 > (미해결 시 원본 유지)
        상호 참조를 위해 값이 안정될 때까지 최대 _MAX_SUBSTITUTION_PASSES회 반복한다.
        """
        for _ in range(_MAX_SUBSTITUTION_PASSES):
            changed = False
            for key, value in self.config.items():
                resolved = self._substitute(value)
                if resolved != value:
                    self.config[key] = resolved
                    changed = True
            if not changed:
                break

    def _substitute(self, value: str) -> str:
        """
        단일 값의 ${VAR} 패턴을 치환한다 (정규식 미사용, str 스캔).

        Args:
            value: 치환 대상 값

        Returns:
            치환된 값 (미해결 참조는 원본 그대로 유지)
        """
        if "${" not in value:
            return value

        result = []
        i = 0
        length = len(value)
        while i < length:
            start = value.find("${", i)
            if start == -1:
                result.append(value[i:])
                break

            end = value.find("}", start + 2)
            if end == -1:
                # 닫는 중괄호가 없으면 나머지를 그대로 붙임
                result.append(value[i:])
                break

            result.append(value[i:start])
            var_name = value[start + 2 : end]
            replacement = self._lookup_variable(var_name)
            if replacement is None:
                # 미해결 참조는 원본 형태로 보존
                result.append(value[start : end + 1])
            else:
                result.append(replacement)
            i = end + 1

        return "".join(result)

    def _lookup_variable(self, var_name: str) -> Optional[str]:
        """
        치환용 변수 값을 조회한다 (설정 키 > 환경 변수).

        Args:
            var_name: ${...} 안의 변수명

        Returns:
            찾은 값 또는 None
        """
        if var_name in self.config:
            return self.config[var_name]
        return os.environ.get(var_name)

    def get(self, key: str, default: Any = None) -> Any:
        """
        설정 값 조회 (숫자는 자동 형변환)

        순수 정수 문자열은 int, 소수 형태는 float로 변환한다.
        그 외에는 문자열을 그대로 반환한다. 불린은 get_bool()을 사용할 것.

        Args:
            key: 설정 키
            default: 없을 때 반환할 기본 값

        Returns:
            설정 값(자동 형변환됨) 또는 default
        """
        if key not in self.config:
            return default

        value = self.config[key]
        return self._coerce_type(value)

    @staticmethod
    def _coerce_type(value: str) -> Any:
        """
        문자열 값을 int/float로 자동 변환 시도한다.

        Args:
            value: 원본 문자열

        Returns:
            변환된 int/float 또는 원본 문자열
        """
        if not isinstance(value, str):
            return value

        candidate = value.strip()
        # 정수 (앞 부호 허용)
        int_body = candidate[1:] if candidate[:1] in ("+", "-") else candidate
        if int_body.isdigit():
            return int(candidate)

        # 소수
        try:
            if "." in candidate or "e" in candidate.lower():
                return float(candidate)
        except ValueError:
            pass

        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """
        정수 값 조회

        Args:
            key: 설정 키
            default: 기본 값

        Returns:
            정수 값

        Raises:
            ConfigError: 정수로 변환할 수 없을 때
        """
        value = self.get(key, default)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            raise ConfigError(
                "정수로 변환할 수 없습니다",
                {"key": key, "value": value},
            ) from e

    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        불린 값 조회 (true/yes/1 → True)

        Args:
            key: 설정 키
            default: 기본 값

        Returns:
            불린 값
        """
        value = self.config.get(key)
        if value is None:
            return default
        return value.strip().lower() in ("true", "yes", "1", "on")

    def get_list(
        self, key: str, separator: str = ",", default: Optional[List[str]] = None
    ) -> List[str]:
        """
        구분자로 분리된 리스트 값 조회

        Args:
            key: 설정 키
            separator: 구분자 (기본 ',')
            default: 기본 값

        Returns:
            문자열 리스트 (빈 항목 제외)
        """
        value = self.config.get(key)
        if value is None:
            return default if default is not None else []
        return [item.strip() for item in value.split(separator) if item.strip()]
