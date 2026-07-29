# OMA 코딩 가이드라인

## 목적

AI 코딩 시 코드 품질 유지, 중복 방지, 유지보수성 보장

---

## 🚨 필수 규칙: 작업 로그 시스템

### WORK_LOG.md 필수 사용

**모든 코딩 작업은 반드시 다음 순서로 진행**:

```
1. WORK_LOG.md 읽기 (전체)
2. 작업할 내용이 이미 구현되었는지 확인
3. 작업 시작 전 로그 작성
4. 코딩
5. 작업 완료 후 로그 작성
```

### WORK_LOG.md 형식

```markdown
# OMA 개발 작업 로그

## 규칙
- **작업 전**: 이 파일을 처음부터 끝까지 읽고 중복 작업 방지
- **작업 후**: 반드시 로그 작성
- **형식**: 최신 작업이 맨 위

---

## 2026-07-27 14:30 | LLM Client 구현

### 작업 내용
- `oma/converter/llm_client.py` 생성
- LLMClient 클래스 구현
- Rate limit 처리 (RPM 50)
- Exponential backoff 재시도

### 구현 내용
- `call_llm(prompt, retry_count)` - LLM API 호출
- `calculate_backoff(retry_count)` - 백오프 계산
- `_respect_rate_limit()` - Rate limit 준수

### 주의사항
- 절대 `call_llm_with_retry()` 같은 중복 메서드 만들지 말 것
- 이미 재시도 로직 포함되어 있음

### 파일 위치
- `oma/converter/llm_client.py` (150 lines)

### 테스트
- [ ] 단위 테스트 작성 필요

---

## 2026-07-27 13:15 | Dictionary Builder 구현

### 작업 내용
- `oma/dictionary/builder.py` 생성
- DictionaryBuilder 클래스 구현
- PostgreSQL 메타데이터 추출
- 샘플 데이터 수집

### 구현 내용
- `build()` - 딕셔너리 전체 생성
- `extract_metadata()` - information_schema 조회
- `collect_samples()` - 테이블별 샘플 1건
- `save_to_file()` - JSON 저장

### 주의사항
- 이미 `oma/dictionary/` 모듈 존재
- `oma/utils/` 에 중복 생성하지 말 것

### 파일 위치
- `oma/dictionary/builder.py` (220 lines)
- `oma/dictionary/__init__.py` (export)

### 테스트
- [x] 단위 테스트 완료
- [x] PostgreSQL 15 테스트 완료

---
```

### 위반 시 문제

```
❌ WORK_LOG.md를 읽지 않으면:
→ LLMClient를 또 만듦 (중복)
→ 다른 위치에 만듦 (분산)
→ 다른 이름으로 만듦 (일관성 X)
→ 유지보수 불가능
```

---

## 🚫 절대 금지 사항

### 1. 정규식 사용 금지 (XML/SQL 파싱)

**이유**: SQL/XML은 중첩 구조, 정규식으로 파싱 불가능

**금지**:
```python
# ❌ 절대 금지
sql_match = re.search(r'SELECT\s+(.+?)\s+FROM', sql)
where_clause = re.findall(r'WHERE\s+(.+)', sql)
columns = re.split(r',\s*', select_clause)
```

**허용**:
```python
# ✅ 허용: 단순 패턴 감지만
has_dblink = re.search(r'@[\w\.]+', sql)  # DBLINK 감지만
is_procedure = re.match(r'^(CALL|EXEC|EXECUTE)\s+', sql, re.IGNORECASE)

# ✅ 허용: 문자열 치환 (단순)
sql = sql.replace('SYSDATE', 'CURRENT_TIMESTAMP')
```

**대신 사용**:
- XML: `lxml.etree` (표준 XML 파서)
- SQL: MyBatis `BoundSql` (Java 측)
- 간단한 경우: `str.split()`, `str.find()`

---

### 2. sed 절대 금지

**이유**: 
- sed는 라인 기반, XML/SQL은 구조 기반
- 디버깅 불가능
- 플랫폼 의존적 (macOS vs Linux)

**금지**:
```bash
# ❌ 절대 금지
sed -i 's/SYSDATE/CURRENT_TIMESTAMP/g' *.xml
sed -n '/SELECT/,/FROM/p' mapper.xml
```

**대신 사용**:
```python
# ✅ Python으로 파일 처리
with open('mapper.xml', 'r') as f:
    content = f.read()
    content = content.replace('SYSDATE', 'CURRENT_TIMESTAMP')

with open('mapper.xml', 'w') as f:
    f.write(content)
```

---

### 3. eval / exec 금지

**이유**: 보안 위험, 디버깅 불가

**금지**:
```python
# ❌ 절대 금지
eval(user_input)
exec(code_string)
```

---

### 4. 전역 변수 금지

**이유**: 상태 추적 불가, 테스트 불가

**금지**:
```python
# ❌ 금지
llm_client = None  # 전역 변수

def init():
    global llm_client
    llm_client = LLMClient()

def convert(sql):
    return llm_client.call_llm(sql)  # 전역 변수 사용
```

**대신**:
```python
# ✅ 의존성 주입
class Converter:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
    
    def convert(self, sql: str) -> str:
        return self.llm_client.call_llm(sql)
```

---

### 5. 하드코딩 금지

**금지**:
```python
# ❌ 금지
def connect_db():
    conn = psycopg2.connect(
        host='10.0.1.5',  # 하드코딩
        port=5432,
        database='appdb'
    )
```

**대신**:
```python
# ✅ 설정 외부화
def connect_db(config: Config):
    conn = psycopg2.connect(
        host=config.get('TARGET_HOST'),
        port=config.get('TARGET_PORT'),
        database=config.get('TARGET_DATABASE')
    )
```

---

### 6. 마법 숫자/문자열 금지

**금지**:
```python
# ❌ 금지
if user.status == 'A':  # 'A'가 뭔지 모름
    return True

time.sleep(60)  # 60이 뭔지 모름
```

**대신**:
```python
# ✅ 상수 정의
class UserStatus:
    ACTIVE = 'A'
    INACTIVE = 'I'
    DELETED = 'D'

if user.status == UserStatus.ACTIVE:
    return True

RATE_LIMIT_WAIT_SECONDS = 60
time.sleep(RATE_LIMIT_WAIT_SECONDS)
```

---

## ✅ 필수 사항

### 1. 타입 힌트 필수 (Python)

```python
# ✅ 필수
def convert_sql(
    sql: str, 
    dictionary: Dict[str, Any],
    config: Config
) -> ConversionResult:
    pass

# ✅ 복잡한 타입도 명시
from typing import List, Dict, Optional, Union

def process_mappers(
    mapper_files: List[str],
    options: Optional[Dict[str, Any]] = None
) -> List[ConversionResult]:
    pass
```

---

### 2. 파일 상단 변경 이력 필수

**모든 파일 최상단에 작성**:

```python
"""
LLM API 클라이언트 모듈

Rate limit 준수 (RPM 50), exponential backoff 재시도 포함

변경 이력:
2026-07-27 10:30 | 홍길동 | 초기 생성
  - call_llm() 구현: LLM API 호출 및 재시도 로직
  - _respect_rate_limit() 구현: RPM 50 준수
  - calculate_backoff() 구현: 지수 백오프 계산

2026-07-28 14:20 | 김철수 | 버그 수정 #123
  - call_llm()에서 timeout 무한루프 수정
  - 원인: retry_count가 max_retries를 초과해도 계속 재시도 (line 45)
  - 수정: if retry_count >= self.max_retries 조건 추가
  - 영향: 타임아웃 발생 시 3회 후 정상 종료

2026-07-29 09:15 | 이영희 | 기능 추가
  - call_llm_batch() 구현 (line 120-145)
  - 목적: 여러 SQL을 한 번에 변환 (토큰 효율)
  - 제약: 배치 크기 최대 5개 (토큰 제한 100K)
  - 주의: 한 개라도 실패하면 전체 재시도
"""

import logging
from typing import Dict, Any, List
# ...
```

**Java도 동일**:

```java
/**
 * MyBatis SqlSessionFactory 기반 SQL 추출기
 * 
 * 변경 이력:
 * 2026-07-27 10:30 | 홍길동 | 초기 생성
 *   - extractSql() 구현
 *   - BoundSql로 동적 SQL 처리 (<if>, <choose> 등)
 * 
 * 2026-07-28 16:00 | 김철수 | 버그 수정 #456
 *   - extractSql()에서 NPE 수정
 *   - 원인: parameterObject가 null일 때 getProperty() 호출 (line 89)
 *   - 수정: null 체크 추가 및 빈 Map 반환
 *   - 영향: 파라미터 없는 SQL도 정상 처리
 * 
 * 2026-07-30 11:00 | 박민수 | 성능 개선
 *   - extractParameterValues()에서 리플렉션 제거
 *   - 원인: POJO 객체 접근 시 매번 리플렉션 사용 (느림)
 *   - 수정: Map 타입은 직접 get(), POJO는 PropertyAccessor 캐싱
 *   - 영향: 성능 50% 향상 (1000 TC 기준 20초 → 10초)
 */
public class SqlExtractor {
    // ...
}
```

**왜 중요한가**:
1. **버그 원인 빠르게 파악**: "line 45에서 retry_count 체크 누락" 보면 바로 이해
2. **같은 버그 재발 방지**: 이미 고친 버그 다시 안 만듦
3. **의도 파악**: "왜 이렇게 했지?" → 변경 이력 보면 바로 알 수 있음
4. **영향 범위 확인**: "이거 고치면 다른 데 영향 있나?" → 이력에 명시됨

### 3. Docstring 필수 (함수/메서드)

```python
def convert_sql(sql: str, dictionary: Dict[str, Any]) -> ConversionResult:
    """
    Oracle SQL을 PostgreSQL로 변환
    
    Args:
        sql: Oracle SQL 문자열
        dictionary: 스키마 딕셔너리 (table.column → 타입 정보)
    
    Returns:
        ConversionResult: 변환 결과 (converted_sql, type_casts, warnings)
    
    Raises:
        ConversionError: LLM API 실패 시
        ValidationError: SQL 구문 오류 시
    
    Examples:
        >>> result = convert_sql("SELECT * FROM users WHERE user_id = '123'", dict)
        >>> result.converted_sql
        "SELECT * FROM users WHERE user_id = 123::INTEGER"
    """
    pass
```

---

### 3. 에러 처리 필수

```python
# ✅ 구체적인 예외 처리
try:
    result = llm_client.call_llm(prompt)
except RateLimitError as e:
    logger.warning(f"Rate limit hit: {e}")
    time.sleep(60)
    result = llm_client.call_llm(prompt)
except TimeoutError as e:
    logger.error(f"LLM timeout: {e}")
    raise ConversionError(f"Failed to convert: timeout") from e
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise

# ❌ 금지: 너무 광범위
try:
    result = llm_client.call_llm(prompt)
except:  # 모든 예외 잡음
    pass  # 무시
```

---

### 4. 로깅 필수

```python
import logging

logger = logging.getLogger(__name__)

def convert_mapper(mapper_file: str) -> ConversionResult:
    logger.info(f"Converting mapper: {mapper_file}")
    
    try:
        result = do_conversion(mapper_file)
        logger.info(f"Conversion success: {mapper_file}")
        return result
    
    except ConversionError as e:
        logger.error(f"Conversion failed: {mapper_file} - {e}")
        raise
```

**로깅 레벨**:
- `DEBUG`: 상세 디버깅 정보
- `INFO`: 주요 작업 진행 상황
- `WARNING`: 경고 (계속 진행 가능)
- `ERROR`: 에러 (작업 실패)
- `CRITICAL`: 치명적 에러 (프로그램 중단)

---

### 5. 테스트 가능한 구조

**금지**:
```python
# ❌ 테스트 불가능
def process_all():
    config = load_config('config/oma.properties')  # 하드코딩
    client = LLMClient(config)  # 내부 생성
    db = connect_db(config)  # 내부 생성
    
    # ... 처리
```

**권장**:
```python
# ✅ 테스트 가능 (의존성 주입)
def process_all(
    config: Config,
    llm_client: LLMClient,
    db_connection: Connection
):
    # ... 처리

# 테스트 시
def test_process_all():
    mock_config = MockConfig()
    mock_client = MockLLMClient()
    mock_db = MockConnection()
    
    result = process_all(mock_config, mock_client, mock_db)
    assert result.success
```

---

## 📁 파일 구조 규칙

### 1. 모듈별 단일 책임

```
oma/
├─ dictionary/
│   ├─ __init__.py
│   ├─ builder.py          # 딕셔너리 생성만
│   └─ loader.py           # 딕셔너리 로드만
│
├─ converter/
│   ├─ __init__.py
│   ├─ llm_client.py       # LLM API 호출만
│   ├─ type_caster.py      # 타입 캐스팅만
│   └─ sql_analyzer.py     # SQL 분석만
│
├─ validation/
│   ├─ __init__.py
│   ├─ orchestrator.py     # 검증 오케스트레이션
│   ├─ java_bridge.py      # Java 통신만
│   └─ comparator.py       # 결과 비교만
```

**금지**:
```python
# ❌ 하나의 파일에 너무 많은 책임
# oma/utils/helpers.py (3000 lines)
class DatabaseHelper:
    pass

class LLMHelper:
    pass

class ValidationHelper:
    pass

class ConfigHelper:
    pass
# ... 20개 클래스
```

---

### 2. 파일 크기 제한

- **Python**: 최대 500 lines
- **Java**: 최대 500 lines
- 초과 시 분할

---

### 3. __init__.py 명확히

```python
# oma/converter/__init__.py

from .llm_client import LLMClient
from .type_caster import TypeCaster
from .sql_analyzer import SqlAnalyzer

__all__ = [
    'LLMClient',
    'TypeCaster',
    'SqlAnalyzer',
]
```

---

## 🏗️ 아키텍처 규칙

### 1. 계층 분리

```
[Main Script]
    ↓
[Orchestrator] (workflow 제어)
    ↓
[Service] (비즈니스 로직)
    ↓
[Repository] (데이터 접근)
    ↓
[Database/API]
```

**금지**: 계층 건너뛰기
```python
# ❌ Main에서 직접 DB 접근
def main():
    conn = psycopg2.connect(...)  # 금지
    cursor = conn.cursor()
```

**권장**:
```python
# ✅ Repository 패턴
class SchemaRepository:
    def __init__(self, connection: Connection):
        self.conn = connection
    
    def get_tables(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT table_name FROM information_schema.tables")
        return [row[0] for row in cursor.fetchall()]

# Main
def main():
    conn = create_connection(config)
    repo = SchemaRepository(conn)
    tables = repo.get_tables()
```

---

### 2. 의존성 주입

```python
# ✅ 생성자 주입
class Converter:
    def __init__(
        self, 
        llm_client: LLMClient,
        dictionary: Dict[str, Any],
        config: Config
    ):
        self.llm_client = llm_client
        self.dictionary = dictionary
        self.config = config
    
    def convert(self, sql: str) -> str:
        # self.llm_client 사용
        pass

# 사용
converter = Converter(
    llm_client=LLMClient(config),
    dictionary=load_dictionary(),
    config=config
)
```

---

## 🔤 네이밍 컨벤션

### Python

```python
# 클래스: PascalCase
class LLMClient:
    pass

class ConversionResult:
    pass

# 함수/메서드: snake_case
def convert_sql(sql: str) -> str:
    pass

def extract_columns(sql: str) -> List[str]:
    pass

# 변수: snake_case
user_id = 123
conversion_result = convert_sql(sql)

# 상수: UPPER_SNAKE_CASE
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 120

# Private: _prefix
class MyClass:
    def __init__(self):
        self._internal_state = {}  # private
    
    def _helper_method(self):  # private
        pass
```

### Java

```java
// 클래스: PascalCase
public class ValidationService {
}

// 메서드: camelCase
public ValidationResult validateTestCase(TestCase tc) {
}

// 변수: camelCase
String statementId = "UserMapper.getUser";
int affectedRows = 0;

// 상수: UPPER_SNAKE_CASE
public static final int MAX_POOL_SIZE = 10;
public static final String DEFAULT_SCHEMA = "public";

// private: 일반 camelCase
private Connection connection;
private SqlExtractor sqlExtractor;
```

---

## 📝 코드 리뷰 체크리스트

### 작성자 체크리스트 (코드 제출 전)

- [ ] WORK_LOG.md 읽었는가?
- [ ] WORK_LOG.md에 작업 기록했는가?
- [ ] 정규식으로 SQL/XML 파싱하지 않았는가?
- [ ] sed 사용하지 않았는가?
- [ ] 타입 힌트 작성했는가?
- [ ] Docstring 작성했는가?
- [ ] 에러 처리 추가했는가?
- [ ] 로깅 추가했는가?
- [ ] 하드코딩 제거했는가?
- [ ] 전역 변수 사용하지 않았는가?
- [ ] 테스트 가능한 구조인가?
- [ ] 파일 크기 500 lines 이하인가?
- [ ] 단일 책임 원칙 지켰는가?

### 리뷰어 체크리스트

- [ ] WORK_LOG.md에 작업 기록되어 있는가?
- [ ] 중복 코드 없는가?
- [ ] 네이밍이 명확한가?
- [ ] 에러 시나리오 처리되었는가?
- [ ] 테스트 코드 있는가?
- [ ] 문서화(Docstring) 되어 있는가?

---

## 🧪 테스트 규칙

### 1. 단위 테스트 필수

```python
# tests/test_llm_client.py

import pytest
from oma.converter.llm_client import LLMClient
from unittest.mock import Mock, patch

def test_call_llm_success():
    """LLM 호출 성공 케이스"""
    mock_bedrock = Mock()
    mock_bedrock.invoke_model.return_value = {"result": "converted"}
    
    client = LLMClient(config=mock_config, bedrock_client=mock_bedrock)
    result = client.call_llm("test prompt")
    
    assert result == {"result": "converted"}
    mock_bedrock.invoke_model.assert_called_once()


def test_call_llm_rate_limit_retry():
    """Rate limit 재시도 테스트"""
    mock_bedrock = Mock()
    mock_bedrock.invoke_model.side_effect = [
        RateLimitError("rate limit"),
        {"result": "converted"}
    ]
    
    client = LLMClient(config=mock_config, bedrock_client=mock_bedrock)
    result = client.call_llm("test prompt")
    
    assert result == {"result": "converted"}
    assert mock_bedrock.invoke_model.call_count == 2
```

---

### 2. 통합 테스트

```python
# tests/integration/test_conversion_flow.py

def test_full_conversion_flow():
    """전체 변환 플로우 통합 테스트"""
    
    # 1. 딕셔너리 생성
    builder = DictionaryBuilder(config)
    dictionary = builder.build()
    
    # 2. 매퍼 분할
    splitter = MapperSplitter(config)
    fragments = splitter.split("UserMapper.xml")
    
    # 3. 변환
    converter = Converter(llm_client, dictionary, config)
    results = [converter.convert(f) for f in fragments]
    
    # 4. 검증
    assert len(results) == len(fragments)
    assert all(r.success for r in results)
```

---

### 3. 테스트 커버리지 목표

- **단위 테스트**: 80% 이상
- **통합 테스트**: 주요 플로우 100%

---

## 🚀 성능 규칙

### 1. 데이터베이스

```python
# ✅ 커넥션 풀 사용
from psycopg2.pool import ThreadedConnectionPool

pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    host=config.get('TARGET_HOST'),
    database=config.get('TARGET_DATABASE')
)

# ❌ 매번 새 커넥션
def query():
    conn = psycopg2.connect(...)  # 매번 생성 - 느림
    # ...
    conn.close()
```

---

### 2. 파일 I/O

```python
# ✅ 한 번에 읽기
with open('large_file.xml', 'r') as f:
    content = f.read()  # 한 번에
    # 처리

# ❌ 여러 번 열기
for i in range(100):
    with open('same_file.xml', 'r') as f:  # 100번 열기 - 느림
        line = f.readline()
```

---

### 3. 메모리

```python
# ✅ Generator 사용 (대용량 데이터)
def process_large_file(file_path: str):
    with open(file_path, 'r') as f:
        for line in f:  # 한 줄씩
            yield process_line(line)

# ❌ 전체 메모리 로드
def process_large_file(file_path: str):
    with open(file_path, 'r') as f:
        lines = f.readlines()  # 전체 로드 - 메모리 초과
    return [process_line(l) for l in lines]
```

---

## 📚 문서화 규칙

### 1. README.md (각 모듈)

```markdown
# oma.converter

Oracle SQL을 PostgreSQL로 변환하는 모듈

## 구성 요소

- `LLMClient`: LLM API 호출
- `TypeCaster`: 타입 캐스팅 적용
- `SqlAnalyzer`: SQL 분석

## 사용 예시

```python
from oma.converter import LLMClient, TypeCaster

client = LLMClient(config)
caster = TypeCaster(dictionary)

result = client.call_llm(prompt)
final_sql = caster.apply(result)
```

## 주의사항

- LLMClient는 Rate Limit 준수
- TypeCaster는 딕셔너리 필수
```

---

### 2. CHANGELOG.md

```markdown
# Changelog

## [1.0.0] - 2026-07-27

### Added
- LLM Client with rate limit handling
- Type casting module
- Dictionary builder

### Fixed
- Memory leak in large file processing

### Changed
- Improved error messages
```

---

## 🛡️ 보안 규칙

### 1. 자격증명 절대 하드코딩 금지

```python
# ❌ 절대 금지
password = "mypassword123"
api_key = "sk-1234567890abcdef"

# ✅ Secrets Manager
from oma.utils.secrets import get_secret

credentials = get_secret(
    secret_name='oma-target-service',
    region='ap-northeast-2'
)
```

---

### 2. SQL 인젝션 방지

```python
# ❌ 금지: 문자열 포맷
cursor.execute(f"SELECT * FROM users WHERE user_id = {user_id}")

# ✅ 파라미터 바인딩
cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
```

---

### 3. 로그에 민감 정보 제외

```python
# ❌ 금지
logger.info(f"Connecting with password: {password}")

# ✅ 마스킹
logger.info(f"Connecting with password: {'*' * len(password)}")
```

---

## 🔧 개발 도구

### 추천 도구

**Python**:
- `black` - 코드 포맷터
- `pylint` - 린터
- `mypy` - 타입 체커
- `pytest` - 테스트 프레임워크
- `coverage` - 커버리지 측정

**Java**:
- `google-java-format` - 코드 포맷터
- `checkstyle` - 코드 스타일 체커
- `spotbugs` - 버그 탐지
- `JUnit 5` - 테스트 프레임워크
- `JaCoCo` - 커버리지 측정

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-27
- 목적: AI 코딩 가이드라인 및 코드 품질 유지
