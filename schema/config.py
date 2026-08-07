"""
schema 단계 설정 로더

schema/oma.properties(INI 유사 형식)를 로드해 설정 값을 제공한다.
env/oma.properties는 사용하지 않는다(시크릿 기반으로 독립 동작).

설계 원칙:
  - [COMMON] 섹션 + 선택된 프로젝트 섹션([b2b] 등)을 평탄하게(flat) 병합
  - 프로젝트 섹션이 COMMON을 오버라이드
  - ${VAR} 치환: 설정 키 우선, 환경 변수 후순위
    (${OMA_BASE_DIR}, ${APPLICATION_NAME} 등 상호 참조 지원)
  - 자격증명은 이 파일에 두지 않는다 → 시크릿 "이름"만 관리

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - Config 클래스: _load(), _resolve(), get()/get_bool()/get_int()
  - APPLICATION_NAME 기반 프로젝트 섹션 선택
"""

import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ${VAR} 패턴
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# 최대 치환 반복(순환 참조 방지)
_MAX_RESOLVE_PASSES = 10


class ConfigError(Exception):
    """설정 로드/파싱 오류."""


class Config:
    """
    oma.properties 로더.

    Attributes:
        config_file: 설정 파일 경로
        application_name: 선택된 프로젝트 이름(섹션 선택에 사용)
    """

    def __init__(
        self,
        config_file: Optional[str] = None,
        application_name: Optional[str] = None,
    ) -> None:
        """
        Args:
            config_file: oma.properties 경로. 없으면 이 파일과 같은 디렉토리의
                oma.properties 사용.
            application_name: 프로젝트 섹션 이름. 없으면 파일의
                APPLICATION_NAME 값을 사용.

        Raises:
            ConfigError: 파일이 없거나 읽을 수 없을 때
        """
        if config_file is None:
            config_file = os.path.join(os.path.dirname(__file__), "oma.properties")
        self.config_file = config_file
        self._application_name_hint = application_name
        self._data: Dict[str, str] = {}
        self.application_name: str = ""
        self._load()

    def _parse_sections(self) -> Dict[str, Dict[str, str]]:
        """
        파일을 섹션별 딕셔너리로 파싱한다.

        Returns:
            {section_name: {key: value}}

        Raises:
            ConfigError: 파일이 없을 때
        """
        if not os.path.isfile(self.config_file):
            raise ConfigError(f"설정 파일이 없습니다: {self.config_file}")

        sections: Dict[str, Dict[str, str]] = {}
        current = "COMMON"
        sections.setdefault(current, {})

        with open(self.config_file, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1].strip()
                    sections.setdefault(current, {})
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                # 값에 인라인 주석(#)은 허용하지 않는다(값에 # 포함 가능성 대비)
                value = value.strip()
                if key:
                    sections[current][key] = value
        return sections

    def _load(self) -> None:
        """섹션을 병합하고 ${VAR}를 치환한다."""
        sections = self._parse_sections()

        common = sections.get("COMMON", {})

        # 프로젝트 이름 결정: 생성자 힌트 > COMMON/프로젝트 섹션의 APPLICATION_NAME
        app_name = self._application_name_hint
        if not app_name:
            # 프로젝트 섹션 중 APPLICATION_NAME을 가진 첫 섹션, 없으면 COMMON 값
            app_name = common.get("APPLICATION_NAME")
            if not app_name:
                for sec_name, sec in sections.items():
                    if sec_name == "COMMON":
                        continue
                    if "APPLICATION_NAME" in sec:
                        app_name = sec["APPLICATION_NAME"]
                        break
        if not app_name:
            raise ConfigError(
                "APPLICATION_NAME을 결정할 수 없습니다 "
                "(생성자 인자 또는 properties에 지정 필요)"
            )

        # 병합: COMMON → 프로젝트 섹션(오버라이드)
        merged: Dict[str, str] = dict(common)
        project_section = sections.get(app_name, {})
        merged.update(project_section)
        merged["APPLICATION_NAME"] = app_name

        self.application_name = app_name
        self._data = self._resolve(merged)
        logger.info(
            "설정 로드 완료: %s (project=%s, keys=%d)",
            self.config_file,
            app_name,
            len(self._data),
        )

    def _resolve(self, data: Dict[str, str]) -> Dict[str, str]:
        """
        ${VAR}를 반복 치환한다(설정 키 우선, 환경 변수 후순위).

        Args:
            data: 원본 키-값

        Returns:
            치환 완료된 키-값
        """
        resolved = dict(data)
        for _ in range(_MAX_RESOLVE_PASSES):
            changed = False

            def _sub(match: "re.Match[str]") -> str:
                nonlocal changed
                var = match.group(1)
                if var in resolved:
                    changed = True
                    return resolved[var]
                env_val = os.environ.get(var)
                if env_val is not None:
                    changed = True
                    return env_val
                # 미해결 변수는 원문 유지
                return match.group(0)

            for key in list(resolved.keys()):
                resolved[key] = _VAR_PATTERN.sub(_sub, resolved[key])

            if not changed:
                break

        # 미해결 변수 경고
        for key, val in resolved.items():
            leftover = _VAR_PATTERN.findall(val)
            if leftover:
                logger.warning(
                    "설정 값에 미해결 변수: %s=%s (미해결: %s)", key, val, leftover
                )
        return resolved

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        설정 값을 문자열로 반환한다.

        Args:
            key: 설정 키
            default: 없을 때 기본값

        Returns:
            값 또는 default
        """
        return self._data.get(key, default)

    def require(self, key: str) -> str:
        """
        필수 설정 값을 반환한다.

        Args:
            key: 설정 키

        Returns:
            값

        Raises:
            ConfigError: 값이 없거나 빈 문자열일 때
        """
        val = self._data.get(key)
        if val is None or val == "":
            raise ConfigError(f"필수 설정이 없습니다: {key}")
        return val

    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        불리언 설정 값을 반환한다.

        Args:
            key: 설정 키
            default: 기본값

        Returns:
            true/1/yes/on → True (대소문자 무시)
        """
        val = self._data.get(key)
        if val is None:
            return default
        return val.strip().lower() in ("true", "1", "yes", "on")

    def get_int(self, key: str, default: int = 0) -> int:
        """
        정수 설정 값을 반환한다.

        Args:
            key: 설정 키
            default: 기본값

        Returns:
            정수 값(파싱 실패 시 default)
        """
        val = self._data.get(key)
        if val is None or val == "":
            return default
        try:
            return int(val)
        except ValueError:
            logger.warning("정수 파싱 실패: %s=%s → 기본값 %d", key, val, default)
            return default

    def as_dict(self) -> Dict[str, str]:
        """전체 설정의 사본을 반환한다(디버깅/로깅용)."""
        return dict(self._data)
