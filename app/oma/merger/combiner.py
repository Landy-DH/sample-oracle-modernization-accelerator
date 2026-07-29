"""
매퍼 병합 모듈

변환된 조각(Fragment 단위)들을 원본 매퍼 구조로 재조립한다 (Fragmenter의 역작업).
원본 매퍼의 뼈대(namespace, DOCTYPE, 요소 순서, 주석)를 유지하면서, 각 statement를
변환된 조각으로 교체한다.

파싱/직렬화는 lxml.etree로 수행한다 (정규식으로 XML 조작 금지 — 15-coding-guidelines.md).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - MapperCombiner 구현: merge(원본 트리 기반 요소 교체) + merge_to_string
  - sql_id+statement_type으로 조각 매칭, 누락/미사용 조각 검증(MergeReport)
  - 원본 DOCTYPE/namespace/순서 보존
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lxml import etree

from oma.fragmenter.splitter import Fragment
from oma.utils.exceptions import ConversionError

logger = logging.getLogger(__name__)


@dataclass
class MergeReport:
    """병합 결과 리포트"""

    mapper_name: str
    source_file: str
    replaced: List[str] = field(default_factory=list)   # 교체된 sql_id 목록
    not_replaced: List[str] = field(default_factory=list)  # 조각 없어 원본 유지
    unused_fragments: List[str] = field(default_factory=list)  # 매칭 안 된 조각


class MapperCombiner:
    """
    매퍼 조각 재조립기

    원본 매퍼 파일을 뼈대로 삼아, 제공된 변환 조각으로 각 statement를 교체한다.
    """

    @staticmethod
    def _make_parser() -> "etree.XMLParser":
        """조각/매퍼 파싱용 안전 파서 (외부 DTD 네트워크 차단, CDATA 보존)."""
        return etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            strip_cdata=False, remove_blank_text=False,
        )

    def merge(
        self, original_mapper_file: str, fragments: List[Fragment]
    ) -> "etree._ElementTree":
        """
        원본 매퍼를 뼈대로 변환 조각을 반영한 ElementTree를 만든다.

        Args:
            original_mapper_file: 원본 매퍼 파일 경로
            fragments: 변환된 조각 리스트 (content가 변환 결과)

        Returns:
            병합된 lxml ElementTree

        Raises:
            ConversionError: 원본 파싱 실패/루트가 <mapper>가 아닐 때
        """
        tree, report = self._merge_with_report(original_mapper_file, fragments)
        self._log_report(report)
        return tree

    def merge_with_report(
        self, original_mapper_file: str, fragments: List[Fragment]
    ) -> "tuple":
        """
        merge와 동일하되 (ElementTree, MergeReport)를 함께 반환한다.

        Args:
            original_mapper_file: 원본 매퍼 파일 경로
            fragments: 변환된 조각 리스트

        Returns:
            (ElementTree, MergeReport)
        """
        tree, report = self._merge_with_report(original_mapper_file, fragments)
        self._log_report(report)
        return tree, report

    def _merge_with_report(
        self, original_mapper_file: str, fragments: List[Fragment]
    ) -> "tuple":
        """실제 병합 로직 (트리 요소 교체) + 리포트 생성."""
        if not os.path.isfile(original_mapper_file):
            raise ConversionError(
                "원본 매퍼 파일을 찾을 수 없습니다",
                {"file": original_mapper_file},
            )

        try:
            tree = etree.parse(original_mapper_file, self._make_parser())
        except etree.XMLSyntaxError as e:
            raise ConversionError(
                "원본 매퍼 파싱에 실패했습니다",
                {"file": original_mapper_file, "error": str(e)},
            ) from e

        root = tree.getroot()
        if root.tag != "mapper":
            raise ConversionError(
                "루트 요소가 <mapper>가 아닙니다",
                {"file": original_mapper_file, "root_tag": str(root.tag)},
            )

        mapper_name = self._mapper_name(original_mapper_file)
        # 조각을 (statement_type, sql_id)로 인덱싱
        frag_index = self._index_fragments(fragments)
        used_keys: set = set()

        report = MergeReport(
            mapper_name=mapper_name,
            source_file=original_mapper_file,
        )

        for index, element in enumerate(list(root)):
            if not isinstance(element.tag, str):
                continue  # 주석/PI는 원본 유지

            key = self._element_key(element, index)
            fragment = frag_index.get(key)
            if fragment is None:
                # id 있는 statement인데 조각이 없으면 not_replaced로 기록
                if element.get("id") is not None:
                    report.not_replaced.append(element.get("id"))
                continue

            self._replace_element(root, element, fragment)
            used_keys.add(key)
            if element.get("id") is not None:
                report.replaced.append(element.get("id"))

        report.unused_fragments = [
            f.sql_id for k, f in frag_index.items() if k not in used_keys
        ]
        return tree, report

    def merge_to_string(
        self, original_mapper_file: str, fragments: List[Fragment]
    ) -> str:
        """
        병합 결과를 XML 문자열(선언 포함)로 반환한다.

        Args:
            original_mapper_file: 원본 매퍼 파일 경로
            fragments: 변환된 조각 리스트

        Returns:
            직렬화된 매퍼 XML 문자열
        """
        tree = self.merge(original_mapper_file, fragments)
        # unicode + xml_declaration 동시 사용 불가 → UTF-8 바이트로 직렬화 후 디코드
        raw = etree.tostring(
            tree, encoding="UTF-8", xml_declaration=True, doctype=self._doctype(tree)
        )
        return raw.decode("utf-8")

    def merge_to_file(
        self,
        original_mapper_file: str,
        fragments: List[Fragment],
        output_path: str,
    ) -> None:
        """
        병합 결과를 파일로 저장한다 (디렉토리 자동 생성).

        Args:
            original_mapper_file: 원본 매퍼 파일 경로
            fragments: 변환된 조각 리스트
            output_path: 저장 경로
        """
        content = self.merge_to_string(original_mapper_file, fragments)
        directory = os.path.dirname(output_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("병합 매퍼 저장: %s", output_path)

    def _replace_element(
        self, root: Any, old_element: Any, fragment: Fragment
    ) -> None:
        """
        원본 요소를 변환 조각으로 교체한다 (tail 보존).

        Args:
            root: 매퍼 루트 요소
            old_element: 교체될 원본 요소
            fragment: 변환 조각
        """
        try:
            new_element = etree.fromstring(
                fragment.content.encode("utf-8"), self._make_parser()
            )
        except etree.XMLSyntaxError as e:
            raise ConversionError(
                "변환 조각 파싱에 실패했습니다",
                {"sql_id": fragment.sql_id, "error": str(e)},
            ) from e

        # 원본 요소의 tail(줄바꿈/들여쓰기)을 새 요소에 승계해 포맷 유지
        new_element.tail = old_element.tail
        old_element.addprevious(new_element)
        root.remove(old_element)

    @staticmethod
    def _index_fragments(fragments: List[Fragment]) -> Dict[tuple, Fragment]:
        """조각을 (statement_type, sql_id) 키로 인덱싱한다."""
        return {(f.statement_type, f.sql_id): f for f in fragments}

    @staticmethod
    def _element_key(element: Any, index: int) -> tuple:
        """
        원본 요소의 매칭 키를 만든다 (조각 인덱싱과 동일 규칙).

        id 없는 요소는 splitter의 합성 id 규칙(__el_{tag}_{index})과 맞춘다.
        """
        tag = element.tag
        element_id = element.get("id")
        if element_id is not None:
            return (tag, element_id)
        return (tag, f"__el_{tag}_{index}")

    @staticmethod
    def _mapper_name(mapper_file: str) -> str:
        """파일 경로에서 매퍼 이름(확장자 제외)을 추출한다."""
        base = os.path.basename(mapper_file)
        name, _ext = os.path.splitext(base)
        return name

    @staticmethod
    def _doctype(tree: "etree._ElementTree") -> Optional[str]:
        """원본 트리의 DOCTYPE 문자열을 반환한다 (없으면 None)."""
        docinfo = tree.docinfo
        return docinfo.doctype or None

    @staticmethod
    def _log_report(report: MergeReport) -> None:
        """병합 리포트를 로깅한다."""
        logger.info(
            "매퍼 병합: %s (교체 %d, 원본유지 %d, 미사용조각 %d)",
            report.mapper_name, len(report.replaced),
            len(report.not_replaced), len(report.unused_fragments),
        )
        if report.not_replaced:
            logger.warning(
                "병합: 변환 조각 없어 원본 유지된 statement: %s",
                report.not_replaced,
            )
        if report.unused_fragments:
            logger.warning(
                "병합: 원본에 매칭되지 않은 조각: %s", report.unused_fragments
            )
