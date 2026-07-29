# 바인드 변수 매핑 실패 추적

## 목적

변환 과정에서 바인드 변수를 딕셔너리에서 매핑하지 못한 경우를 체계적으로 추적하고 리포팅합니다.

---

## 1. 바인딩 실패 케이스

### 발생 원인

1. **테이블 추론 실패**
   - FROM 절이 복잡한 서브쿼리
   - 동적 테이블명 (${tableName})
   - 다중 JOIN에서 테이블 모호성

2. **컬럼 추론 실패**
   - SQL에 컬럼명이 명시되지 않음
   - 바인드 변수명과 컬럼명이 완전히 다름
   - 연산/함수 안의 바인드 변수

3. **딕셔너리 누락**
   - 뷰(View) 컬럼
   - 임시 테이블
   - 동적으로 생성되는 컬럼

4. **타입 추론 불가**
   - CASE WHEN 결과
   - UNION 결과
   - 서브쿼리 결과

---

## 2. 바인딩 실패 파일 구조

### 파일명
```
${REPORT_DIR}/binding_failures.csv
```

### CSV 구조
```csv
mapper_file,sql_id,bind_variable,inferred_table,inferred_column,failure_reason,line_number,sql_fragment
UserMapper.xml,searchUsers,userId,users,user_id,column_not_in_dictionary,15,"WHERE user_id = #{userId}"
OrderMapper.xml,complexQuery,statusCode,NULL,NULL,table_inference_failed,42,"WHERE status = #{statusCode}"
OrderMapper.xml,complexQuery,amount,orders,amount,column_not_in_dictionary,45,"AND amount > #{amount}"
```

### JSON 구조 (상세 버전)
```json
{
  "binding_failures": [
    {
      "mapper_file": "UserMapper.xml",
      "sql_id": "searchUsers",
      "bind_variable": "userId",
      "inferred_mapping": {
        "table": "users",
        "column": "user_id",
        "confidence": "high"
      },
      "lookup_attempted": "users.user_id",
      "failure_reason": "column_not_in_dictionary",
      "line_number": 15,
      "sql_fragment": "WHERE user_id = #{userId}",
      "suggestion": "Verify users.user_id exists in target schema",
      "severity": "high"
    },
    {
      "mapper_file": "OrderMapper.xml",
      "sql_id": "complexQuery",
      "bind_variable": "statusCode",
      "inferred_mapping": {
        "table": null,
        "column": null,
        "confidence": "none"
      },
      "lookup_attempted": null,
      "failure_reason": "table_inference_failed",
      "line_number": 42,
      "sql_fragment": "WHERE status = #{statusCode}",
      "suggestion": "Manually identify table for status column",
      "severity": "critical"
    }
  ]
}
```

### 실패 이유 코드

| 코드 | 설명 | 심각도 |
|------|------|--------|
| `column_not_in_dictionary` | 테이블.컬럼 조합이 딕셔너리에 없음 | high |
| `table_inference_failed` | 테이블 추론 실패 | critical |
| `column_inference_failed` | 컬럼 추론 실패 | critical |
| `ambiguous_mapping` | 여러 테이블에 같은 컬럼명 존재 | medium |
| `view_column` | 뷰의 컬럼 (딕셔너리 미포함) | medium |
| `dynamic_table` | 동적 테이블명 (${}) | critical |
| `subquery_result` | 서브쿼리 결과 컬럼 | low |
| `computed_column` | 계산된 컬럼 (CASE, 함수) | low |

---

## 3. LLM 변환 프롬프트 통합

### Phase 2 수정: 딕셔너리 조회 + 실패 추적

```
## Phase 2: 딕셌너리 조회 및 타입 분석

### 작업
추출된 각 컬럼에 대해 딕셔너리 조회 수행

### 바인드 변수 매핑 프로세스
```
1. SQL 파싱
   WHERE user_id = #{userId}
   → 바인드 변수: userId
   → 컬럼: user_id
   → 테이블 추론 (FROM 절)

2. 테이블.컬럼 매핑
   userId → users.user_id (추론)

3. 딕셔너리 조회
   lookup("users.user_id")
   
4. 조회 결과 처리
   - 성공: 타입 정보 사용, 형변환 판단
   - 실패: binding_failures에 기록
```

### 실패 기록 항목
```json
{
  "bind_variable": "userId",
  "inferred_table": "users",
  "inferred_column": "user_id",
  "lookup_attempted": "users.user_id",
  "failure_reason": "column_not_in_dictionary",
  "line_number": 15,
  "sql_fragment": "WHERE user_id = #{userId}",
  "confidence": "high",
  "suggestion": "Add users.user_id to dictionary or verify schema"
}
```

### 매핑 신뢰도 (Confidence)

**high**: 
- FROM 절에 단일 테이블
- 바인드 변수명과 컬럼명 유사 (userId ↔ user_id)
- 명확한 매핑

**medium**:
- JOIN 있지만 컬럼이 한 테이블에만 존재
- 바인드 변수명과 컬럼명 다름

**low**:
- 여러 테이블에 같은 컬럼명
- 복잡한 서브쿼리
- 추론 불확실

**none**:
- 테이블 추론 실패
- 컬럼 추론 실패
```

### Phase 5 수정: 출력 형식에 binding_failures 추가

```json
{
  "converted_sql": "...",
  "lookups_performed": [...],
  "changes": [...],
  "type_casts": [...],
  "test_cases_generated": [...],
  "warnings": [...],
  
  "binding_failures": [
    {
      "bind_variable": "userId",
      "inferred_table": "users",
      "inferred_column": "user_id",
      "lookup_attempted": "users.user_id",
      "failure_reason": "column_not_in_dictionary",
      "line_number": 15,
      "confidence": "high",
      "suggestion": "Verify schema or add to dictionary"
    }
  ],
  
  "statistics": {
    "total_bind_variables": 25,
    "successful_mappings": 22,
    "failed_mappings": 3,
    "mapping_success_rate": 88.0
  }
}
```

---

## 4. 워크플로우 통합

### Step 4-4: 바인딩 실패 집계

**Phase 4 변환 후**:

```python
# 모든 변환 결과 수집
all_binding_failures = []
for result in converted_results:
    if result['binding_failures']:
        all_binding_failures.extend(result['binding_failures'])

# CSV 생성
import csv
csv_path = f"{MAPPER_WORK_DIR}/reports/binding_failures.csv"
with open(csv_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'mapper_file', 'sql_id', 'bind_variable', 
        'inferred_table', 'inferred_column', 
        'failure_reason', 'confidence', 'line_number', 
        'sql_fragment', 'suggestion'
    ])
    writer.writeheader()
    writer.writerows(all_binding_failures)

# JSON 생성 (상세)
json_path = f"{MAPPER_WORK_DIR}/reports/binding_failures.json"
with open(json_path, 'w') as f:
    json.dump({
        'binding_failures': all_binding_failures,
        'summary': {
            'total_failures': len(all_binding_failures),
            'by_reason': count_by_reason(all_binding_failures),
            'by_severity': count_by_severity(all_binding_failures)
        }
    }, f, indent=2)
```

### Step 6: 최종 리포트에 포함

```json
{
  "conversion_summary": {
    "total_mappers": 50,
    "total_sql_fragments": 327,
    "total_bind_variables": 1854,
    
    "binding_statistics": {
      "successful_mappings": 1702,
      "failed_mappings": 152,
      "success_rate": 91.8,
      
      "failures_by_reason": {
        "column_not_in_dictionary": 89,
        "table_inference_failed": 35,
        "ambiguous_mapping": 18,
        "view_column": 10
      },
      
      "failures_by_severity": {
        "critical": 35,
        "high": 89,
        "medium": 28,
        "low": 0
      }
    },
    
    "files": {
      "binding_failures_csv": "reports/binding_failures.csv",
      "binding_failures_json": "reports/binding_failures.json"
    }
  }
}
```

---

## 5. 리포팅

### 콘솔 출력

```
========================================
Conversion Summary
========================================

Mappers Processed: 50
SQL Fragments: 327
Bind Variables: 1,854

Binding Statistics:
  ✓ Successful: 1,702 (91.8%)
  ✗ Failed: 152 (8.2%)

Failures by Severity:
  ⚠ Critical: 35 (table/column inference failed)
  ! High: 89 (column not in dictionary)
  - Medium: 28 (ambiguous mapping, view)

Files Generated:
  • reports/binding_failures.csv
  • reports/binding_failures.json

Action Required:
  Review binding_failures.csv for manual mapping
  35 critical failures require immediate attention
========================================
```

### CSV 리포트 (Excel 열기 가능)

```csv
mapper_file,sql_id,bind_variable,inferred_table,inferred_column,failure_reason,confidence,suggestion
UserMapper.xml,searchUsers,userId,users,user_id,column_not_in_dictionary,high,Add users.user_id to dictionary
OrderMapper.xml,complexQuery,statusCode,NULL,NULL,table_inference_failed,none,Manually identify table
OrderMapper.xml,getByDate,fromDate,orders,created_date,column_not_in_dictionary,high,Verify orders.created_date exists
ProductMapper.xml,searchProducts,categoryId,products,category_id,ambiguous_mapping,medium,Multiple tables have category_id
```

### 액션 우선순위

**Critical (즉시 처리)**:
- table_inference_failed
- column_inference_failed
→ 수동으로 테이블/컬럼 식별 필요

**High (우선 처리)**:
- column_not_in_dictionary (confidence: high)
→ 딕셔너리 누락 또는 스키마 불일치 확인

**Medium (검토 필요)**:
- ambiguous_mapping
- view_column
→ 올바른 매핑 확인

**Low (참고)**:
- subquery_result
- computed_column
→ 일반적으로 형변환 불필요

---

## 6. 수동 보정 프로세스

### 6.1 바인딩 실패 수정 파일

**파일**: `${REPORT_DIR}/binding_corrections.csv`

```csv
mapper_file,sql_id,bind_variable,corrected_table,corrected_column,notes
OrderMapper.xml,complexQuery,statusCode,orders,status,status 컬럼 확인됨
ProductMapper.xml,searchProducts,categoryId,products,category_id,products.category_id 사용
```

### 6.2 재변환

```python
# 수정 파일 로드
corrections = load_corrections('reports/binding_corrections.csv')

# 실패한 조각만 재변환
failed_fragments = get_failed_fragments(binding_failures)

for fragment in failed_fragments:
    # 수정된 매핑 적용
    mapping = corrections.get(fragment.id)
    if mapping:
        # 딕셔너리 조회 재시도
        result = lookup(f"{mapping.table}.{mapping.column}")
        # 변환 재실행

# 재변환 결과 병합
```

---

## 7. 예방 전략

### 딕셔너리 품질 향상

1. **뷰 포함**
   ```sql
   -- 뷰도 딕셔너리에 포함
   SELECT table_name, column_name, data_type
   FROM information_schema.columns
   WHERE table_schema = 'appdb'
     AND table_type IN ('BASE TABLE', 'VIEW')
   ```

2. **별칭 매핑 추가**
   ```json
   {
     "users.user_id": {
       "aliases": ["userId", "user_id", "id"],
       "data_type": "integer"
     }
   }
   ```

3. **관계 정보 추가**
   ```json
   {
     "orders.user_id": {
       "data_type": "integer",
       "foreign_key": {
         "references": "users.user_id"
       }
   }
   ```

### LLM 추론 향상

**Few-shot 예시 추가**:
```
바인드 변수 매핑 예시:

예시 1:
SQL: SELECT * FROM users WHERE user_id = #{userId}
추론: userId → users.user_id (신뢰도: high)

예시 2:
SQL: SELECT * FROM orders o JOIN users u ON o.user_id = u.user_id
     WHERE o.status = #{orderStatus}
추론: orderStatus → orders.status (신뢰도: high, 테이블 별칭 'o')

예시 3:
SQL: SELECT * FROM (SELECT user_id FROM users) t WHERE t.user_id = #{id}
추론: id → users.user_id (신뢰도: medium, 서브쿼리 컬럼)
```

---

## 8. 통계 및 메트릭

### 변환 품질 지표

```python
# 바인딩 성공률
binding_success_rate = (successful / total) * 100

# 신뢰도별 분포
confidence_distribution = {
    'high': count_high / total_attempts,
    'medium': count_medium / total_attempts,
    'low': count_low / total_attempts,
    'none': count_none / total_attempts
}

# 실패 원인 분포
failure_distribution = {
    'column_not_in_dictionary': 58.5%,
    'table_inference_failed': 23.0%,
    'ambiguous_mapping': 11.8%,
    'view_column': 6.7%
}
```

### 품질 임계값

- **Excellent**: 성공률 ≥ 95%
- **Good**: 성공률 ≥ 90%
- **Acceptable**: 성공률 ≥ 85%
- **Needs Review**: 성공률 < 85%

---

## 9. 디렉토리 구조 업데이트

```
${PROJECT_WORK_DIR}/
├─ mappers/
│   ├─ original/
│   ├─ fragmented/
│   ├─ converted/
│   └─ merged/
├─ output/
├─ testcases/
└─ reports/
    ├─ conversion-summary.json       # 전체 변환 요약
    ├─ binding_failures.csv          # 바인딩 실패 (CSV)
    ├─ binding_failures.json         # 바인딩 실패 (JSON 상세)
    ├─ binding_corrections.csv       # 수동 보정 (사용자 작성)
    ├─ validation-errors.json        # 검증 에러
    └─ manual-review-list.json       # 수동 검토 리스트
```

---

## 10. 체크리스트

### 변환 완료 후 확인

- [ ] binding_failures.csv 존재 확인
- [ ] 바인딩 성공률 확인 (90% 이상 권장)
- [ ] Critical 실패 건수 확인
- [ ] High 실패 건수 확인
- [ ] binding_corrections.csv 작성 (필요 시)
- [ ] 재변환 실행 (수정 사항 있으면)
- [ ] 최종 성공률 확인

### 프로덕션 배포 전

- [ ] 바인딩 성공률 85% 이상
- [ ] Critical 실패 0건
- [ ] High 실패 검토 완료
- [ ] 수동 보정 적용 완료

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 바인드 변수 매핑 실패 추적 및 리포팅
