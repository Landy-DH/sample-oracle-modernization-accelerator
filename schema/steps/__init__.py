"""
schema 단계 파이프라인 스텝 패키지

  - dms_sc_convert.py : DMS SC 1차 변환(추출→변환→S3 스크립트 export→평가)
  - s3_export.py      : 변환 결과 수집·압축·프로젝트 연결 S3 업로드
  - dms_full_load.py  : 3차 DMS full-load 데이터 마이그레이션(replication task)
  - fk_manager.py     : 3차 보조 - 타겟 FK 캡처/드랍/재생성

변경 이력:
2026-08-05 | OMA Team | 초기 생성
2026-08-05 | OMA Team | 3차(full-load) 스텝 추가: dms_full_load, fk_manager
"""
