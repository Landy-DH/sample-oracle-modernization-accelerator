"""
매퍼 분할 모듈

MyBatis 매퍼 XML을 SQL ID(statement)별 조각(Fragment)으로 분할한다.
대용량 매퍼를 작은 단위로 나눠 병렬 변환을 가능하게 한다.

파싱은 반드시 lxml.etree로 수행한다 (정규식으로 XML 파싱 금지 — 15-coding-guidelines.md).
외부 DTD(mybatis-3-mapper.dtd)를 참조하는 DOCTYPE이 있으므로 네트워크 접근을 차단하고
(no_network), CDATA는 보존한다(strip_cdata=False).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - Fragment 데이터클래스 및 MapperSplitter 구현
  - split(): 최상위 statement(select/insert/update/delete/sql 등)를 조각으로 분리
  - split_workspace(): 워크스페이스 내 모든 매퍼 분할 + mapping.json 생성
  - lxml 사용, 정규식 미사용
"""

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from lxml import etree

from oma.utils.exceptions import ConversionError

logger = logging.getLogger(__name__)

# id 속성을 갖는 MyBatis 최상위 statement 태그 (변환 대상 + 재사용 sql/맵)
_STATEMENT_TAGS = frozenset(
    {"select", "insert", "update", "delete", "sql", "resultMap", "parameterMap"}
)
# id 없는 최상위 요소 (cache 등) — 손실 없이 보존하기 위한 합성 id 접두어
_SYNTHETIC_ID_PREFIX = "__el"

# 스캔에서 기본 제외할 디렉토리명 (변환 대상이 아닌 백업/파이프라인 산출물)
_DEFAULT_EXCLUDE_DIRS = frozenset(
    {"app-migration", "target", "build", ".git", "node_modules"}
)


@dataclass
class Fragment:
    """
    매퍼에서 분리된 단일 조각 (하나의 SQL statement 등)

    Attributes:
        mapper_name: 매퍼 이름 (파일명에서 확장자 제외)
        namespace: <mapper namespace="..."> 값
        sql_id: statement의 id 속성 (id 없으면 합성 id)
        statement_type: 태그명 (select/insert/update/delete/sql/resultMap 등)
        content: 해당 요소의 XML 직렬화 문자열
        source_file: 원본 매퍼 파일 경로 (워크스페이스 기준 상대경로)
        has_id: 원본에 실제 id 속성이 있었는지 여부
    """

    mapper_name: str
    namespace: Optional[str]
    sql_id: str
    statement_type: str
    content: str
    source_file: str
    has_id: bool = True


@dataclass
class MapperSplitResult:
    """단일 매퍼 분할 결과"""

    mapper_name: str
    namespace: Optional[str]
    source_file: str
    fragments: List[Fragment] = field(default_factory=list)


class MapperSplitter:
    """
    MyBatis 매퍼 XML 분할기

    Attributes:
        config: Config 객체 (SOURCE_WORKSPACE 등 참조)
        source_workspace: 매퍼 검색 루트
    """

    def __init__(self, config: Any) -> None:
        """
        초기화

        Args:
            config: Config 객체

        참고:
            MAPPER_EXCLUDE_DIRS (config, 콤마 구분)로 스캔에서 제외할 디렉토리명을
            지정한다. 미설정 시 기본값(_DEFAULT_EXCLUDE_DIRS) 사용.
            변환 대상이 아닌 백업/파이프라인 산출물 디렉토리를 걸러낸다.
        """
        self.config = config
        self.source_workspace = config.get("SOURCE_WORKSPACE", "")
        self.exclude_dirs = self._resolve_exclude_dirs(config)

    @staticmethod
    def _resolve_exclude_dirs(config: Any) -> frozenset:
        """
        스캔 제외 디렉토리명 집합을 구성한다.

        Args:
            config: Config 객체

        Returns:
            제외할 디렉토리명 frozenset
        """
        configured = config.get_list("MAPPER_EXCLUDE_DIRS", default=[])
        if configured:
            return frozenset(configured)
        return _DEFAULT_EXCLUDE_DIRS

    @staticmethod
    def _make_parser() -> "etree.XMLParser":
        """
        MyBatis 매퍼용 안전한 lxml 파서를 생성한다.

        - no_network=True: 외부 DTD/엔티티 네트워크 로드 차단
        - load_dtd=False, resolve_entities=False: DTD 검증/엔티티 확장 안 함
        - strip_cdata=False: CDATA 섹션 원형 보존
        - remove_blank_text=False: 원본 포맷 최대한 유지

        Returns:
            구성된 XMLParser
        """
        return etree.XMLParser(
            no_network=True,
            load_dtd=False,
            resolve_entities=False,
            strip_cdata=False,
            remove_blank_text=False,
            recover=False,
        )

    def split(self, mapper_file: str) -> List[Fragment]:
        """
        매퍼 파일 하나를 SQL ID별 Fragment 리스트로 분할한다.

        Args:
            mapper_file: 매퍼 XML 파일 경로 (절대 또는 상대)

        Returns:
            Fragment 리스트

        Raises:
            ConversionError: 파일 읽기/파싱 실패, 루트가 <mapper>가 아닐 때
        """
        return self.split_file(mapper_file).fragments

    def split_file(self, mapper_file: str) -> MapperSplitResult:
        """
        매퍼 파일 하나를 분할해 결과 객체로 반환한다.

        Args:
            mapper_file: 매퍼 XML 파일 경로

        Returns:
            MapperSplitResult (매퍼 메타 + fragments)

        Raises:
            ConversionError: 파일 읽기/파싱 실패, 루트가 <mapper>가 아닐 때
        """
        if not os.path.isfile(mapper_file):
            raise ConversionError(
                "매퍼 파일을 찾을 수 없습니다", {"file": mapper_file}
            )

        try:
            tree = etree.parse(mapper_file, self._make_parser())
        except etree.XMLSyntaxError as e:
            raise ConversionError(
                "매퍼 XML 파싱에 실패했습니다",
                {"file": mapper_file, "error": str(e)},
            ) from e

        root = tree.getroot()
        if root.tag != "mapper":
            raise ConversionError(
                "루트 요소가 <mapper>가 아닙니다",
                {"file": mapper_file, "root_tag": str(root.tag)},
            )

        mapper_name = self._mapper_name(mapper_file)
        namespace = root.get("namespace")
        rel_path = self._relative_path(mapper_file)

        fragments: List[Fragment] = []
        for index, element in enumerate(root):
            fragment = self._element_to_fragment(
                element, index, mapper_name, namespace, rel_path
            )
            if fragment is not None:
                fragments.append(fragment)

        logger.info(
            "매퍼 분할 완료: %s → %d개 조각", mapper_name, len(fragments)
        )
        return MapperSplitResult(
            mapper_name=mapper_name,
            namespace=namespace,
            source_file=rel_path,
            fragments=fragments,
        )

    def _element_to_fragment(
        self,
        element: Any,
        index: int,
        mapper_name: str,
        namespace: Optional[str],
        source_file: str,
    ) -> Optional[Fragment]:
        """
        최상위 요소 하나를 Fragment로 변환한다.

        주석/처리지시(PI)는 건너뛴다. id가 없는 요소도 손실 방지를 위해
        합성 id를 부여해 조각으로 남긴다.

        Args:
            element: lxml 요소
            index: 매퍼 내 순서 (합성 id 및 병합 순서 복원용)
            mapper_name: 매퍼 이름
            namespace: 매퍼 namespace
            source_file: 원본 상대경로

        Returns:
            Fragment 또는 None(주석 등)
        """
        # 주석, PI 등은 tag가 문자열이 아님
        if not isinstance(element.tag, str):
            return None

        tag = element.tag
        element_id = element.get("id")
        has_id = element_id is not None
        sql_id = element_id if has_id else f"{_SYNTHETIC_ID_PREFIX}_{tag}_{index}"

        content = etree.tostring(element, encoding="unicode")

        return Fragment(
            mapper_name=mapper_name,
            namespace=namespace,
            sql_id=sql_id,
            statement_type=tag,
            content=content,
            source_file=source_file,
            has_id=has_id,
        )

    def _mapper_name(self, mapper_file: str) -> str:
        """
        파일 경로에서 매퍼 이름(확장자 제외)을 추출한다.

        Args:
            mapper_file: 매퍼 파일 경로

        Returns:
            매퍼 이름
        """
        base = os.path.basename(mapper_file)
        name, _ext = os.path.splitext(base)
        return name

    def _relative_path(self, mapper_file: str) -> str:
        """
        워크스페이스 기준 상대경로를 반환한다 (없으면 절대경로).

        Args:
            mapper_file: 매퍼 파일 경로

        Returns:
            상대 또는 절대 경로
        """
        abs_path = os.path.abspath(mapper_file)
        if self.source_workspace:
            ws = os.path.abspath(self.source_workspace)
            if abs_path.startswith(ws):
                return os.path.relpath(abs_path, ws)
        return abs_path

    def find_mapper_files(self, root_dir: Optional[str] = None) -> List[str]:
        """
        루트 디렉토리에서 MyBatis 매퍼 XML 파일 경로를 수집한다.

        <mapper 로 시작하는 요소를 갖는 .xml만 선별한다 (단순 문자열 감지이며,
        파싱이 아니라 후보 필터링 용도).

        Args:
            root_dir: 검색 루트 (없으면 source_workspace)

        Returns:
            매퍼 파일 경로 리스트 (정렬됨)
        """
        base = root_dir or self.source_workspace
        if not base or not os.path.isdir(base):
            raise ConversionError(
                "소스 워크스페이스 디렉토리를 찾을 수 없습니다", {"dir": base}
            )

        results: List[str] = []
        for dirpath, dirs, files in os.walk(base):
            # 제외 디렉토리는 하위 탐색을 아예 건너뜀 (in-place 수정으로 prune)
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for fname in files:
                if not fname.endswith(".xml"):
                    continue
                # macOS 리소스 포크/AppleDouble 파일(._*) 제외
                if fname.startswith("._"):
                    continue
                path = os.path.join(dirpath, fname)
                if self._looks_like_mapper(path):
                    results.append(path)
        results.sort()
        return results

    @staticmethod
    def _looks_like_mapper(path: str) -> bool:
        """
        파일이 MyBatis 매퍼인지 가볍게 감지한다 (앞부분만 읽어 문자열 확인).

        정규식/파싱이 아니라 후보 선별을 위한 단순 substring 검사다.

        Args:
            path: 파일 경로

        Returns:
            매퍼 가능성 여부
        """
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2048)
        except OSError:
            return False
        return "DTD Mapper" in head or "<mapper" in head

    def split_workspace(
        self, root_dir: Optional[str] = None
    ) -> Dict[str, MapperSplitResult]:
        """
        워크스페이스 내 모든 매퍼를 분할한다.

        Args:
            root_dir: 검색 루트 (없으면 source_workspace)

        Returns:
            {source_file(상대경로): MapperSplitResult} 딕셔너리
        """
        mapper_files = self.find_mapper_files(root_dir)
        logger.info("매퍼 파일 %d개 발견", len(mapper_files))

        results: Dict[str, MapperSplitResult] = {}
        for mapper_file in mapper_files:
            try:
                result = self.split_file(mapper_file)
            except ConversionError as e:
                # 개별 매퍼 실패는 건너뛰고 계속 (전체 중단 방지)
                logger.warning("매퍼 분할 실패 (건너뜀): %s", e)
                continue
            results[result.source_file] = result

        return results

    @staticmethod
    def build_mapping(results: Dict[str, MapperSplitResult]) -> Dict[str, Any]:
        """
        분할 결과로부터 조각↔원본 매핑 정보(mapping.json 내용)를 만든다.

        Args:
            results: split_workspace() 결과

        Returns:
            직렬화 가능한 매핑 딕셔너리
        """
        mappers: Dict[str, Any] = {}
        total_fragments = 0
        for source_file, result in results.items():
            frag_meta = [
                {
                    "sql_id": f.sql_id,
                    "statement_type": f.statement_type,
                    "has_id": f.has_id,
                }
                for f in result.fragments
            ]
            total_fragments += len(frag_meta)
            mappers[source_file] = {
                "mapper_name": result.mapper_name,
                "namespace": result.namespace,
                "fragment_count": len(frag_meta),
                "fragments": frag_meta,
            }

        return {
            "mapper_count": len(results),
            "fragment_count": total_fragments,
            "mappers": mappers,
        }
