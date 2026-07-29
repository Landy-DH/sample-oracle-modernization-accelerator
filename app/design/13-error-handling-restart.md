# 에러 처리, 재시작 및 예외 케이스

## 개요

실전 환경에서 발생 가능한 에러, 중단, 예외 케이스를 처리하고 안전하게 재시작하는 전략

---

## 1. 에러 처리 전략

### 1.1 에러 분류

| 에러 유형 | 처리 방식 | 재시도 | 예시 |
|----------|----------|--------|------|
| **Transient** | 자동 재시도 | 3회 + 백오프 | API timeout, DB connection timeout |
| **Rate Limit** | 대기 후 재시도 | 무제한 | LLM API rate limit |
| **Validation** | 실패 기록, 계속 진행 | 없음 | SQL 변환 실패, TC 생성 실패 |
| **Fatal** | 즉시 중단 | 없음 | AWS credentials 없음, 잘못된 설정 |
| **Skippable** | 경고 기록, 계속 진행 | 없음 | DBLINK, 변환 불가 구문 |

---

### 1.2 LLM API 에러 처리

#### Rate Limit 대응

```python
# oma/converter/llm_client.py

import time
from anthropic import RateLimitError

class LLMClient:
    """LLM API 호출 with rate limit handling"""
    
    def __init__(self, config):
        self.config = config
        self.max_retries = 3
        self.base_delay = 2  # 초
        
        # Rate limit 설정
        self.requests_per_minute = config.get('LLM_RPM_LIMIT', 50)
        self.min_interval = 60.0 / self.requests_per_minute
        self.last_request_time = 0
    
    def call_llm(self, prompt, retry_count=0):
        """LLM API 호출 with retry"""
        
        # Rate limit 준수 (요청 간 최소 간격)
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        
        try:
            self.last_request_time = time.time()
            
            # API 호출
            response = self.bedrock_client.invoke_model(
                model_id=self.config.get('LLM_MODEL_ID'),
                prompt=prompt
            )
            
            return response
            
        except RateLimitError as e:
            # Rate limit 에러 - 대기 후 재시도
            wait_time = self.calculate_backoff(retry_count)
            
            print(f"⏸  Rate limit hit. Waiting {wait_time}s...")
            time.sleep(wait_time)
            
            return self.call_llm(prompt, retry_count + 1)
            
        except TimeoutError as e:
            # Timeout - 재시도 제한
            if retry_count < self.max_retries:
                wait_time = self.base_delay * (2 ** retry_count)
                print(f"⏸  Timeout. Retry {retry_count+1}/{self.max_retries} in {wait_time}s...")
                time.sleep(wait_time)
                return self.call_llm(prompt, retry_count + 1)
            else:
                raise ConversionError(f"LLM timeout after {self.max_retries} retries")
        
        except Exception as e:
            # 기타 에러 - 즉시 실패
            raise ConversionError(f"LLM API error: {str(e)}")
    
    def calculate_backoff(self, retry_count):
        """Exponential backoff"""
        # Rate limit은 긴 대기 시간
        base = 60  # 1분 기본
        return min(base * (2 ** retry_count), 300)  # 최대 5분
```

#### 설정

```properties
# oma.properties

# LLM Rate Limit (분당 요청 수)
LLM_RPM_LIMIT=50

# LLM Timeout (초)
LLM_TIMEOUT_SECONDS=120

# 재시도 설정
LLM_MAX_RETRIES=3
LLM_RETRY_BASE_DELAY=2
```

---

### 1.3 DB 연결 에러 처리

```python
# oma/database/connection_manager.py

from contextlib import contextmanager
import psycopg2

class ConnectionManager:
    """DB 연결 관리 with retry"""
    
    def __init__(self, config):
        self.config = config
        self.pool = self.create_pool()
    
    def create_pool(self):
        """커넥션 풀 생성"""
        return psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=self.config.get('TARGET_DB_HOST'),
            port=self.config.get('TARGET_DB_PORT'),
            database=self.config.get('TARGET_DB_NAME'),
            user=self.config.get('TARGET_DB_USER'),
            password=self.config.get('TARGET_DB_PASSWORD'),
            connect_timeout=10
        )
    
    @contextmanager
    def get_connection(self, retry_count=0):
        """커넥션 획득 with retry"""
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
            conn.commit()
        except psycopg2.OperationalError as e:
            if retry_count < 3:
                time.sleep(2 ** retry_count)
                with self.get_connection(retry_count + 1) as retry_conn:
                    yield retry_conn
            else:
                raise DatabaseError(f"DB connection failed after 3 retries: {e}")
        finally:
            if conn:
                self.pool.putconn(conn)
```

---

## 2. 체크포인트 및 재시작

### 2.1 체크포인트 파일

**위치**: `${CHECKPOINT_PATH}`

```json
{
  "run_id": "20260726_143022",
  "phase": "phase4_conversion",
  "started_at": "2026-07-26T14:30:22Z",
  "last_checkpoint_at": "2026-07-26T14:45:18Z",
  
  "progress": {
    "phase1_dictionary": "completed",
    "phase2_copy_mappers": "completed",
    "phase3_fragment": "completed",
    "phase4_conversion": "in_progress",
    "phase5_merge": "pending",
    "phase6_validation": "pending",
    "phase7_copy_target": "pending"
  },
  
  "phase4_detail": {
    "total_fragments": 327,
    "completed": 245,
    "failed": 3,
    "remaining": 79,
    
    "completed_fragments": [
      "UserMapper_getUser.xml",
      "UserMapper_insertUser.xml",
      "..."
    ],
    
    "failed_fragments": [
      {
        "file": "OrderMapper_complexQuery.xml",
        "error": "LLM timeout after 3 retries",
        "retry_count": 3,
        "can_retry": true
      }
    ]
  },
  
  "statistics": {
    "llm_api_calls": 245,
    "llm_total_tokens": 1250000,
    "total_duration_seconds": 892
  }
}
```

### 2.2 체크포인트 저장

```python
# oma/workflow/checkpoint.py

import json
import os
from datetime import datetime

class CheckpointManager:
    """체크포인트 관리"""
    
    def __init__(self, work_dir):
        self.checkpoint_file = f"{work_dir}/.checkpoint.json"
        self.checkpoint = self.load_or_create()
    
    def load_or_create(self):
        """체크포인트 로드 또는 생성"""
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file) as f:
                return json.load(f)
        else:
            return self.create_new_checkpoint()
    
    def create_new_checkpoint(self):
        """새 체크포인트 생성"""
        return {
            "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "phase": "phase1_dictionary",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "progress": {
                "phase1_dictionary": "pending",
                "phase2_copy_mappers": "pending",
                "phase3_fragment": "pending",
                "phase4_conversion": "pending",
                "phase5_merge": "pending",
                "phase6_validation": "pending",
                "phase7_copy_target": "pending"
            },
            "statistics": {}
        }
    
    def mark_phase_started(self, phase):
        """페이즈 시작 표시"""
        self.checkpoint["phase"] = phase
        self.checkpoint["progress"][phase] = "in_progress"
        self.save()
    
    def mark_phase_completed(self, phase):
        """페이즈 완료 표시"""
        self.checkpoint["progress"][phase] = "completed"
        self.checkpoint["last_checkpoint_at"] = datetime.utcnow().isoformat() + "Z"
        self.save()
    
    def mark_fragment_completed(self, fragment_file):
        """조각 완료 표시"""
        if "phase4_detail" not in self.checkpoint:
            self.checkpoint["phase4_detail"] = {
                "completed": 0,
                "failed": 0,
                "completed_fragments": []
            }
        
        detail = self.checkpoint["phase4_detail"]
        detail["completed"] += 1
        detail["completed_fragments"].append(fragment_file)
        
        self.save()
    
    def mark_fragment_failed(self, fragment_file, error, retry_count):
        """조각 실패 표시"""
        if "phase4_detail" not in self.checkpoint:
            self.checkpoint["phase4_detail"] = {
                "completed": 0,
                "failed": 0,
                "failed_fragments": []
            }
        
        detail = self.checkpoint["phase4_detail"]
        detail["failed"] += 1
        
        if "failed_fragments" not in detail:
            detail["failed_fragments"] = []
        
        detail["failed_fragments"].append({
            "file": fragment_file,
            "error": str(error),
            "retry_count": retry_count,
            "can_retry": retry_count < 3,
            "failed_at": datetime.utcnow().isoformat() + "Z"
        })
        
        self.save()
    
    def save(self):
        """체크포인트 저장"""
        with open(self.checkpoint_file, 'w') as f:
            json.dump(self.checkpoint, f, indent=2)
    
    def is_completed(self, phase):
        """페이즈 완료 여부"""
        return self.checkpoint["progress"].get(phase) == "completed"
    
    def get_pending_fragments(self):
        """미완료 조각 목록"""
        if "phase4_detail" not in self.checkpoint:
            return []
        
        detail = self.checkpoint["phase4_detail"]
        completed = set(detail.get("completed_fragments", []))
        
        # 전체 조각 목록에서 완료된 것 제외
        all_fragments = self.list_all_fragments()
        return [f for f in all_fragments if f not in completed]
```

---

### 2.3 재시작 로직

```python
# scripts/run_oma.py

from oma.workflow.checkpoint import CheckpointManager
from oma.workflow.phases import *

def main():
    config = Config('config/oma.properties', 'ap-northeast-2')
    checkpoint = CheckpointManager(config.get('MAPPER_WORK_DIR'))
    
    print(f"{'='*50}")
    print(f"OMA Conversion Tool")
    print(f"{'='*50}\n")
    
    # 재시작 확인
    if checkpoint.checkpoint["phase"] != "phase1_dictionary":
        print(f"⚠️  Previous run detected:")
        print(f"   Run ID: {checkpoint.checkpoint['run_id']}")
        print(f"   Last Phase: {checkpoint.checkpoint['phase']}")
        print(f"   Last Checkpoint: {checkpoint.checkpoint.get('last_checkpoint_at', 'N/A')}")
        
        response = input("\nResume from checkpoint? (y/n): ")
        if response.lower() != 'y':
            print("Starting fresh run...")
            checkpoint = CheckpointManager(config.get('MAPPER_WORK_DIR'))
            checkpoint.checkpoint = checkpoint.create_new_checkpoint()
            checkpoint.save()
    
    # Phase 1: Dictionary
    if not checkpoint.is_completed("phase1_dictionary"):
        checkpoint.mark_phase_started("phase1_dictionary")
        print("\n[Phase 1] Building schema dictionary...")
        build_dictionary(config)
        checkpoint.mark_phase_completed("phase1_dictionary")
        print("✓ Dictionary completed")
    else:
        print("\n[Phase 1] Dictionary (skipped - already completed)")
    
    # Phase 2: Copy Mappers
    if not checkpoint.is_completed("phase2_copy_mappers"):
        checkpoint.mark_phase_started("phase2_copy_mappers")
        print("\n[Phase 2] Copying mappers...")
        copy_mappers(config)
        checkpoint.mark_phase_completed("phase2_copy_mappers")
        print("✓ Copy completed")
    else:
        print("\n[Phase 2] Copy Mappers (skipped - already completed)")
    
    # Phase 3: Fragment
    if not checkpoint.is_completed("phase3_fragment"):
        checkpoint.mark_phase_started("phase3_fragment")
        print("\n[Phase 3] Fragmenting mappers...")
        fragment_mappers(config)
        checkpoint.mark_phase_completed("phase3_fragment")
        print("✓ Fragmentation completed")
    else:
        print("\n[Phase 3] Fragment (skipped - already completed)")
    
    # Phase 4: Conversion (재시작 지원!)
    if not checkpoint.is_completed("phase4_conversion"):
        checkpoint.mark_phase_started("phase4_conversion")
        print("\n[Phase 4] Converting SQL...")
        
        # 미완료 조각만 처리
        pending_fragments = checkpoint.get_pending_fragments()
        
        if pending_fragments:
            print(f"   Resuming: {len(pending_fragments)} fragments remaining")
            convert_fragments(config, pending_fragments, checkpoint)
        else:
            print(f"   Starting: all fragments")
            all_fragments = list_all_fragments(config)
            convert_fragments(config, all_fragments, checkpoint)
        
        checkpoint.mark_phase_completed("phase4_conversion")
        print("✓ Conversion completed")
    else:
        print("\n[Phase 4] Conversion (skipped - already completed)")
    
    # Phase 5-7 생략...
    
    print(f"\n{'='*50}")
    print(f"OMA Conversion Completed!")
    print(f"{'='*50}\n")
```

---

### 2.4 실패 조각만 선택 재변환 (부분 재실행)

전체 파이프라인이 끝난 뒤, **일부 조각만 변환 품질이 낮은 경우**(LLM이
`conversion_status=failed`/`partial`로 표기했거나, 특정 조각만 수동으로 다시
돌리고 싶은 경우) 전체를 재실행하지 않고 해당 조각만 재변환한다.

**원리**: Phase4는 `checkpoint.is_fragment_completed(frag_id)`로 완료 조각을
건너뛰므로, 재변환하려는 조각을 `completed_fragments`에서 제거하고
`phase4_conversion`(및 그 하류 phase)을 `pending`으로 되돌리면, 다음
`--phase convert` 실행 시 **해당 조각만** 다시 변환된다. 나머지 성공 조각은
그대로 스킵된다.

**유틸리티**: `scripts/reset_failed_fragments.py`

```bash
# 1) report.status 로 재변환 대상 자동 식별 (기본: failed, partial)
python3.11 scripts/reset_failed_fragments.py --config oma.properties --dry-run

# 2) failed 만 대상으로 실제 리셋 (체크포인트는 .bak-<run_id> 로 자동 백업)
python3.11 scripts/reset_failed_fragments.py --config oma.properties --status failed

# 특정 조각을 명시 지정할 수도 있음
python3.11 scripts/reset_failed_fragments.py --config oma.properties \
    --fragment NoticeMapper__retrieveGscmNoticeList

# 3) 재변환 + 병합 재실행 (하류 phase도 pending 이므로 함께 재실행됨)
python3.11 scripts/run_oma.py --config oma.properties --phase convert,merge
```

**스크립트 동작**:
1. `converted/*.report.json`을 읽어 대상 status(`failed`/`partial`)를 가진
   조각 id를 식별한다(순수 JSON 파싱 — SQL/XML 정규식 파싱 아님).
2. 체크포인트를 `.checkpoint.json.bak-<run_id>`로 백업한다.
3. 대상 조각을 `phase4_detail.completed_fragments`에서 제거하고 `completed`
   카운트를 갱신한다.
4. `phase4_conversion`·`phase5_merge`·`phase6_validation`·`phase7_copy_target`을
   `pending`으로 되돌린다(재변환 결과가 하류 phase에 반영되도록).

**주의 — false negative(오탐)**: 원본 SQL이 이미 타겟 DB 호환이면 LLM이
"바꿀 게 없음 → 원본 반환"하면서 `status=failed`로 잘못 표기할 수 있다
(converted == original, warnings/type_casts 0). 이 경우 재변환해도 계속
failed로 남지만 **실제 변환 결함은 아니며**, validation에서 실행하면 통과한다.
재변환 후에도 failed인 조각은 converted와 original을 비교해 실제 결함인지
오탐인지 판별한다.

---

## 3. 예외 케이스 처리

### 3.1 DBLINK (변환 불가)

**정책**: 변환하지 않고 에러 리포팅

```python
# oma/converter/validator.py

def detect_unsupported_features(sql):
    """변환 불가 구문 감지"""
    
    issues = []
    
    # DBLINK 감지
    if re.search(r'@[\w\.]+', sql):
        dblink_match = re.findall(r'@([\w\.]+)', sql)
        issues.append({
            "type": "dblink",
            "severity": "error",
            "message": f"DBLINK detected: {', '.join(dblink_match)}",
            "description": "DBLINK is not supported. Must be refactored to use local tables or API calls.",
            "suggestion": "Options: 1) Replicate remote data locally, 2) Replace with REST API call, 3) Use FDW (Foreign Data Wrapper) in PostgreSQL"
        })
    
    # CONNECT BY (계층 쿼리)
    if re.search(r'CONNECT\s+BY', sql, re.IGNORECASE):
        issues.append({
            "type": "connect_by",
            "severity": "warning",
            "message": "Hierarchical query (CONNECT BY) detected",
            "description": "PostgreSQL uses WITH RECURSIVE instead",
            "suggestion": "LLM will attempt conversion, but manual review recommended"
        })
    
    # ROWNUM
    if re.search(r'\bROWNUM\b', sql, re.IGNORECASE):
        issues.append({
            "type": "rownum",
            "severity": "warning",
            "message": "ROWNUM detected",
            "description": "PostgreSQL uses LIMIT/OFFSET",
            "suggestion": "LLM will convert to LIMIT, but verify ORDER BY clause"
        })
    
    return issues
```

**리포트**:

```json
{
  "unsupported_features": [
    {
      "mapper": "RemoteDataMapper.xml",
      "sql_id": "getRemoteData",
      "line_number": 15,
      "type": "dblink",
      "severity": "error",
      "sql_fragment": "SELECT * FROM remote_table@remote_db",
      "message": "DBLINK detected: remote_db",
      "suggestion": "Options: 1) Replicate remote data locally, 2) Replace with REST API call, 3) Use PostgreSQL FDW",
      "action_required": "manual_refactoring"
    }
  ]
}
```

**콘솔 출력**:

```
⚠️  Unsupported Features Detected

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ ERROR: DBLINK (1 occurrence)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  File: RemoteDataMapper.xml
  SQL ID: getRemoteData
  Line: 15
  
  SQL: SELECT * FROM remote_table@remote_db
  
  Issue: DBLINK is not supported in PostgreSQL
  
  Options:
    1. Replicate remote data locally (ETL)
    2. Replace with REST API call
    3. Use PostgreSQL Foreign Data Wrapper (FDW)
  
  Action: Manual refactoring required

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  1 mapper(s) require manual attention
   See: reports/unsupported-features.json
```

---

### 3.2 오라클 전용 함수/시퀀스 (LLM 변환)

**정책**: LLM이 자동 변환 (프롬프트에 포함됨)

이미 `05-conversion-prompt.md`에 포함되어 있음:

```
### 오라클 함수 → PostgreSQL 변환

NVL(a, b) → COALESCE(a, b)
NVL2(a, b, c) → CASE WHEN a IS NOT NULL THEN b ELSE c END
DECODE(col, val1, res1, val2, res2, default) → CASE col WHEN val1 THEN res1 ...
TO_DATE(str, fmt) → TO_DATE(str, fmt) (PostgreSQL 포맷 조정)
TO_CHAR(date, fmt) → TO_CHAR(date, fmt) (PostgreSQL 포맷 조정)
SYSDATE → CURRENT_TIMESTAMP
TRUNC(date) → DATE_TRUNC('day', date)
ADD_MONTHS(date, n) → date + INTERVAL 'n months'
MONTHS_BETWEEN(d1, d2) → EXTRACT(YEAR FROM AGE(d1, d2)) * 12 + EXTRACT(MONTH FROM AGE(d1, d2))

### 시퀀스

seq_name.NEXTVAL → NEXTVAL('seq_name')
seq_name.CURRVAL → CURRVAL('seq_name')
```

**검증**: 변환 후 validation에서 실행 결과 비교로 확인

---

### 3.3 HINT 주석

**정책**: 주석으로 보존, 경고만

```python
def handle_hints(sql):
    """Oracle HINT 처리"""
    
    # /*+ INDEX(...) */ 패턴 감지
    hint_pattern = r'/\*\+.*?\*/'
    hints = re.findall(hint_pattern, sql)
    
    if hints:
        # 주석으로 변환
        sql_converted = sql
        for hint in hints:
            # /*+ INDEX(t idx) */ → /* Oracle hint: INDEX(t idx) */
            comment = f"/* Oracle hint: {hint[3:-2].strip()} */"
            sql_converted = sql_converted.replace(hint, comment)
        
        return {
            "sql": sql_converted,
            "warning": f"Oracle hints converted to comments: {len(hints)} found",
            "hints": hints
        }
    
    return {"sql": sql}
```

---

## 4. 실행 환경 요구사항

### 4.1 Python 환경

```bash
# requirements.txt
anthropic>=0.18.0
boto3>=1.34.0
psycopg2-binary>=2.9.9
cx-Oracle>=8.3.0     # Oracle 소스 DB용
pymysql>=1.1.0       # MySQL 타겟 DB용 (옵션)
lxml>=5.0.0
pyyaml>=6.0.1
jsonschema>=4.20.0
```

```properties
# oma.properties 추가

# Python 환경
PYTHON_VERSION=3.10+

# 의존성 설치
# pip install -r requirements.txt
```

---

### 4.2 Java 환경

```xml
<!-- pom.xml 추가 -->
<properties>
    <java.version>11</java.version>
    <maven.compiler.source>11</maven.compiler.source>
    <maven.compiler.target>11</maven.compiler.target>
</properties>
```

---

### 4.3 AWS 권한

**필수 권한**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:ap-northeast-2::foundation-model/anthropic.claude-3-5-sonnet-*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:ap-northeast-2:*:secret:oma-source-*",
        "arn:aws:secretsmanager:ap-northeast-2:*:secret:oma-target-*"
      ]
    }
  ]
}
```

---

### 4.4 시스템 리소스

| 항목 | 최소 | 권장 | 대규모 (1000+ 매퍼) |
|------|------|------|---------------------|
| **CPU** | 2 cores | 4 cores | 8+ cores |
| **메모리** | 4 GB | 8 GB | 16+ GB |
| **디스크** | 10 GB | 20 GB | 50+ GB |
| **네트워크** | 1 Mbps | 10 Mbps | 100 Mbps |

**디스크 사용량 예측**:
- 소스 매퍼: ~10-50 MB
- 조각화: 소스의 2-3배
- 딕셔너리: 1-10 MB
- TC 파일: 1-10 MB
- 로그/리포트: 1-10 MB
- **여유 공간**: 최소 5 GB

---

## 5. 성능 최적화 추가 포인트

### 5.1 LLM API Rate Limit

```properties
# oma.properties 추가

# LLM API Rate Limit
LLM_RPM_LIMIT=50                    # 분당 요청 수
LLM_BATCH_SIZE=1                    # 배치 크기 (1=조각당 1 요청)
LLM_TIMEOUT_SECONDS=120             # 타임아웃
LLM_MAX_RETRIES=3                   # 최대 재시도
```

**배치 처리 고려**:
- 현재: 조각 1개 = API 호출 1개
- 배치: 조각 3-5개 = API 호출 1개
- 장점: 토큰 효율 향상, 컨텍스트 공유
- 단점: 실패 시 전체 재시도, 응답 파싱 복잡

→ **Phase 1에서는 배치 없이 1:1로 시작 권장**

---

### 5.2 메모리 최적화

```python
# 대용량 파일 스트리밍 처리
def process_large_mapper(mapper_file):
    """대용량 매퍼 스트리밍 처리"""
    
    # 한 번에 메모리 로드 X
    # 대신 SQL ID별로 순차 처리
    with open(mapper_file) as f:
        for sql_block in iter_sql_blocks(f):
            # SQL ID 단위로 처리
            process_sql_block(sql_block)
            # 메모리 해제
            del sql_block
```

```properties
# oma.properties 추가

# 메모리 최적화
LARGE_MAPPER_THRESHOLD_KB=5000      # 5MB 이상은 대용량
STREAM_PROCESSING=true              # 스트리밍 처리 활성화
```

---

### 5.3 디스크 I/O 최적화

```properties
# oma.properties 추가

# 임시 디렉토리 (옵션)
# 메모리 파일시스템 사용 시 성능 향상
# TEMP_DIR=/dev/shm/oma-temp

# 조각 파일 압축 (디스크 공간 절약)
COMPRESS_FRAGMENTS=false            # 기본 false (압축은 CPU 사용)
```

---

### 5.4 DB 커넥션 풀

```python
# Java ValidationService에 HikariCP 추가

# pom.xml
<dependency>
    <groupId>com.zaxxer</groupId>
    <artifactId>HikariCP</artifactId>
    <version>5.0.1</version>
</dependency>

# 커넥션 풀 설정
HikariConfig config = new HikariConfig();
config.setJdbcUrl(jdbcUrl);
config.setUsername(username);
config.setPassword(password);
config.setMaximumPoolSize(10);
config.setMinimumIdle(2);
config.setConnectionTimeout(10000);
config.setIdleTimeout(600000);

HikariDataSource dataSource = new HikariDataSource(config);
```

---

## 6. 전체 에러 리포트

### 위치
`${REPORT_DIR}/error-report.json`

### 구조

```json
{
  "run_id": "20260726_143022",
  "generated_at": "2026-07-26T15:12:45Z",
  
  "summary": {
    "total_errors": 25,
    "fatal": 0,
    "errors": 5,
    "warnings": 20
  },
  
  "errors_by_type": {
    "dblink": 3,
    "llm_timeout": 2,
    "unsupported_syntax": 5,
    "hint_detected": 15
  },
  
  "fatal_errors": [],
  
  "errors": [
    {
      "mapper": "RemoteDataMapper.xml",
      "sql_id": "getRemoteData",
      "error_type": "dblink",
      "severity": "error",
      "message": "DBLINK detected: remote_db",
      "line_number": 15,
      "sql_fragment": "SELECT * FROM remote_table@remote_db",
      "suggestion": "Use PostgreSQL FDW or replicate data locally",
      "action_required": "manual_refactoring"
    }
  ],
  
  "warnings": [
    {
      "mapper": "OrderMapper.xml",
      "sql_id": "getOrders",
      "error_type": "hint_detected",
      "severity": "warning",
      "message": "Oracle hint converted to comment",
      "hints": ["/*+ INDEX(o ord_idx) */"],
      "action_required": "verify_performance"
    }
  ]
}
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 에러 처리, 재시작, 예외 케이스 대응
