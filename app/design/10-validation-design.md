# 검증 프로그램 설계 (Validation Design)

## 핵심 결정사항

### ✅ SqlSessionFactory 기반 검증

**이유**:
1. **정확성이 최우선**: MyBatis가 직접 처리하므로 100% 정확
2. **동적 SQL 완벽 처리**: `<if>`, `<choose>`, `<foreach>` 자동 평가
3. **<include> 자동 해결**: refid 참조 완벽 처리
4. **바인드 변수 완벽**: ParameterMapping 그대로 사용
5. **실전 검증**: XML 파서/정규식은 품질 낮음 → 포기

**핵심 코드**:
```java
// 이 한 줄로 모든 동적 SQL 처리!
BoundSql boundSql = mappedStatement.getBoundSql(parameters);
String sql = boundSql.getSql();  // <if>, <choose>, <include> 모두 해결됨
```

### ❌ XML 파서/정규식 방식 포기

**문제점**:
- `<if test="userId != null">` 조건 평가를 직접 구현? → 거의 불가능
- `<include>` 중첩 처리? → 유지보수 지옥
- 정규식으로 SQL 파싱? → 버그 투성이

**결론**: 텍스트 파싱으로는 절대 MyBatis 수준에 못 미침

---

## 아키텍처: Python + Java 하이브리드

```
┌─────────────────────────────────────┐
│  Python Orchestrator                │
│  - TC 로드                          │
│  - 결과 비교                        │
│  - 리포팅                           │
│  - 통계 분석                        │
└─────────────────────────────────────┘
           ↓ JSON
┌─────────────────────────────────────┐
│  Java Validation Service            │
│  - SqlSessionFactory 초기화         │
│  - Mapper 로드                      │
│  - SQL 추출 (getBoundSql)           │
│  - DB 실행 (PreparedStatement)      │
└─────────────────────────────────────┘
         ↓           ↓
    [Oracle]    [PostgreSQL]
```

### 디렉토리 구조

```
oma/
├─ oma/                           # Python 패키지
│   ├─ validation/
│   │   ├─ java_bridge.py         # Java 브릿지
│   │   ├─ orchestrator.py        # 오케스트레이터
│   │   └─ comparator.py          # 결과 비교
│
├─ java-validator/                # Java 모듈
│   ├─ pom.xml
│   └─ src/main/java/com/oma/validator/
│       ├─ ValidationService.java
│       ├─ SqlExtractor.java      # MyBatis 활용
│       ├─ DatabaseExecutor.java
│       └─ model/
│           ├─ TestCase.java
│           ├─ ValidationResult.java
│           └─ ExecutionResult.java
│
└─ scripts/
    ├─ build_java_validator.sh    # Java 빌드
    └─ run_validation.py          # Python 실행
```

---

## Java 검증 서비스

### Maven 설정

```xml
<!-- java-validator/pom.xml -->
<project>
    <groupId>com.oma</groupId>
    <artifactId>oma-validator</artifactId>
    <version>1.0.0</version>
    
    <dependencies>
        <!-- MyBatis -->
        <dependency>
            <groupId>org.mybatis</groupId>
            <artifactId>mybatis</artifactId>
            <version>3.5.13</version>
        </dependency>
        
        <!-- DB Drivers -->
        <dependency>
            <groupId>com.oracle.database.jdbc</groupId>
            <artifactId>ojdbc11</artifactId>
            <version>21.9.0.0</version>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.6.0</version>
        </dependency>
        <dependency>
            <groupId>mysql</groupId>
            <artifactId>mysql-connector-java</artifactId>
            <version>8.0.33</version>
        </dependency>
        
        <!-- JSON -->
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
        </dependency>
    </dependencies>
</project>
```

---

### SQL 추출기 (핵심!)

```java
// SqlExtractor.java
package com.oma.validator;

import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;

public class SqlExtractor {
    
    private final SqlSessionFactory sqlSessionFactory;
    
    public SqlExtractor(SqlSessionFactory sqlSessionFactory) {
        this.sqlSessionFactory = sqlSessionFactory;
    }
    
    /**
     * TC 파라미터를 적용하여 실제 실행될 SQL 추출
     * 
     * MyBatis가 동적 SQL을 완벽하게 처리!
     */
    public ExtractedSql extractSql(
        String statementId, 
        Map<String, Object> parameters
    ) {
        try (SqlSession session = sqlSessionFactory.openSession()) {
            Configuration configuration = session.getConfiguration();
            
            // MappedStatement 조회
            MappedStatement ms = configuration.getMappedStatement(statementId);
            
            // ⭐ 여기서 마법이 일어남! ⭐
            // BoundSql 생성 - 동적 SQL 모두 평가됨!
            // <if>, <choose>, <foreach>, <include> 모두 처리됨
            BoundSql boundSql = ms.getBoundSql(parameters);
            
            // 최종 SQL
            String sql = boundSql.getSql();
            
            // 파라미터 매핑 정보
            List<ParameterMapping> parameterMappings = 
                boundSql.getParameterMappings();
            
            // 실제 파라미터 값
            Object parameterObject = boundSql.getParameterObject();
            
            return new ExtractedSql(
                statementId,
                sql,
                parameterMappings,
                parameterObject,
                extractParameterValues(boundSql, parameterMappings, parameterObject)
            );
            
        } catch (Exception e) {
            throw new SqlExtractionException(
                "Failed to extract SQL for: " + statementId, 
                e
            );
        }
    }
    
    private List<Object> extractParameterValues(
        BoundSql boundSql,
        List<ParameterMapping> mappings,
        Object parameterObject
    ) {
        List<Object> values = new ArrayList<>();
        
        for (ParameterMapping mapping : mappings) {
            String property = mapping.getProperty();
            Object value;
            
            if (parameterObject == null) {
                value = null;
            } else if (parameterObject instanceof Map) {
                value = ((Map<?, ?>) parameterObject).get(property);
            } else {
                // POJO 객체
                value = getPropertyValue(parameterObject, property);
            }
            
            values.add(value);
        }
        
        return values;
    }
}
```

**핵심 포인트**:
- `BoundSql boundSql = ms.getBoundSql(parameters);`
- 이 한 줄로 모든 동적 SQL 처리 완료!
- XML 파서로 직접 구현? 절대 불가능!

---

### DB 실행기

```java
// DatabaseExecutor.java
package com.oma.validator;

public class DatabaseExecutor {
    
    private final Connection connection;
    
    public DatabaseExecutor(Connection connection) {
        this.connection = connection;
    }
    
    /**
     * PreparedStatement로 SQL 실행
     * 
     * DML은 자동으로 트랜잭션 처리 후 롤백
     * 프로시저는 실행하지 않고 스킵 리포팅
     */
    public ExecutionResult execute(ExtractedSql extractedSql) {
        long startTime = System.currentTimeMillis();
        
        // 프로시저 호출 감지
        if (isProcedureCall(extractedSql.getSql())) {
            return ExecutionResult.skipped(
                "Procedure call skipped - would modify data",
                0,
                extractedSql.getSql(),
                "procedure_call"
            );
        }
        
        // SQL 타입 판별
        SqlType sqlType = detectSqlType(extractedSql.getSql());
        
        try {
            // DML은 트랜잭션 시작
            boolean needsRollback = sqlType.isDML();
            if (needsRollback) {
                connection.setAutoCommit(false);
            }
            
            try (PreparedStatement ps = connection.prepareStatement(
                extractedSql.getSql()
            )) {
                
                // 파라미터 바인딩
                bindParameters(ps, extractedSql);
                
                // 실행
                boolean hasResultSet = ps.execute();
                long executionTime = System.currentTimeMillis() - startTime;
                
                ExecutionResult result;
                
                if (hasResultSet) {
                    // SELECT
                    ResultSet rs = ps.getResultSet();
                    List<Map<String, Object>> rows = extractRows(rs);
                    
                    result = ExecutionResult.success(
                        rows,
                        rows.size(),
                        executionTime,
                        extractedSql.getSql()
                    );
                } else {
                    // INSERT/UPDATE/DELETE
                    int affectedRows = ps.getUpdateCount();
                    
                    result = ExecutionResult.success(
                        Collections.emptyList(),
                        affectedRows,
                        executionTime,
                        extractedSql.getSql()
                    );
                }
                
                // DML은 무조건 롤백
                if (needsRollback) {
                    connection.rollback();
                    result.setRolledBack(true);
                }
                
                return result;
                
            } finally {
                // AutoCommit 복원
                if (needsRollback) {
                    connection.setAutoCommit(true);
                }
            }
            
        } catch (SQLException e) {
            // 에러 발생 시에도 롤백 시도
            try {
                if (!connection.getAutoCommit()) {
                    connection.rollback();
                    connection.setAutoCommit(true);
                }
            } catch (SQLException rollbackEx) {
                // 롤백 실패는 로깅만
            }
            
            return ExecutionResult.failure(
                e.getMessage(),
                System.currentTimeMillis() - startTime,
                extractedSql.getSql()
            );
        }
    }
    
    /**
     * 프로시저 호출 여부 판별
     */
    private boolean isProcedureCall(String sql) {
        String normalized = sql.trim().toUpperCase();
        
        // CALL, EXECUTE, EXEC, BEGIN...END 패턴
        return normalized.startsWith("CALL ") ||
               normalized.startsWith("EXECUTE ") ||
               normalized.startsWith("EXEC ") ||
               normalized.startsWith("{CALL ") ||
               (normalized.startsWith("BEGIN") && normalized.contains("END"));
    }
    
    /**
     * SQL 타입 감지
     */
    private SqlType detectSqlType(String sql) {
        String normalized = sql.trim().toUpperCase();
        
        if (normalized.startsWith("SELECT") || 
            normalized.startsWith("WITH")) {
            return SqlType.SELECT;
        } else if (normalized.startsWith("INSERT")) {
            return SqlType.INSERT;
        } else if (normalized.startsWith("UPDATE")) {
            return SqlType.UPDATE;
        } else if (normalized.startsWith("DELETE")) {
            return SqlType.DELETE;
        } else if (normalized.startsWith("MERGE")) {
            return SqlType.MERGE;
        } else {
            return SqlType.UNKNOWN;
        }
    }
    
    enum SqlType {
        SELECT(false),
        INSERT(true),
        UPDATE(true),
        DELETE(true),
        MERGE(true),
        UNKNOWN(false);
        
        private final boolean isDML;
        
        SqlType(boolean isDML) {
            this.isDML = isDML;
        }
        
        public boolean isDML() {
            return isDML;
        }
    }
    
    private void bindParameters(
        PreparedStatement ps, 
        ExtractedSql extractedSql
    ) throws SQLException {
        List<Object> values = extractedSql.getParameterValues();
        
        for (int i = 0; i < values.size(); i++) {
            Object value = values.get(i);
            ps.setObject(i + 1, value);
        }
    }
    
    private List<Map<String, Object>> extractRows(ResultSet rs) 
        throws SQLException {
        
        List<Map<String, Object>> rows = new ArrayList<>();
        ResultSetMetaData metaData = rs.getMetaData();
        int columnCount = metaData.getColumnCount();
        
        while (rs.next()) {
            Map<String, Object> row = new LinkedHashMap<>();
            
            for (int i = 1; i <= columnCount; i++) {
                String columnName = metaData.getColumnLabel(i);
                Object value = rs.getObject(i);
                row.put(columnName, value);
            }
            
            rows.add(row);
        }
        
        return rows;
    }
}
```

---

### 검증 서비스 (메인)

```java
// ValidationService.java
package com.oma.validator;

public class ValidationService {
    
    private final SqlExtractor sqlExtractor;
    private final Map<String, DatabaseExecutor> executors;
    
    public ValidationService(
        SqlSessionFactory sqlSessionFactory,
        Map<String, Connection> connections
    ) {
        this.sqlExtractor = new SqlExtractor(sqlSessionFactory);
        this.executors = new HashMap<>();
        
        connections.forEach((name, conn) -> 
            executors.put(name, new DatabaseExecutor(conn))
        );
    }
    
    /**
     * 단일 TC 검증
     */
    public ValidationResult validateTestCase(TestCase tc) {
        try {
            // 1. SQL 추출 (동적 SQL 평가)
            String statementId = tc.getMapper() + "." + tc.getSqlId();
            ExtractedSql sql = sqlExtractor.extractSql(
                statementId,
                tc.getParameters()
            );
            
            // 2. 소스 DB 실행
            ExecutionResult sourceResult = executors.get("source").execute(sql);
            
            // 3. 타겟 DB 실행
            ExecutionResult targetResult = executors.get("target").execute(sql);
            
            // 4. 결과 반환 (비교는 Python에서)
            return new ValidationResult(
                tc.getTestCaseId(),
                sourceResult,
                targetResult
            );
            
        } catch (Exception e) {
            return ValidationResult.error(tc.getTestCaseId(), e);
        }
    }
    
    /**
     * JSON 입력/출력 (Python 통신)
     */
    public static void main(String[] args) {
        Gson gson = new Gson();
        
        // STDIN으로 JSON 입력 받음
        try (Scanner scanner = new Scanner(System.in)) {
            String input = scanner.nextLine();
            TestCase tc = gson.fromJson(input, TestCase.class);
            
            // 검증 실행
            ValidationService service = initializeService();
            ValidationResult result = service.validateTestCase(tc);
            
            // STDOUT으로 JSON 출력
            System.out.println(gson.toJson(result));
            
        } catch (Exception e) {
            System.err.println(gson.toJson(Map.of("error", e.getMessage())));
            System.exit(1);
        }
    }
    
    private static ValidationService initializeService() {
        // MyBatis 설정 로드
        SqlSessionFactory factory = buildSqlSessionFactory();
        
        // DB 연결
        Map<String, Connection> connections = new HashMap<>();
        connections.put("source", createSourceConnection());
        connections.put("target", createTargetConnection());
        
        return new ValidationService(factory, connections);
    }
}
```

---

## Python 브릿지

### Java 프로세스 관리

```python
# oma/validation/java_bridge.py
import subprocess
import json
from typing import Dict, Any, List

class JavaValidationBridge:
    """Java 검증 서비스 브릿지"""
    
    def __init__(self, jar_path, config):
        self.jar_path = jar_path
        self.config = config
    
    def validate_test_case(self, tc: Dict[str, Any]) -> Dict[str, Any]:
        """TC 검증 요청"""
        
        # JSON 입력
        input_json = json.dumps(tc)
        
        # Java 프로세스 호출
        result = subprocess.run(
            ['java', '-jar', self.jar_path],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=300  # 5분 타임아웃
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Java validation failed: {result.stderr}")
        
        # JSON 출력 파싱
        return json.loads(result.stdout)
    
    def validate_batch(self, tc_list: List[Dict]) -> List[Dict]:
        """배치 검증 (병렬)"""
        from concurrent.futures import ThreadPoolExecutor
        
        with ThreadPoolExecutor(
            max_workers=self.config['max_workers']
        ) as executor:
            results = list(executor.map(self.validate_test_case, tc_list))
        
        return results
```

---

### Python 오케스트레이터

```python
# oma/validation/orchestrator.py
from .java_bridge import JavaValidationBridge
from .comparator import ResultComparator

class ValidationOrchestrator:
    """검증 오케스트레이터 (Python)"""
    
    def __init__(self, config):
        self.config = config
        
        # Java 브릿지 초기화
        self.java_bridge = JavaValidationBridge(
            jar_path='java-validator/target/oma-validator-1.0.0.jar',
            config=config
        )
        
        # 결과 비교기
        self.comparator = ResultComparator()
    
    def validate_all(self, work_dir):
        """전체 검증"""
        
        # 1. TC 파일 수집
        tc_files = self.collect_tc_files(work_dir)
        tc_list = [self.load_tc(f) for f in tc_files]
        
        # 2. Java로 검증 실행 (병렬)
        print(f"Validating {len(tc_list)} test cases...")
        java_results = self.java_bridge.validate_batch(tc_list)
        
        # 3. 결과 비교 (Python)
        print("Comparing results...")
        comparisons = []
        for result in java_results:
            comparison = self.comparator.compare(
                result['sourceResult'],
                result['targetResult']
            )
            comparisons.append({
                'tc_id': result['tcId'],
                'comparison': comparison
            })
        
        # 4. 리포트 생성
        self.generate_report(comparisons, work_dir)
        
        return comparisons
```

---

## ${} 동적 변수 처리

### 문제
```xml
<select id="dynamicQuery">
  SELECT * FROM ${tableName}
  WHERE status = #{status}
</select>
```

`${tableName}`은 런타임에만 결정됨.

### 해결: TC에 포함

```json
{
  "test_case_id": "DynamicMapper_dynamicQuery_tc001",
  "parameters": {
    "tableName": "users",
    "status": "A"
  },
  "dollar_variables": {
    "tableName": "users"
  }
}
```

**Java 처리**:
```java
// ${} 변수는 MyBatis가 자동 처리
// parameters에 포함되어 있으면 자동으로 치환됨
BoundSql boundSql = ms.getBoundSql(parameters);
String sql = boundSql.getSql();  // ${tableName} → users로 이미 치환됨
```

**대부분 ${} 변수는**:
- 테이블명 (고정)
- 컬럼명 (고정)
- ORDER BY 컬럼 (예측 가능)
- → TC 생성 시 LLM이 추론 가능

---

## 결과 비교 (Python)

```python
# oma/validation/comparator.py

def compare_results(
    source_result: Dict,
    target_result: Dict,
    tolerance: float = 0.001
) -> Dict:
    """소스와 타겟 결과 비교"""
    
    differences = []
    
    # 1. 행 수 비교
    row_count_matched = (
        source_result['row_count'] == target_result['row_count']
    )
    
    if not row_count_matched:
        differences.append({
            'type': 'row_count_mismatch',
            'source': source_result['row_count'],
            'target': target_result['row_count']
        })
    
    # 2. 컬럼 비교 (대소문자 무시)
    source_cols = set(col.lower() for col in source_result['columns'])
    target_cols = set(col.lower() for col in target_result['columns'])
    
    if source_cols != target_cols:
        differences.append({
            'type': 'column_mismatch',
            'missing': list(source_cols - target_cols),
            'extra': list(target_cols - source_cols)
        })
    
    # 3. 값 비교 (행별)
    value_differences = []
    min_rows = min(len(source_result['rows']), len(target_result['rows']))
    
    for idx in range(min_rows):
        row_diff = compare_row(
            source_result['rows'][idx],
            target_result['rows'][idx],
            tolerance
        )
        if row_diff:
            value_differences.append({
                'row_index': idx,
                'differences': row_diff
            })
    
    # 4. 성능 차이
    time_diff = target_result['execution_time_ms'] - source_result['execution_time_ms']
    time_diff_percent = (
        (time_diff / source_result['execution_time_ms']) * 100
        if source_result['execution_time_ms'] > 0
        else 0
    )
    
    # 5. 종합 판정
    matched = (
        row_count_matched and
        not differences and
        not value_differences
    )
    
    return {
        'matched': matched,
        'differences': differences,
        'value_differences': value_differences,
        'source_time_ms': source_result['execution_time_ms'],
        'target_time_ms': target_result['execution_time_ms'],
        'time_difference_ms': time_diff,
        'time_difference_percent': time_diff_percent
    }
```

---

## 빌드 및 실행

### Java 빌드

```bash
#!/bin/bash
# scripts/build_java_validator.sh

cd java-validator
mvn clean package

echo "✓ Java validator built: target/oma-validator-1.0.0.jar"
```

### Python 실행

```python
# scripts/run_validation.py
from oma.validation.orchestrator import ValidationOrchestrator
from oma.utils.config import Config

def main():
    # 설정
    config = Config('config/oma.properties', 'ap-northeast-2')
    
    # Java JAR 존재 확인
    jar_path = 'java-validator/target/oma-validator-1.0.0.jar'
    if not os.path.exists(jar_path):
        print("Error: Java validator not built")
        print("Run: scripts/build_java_validator.sh")
        sys.exit(1)
    
    # 검증 실행
    orchestrator = ValidationOrchestrator(config)
    results = orchestrator.validate_all(config.get('MAPPER_WORK_DIR'))
    
    # 결과 출력
    passed = sum(1 for r in results if r['comparison']['matched'])
    total = len(results)
    
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print(f"{'='*50}\n")
```

---

## 성능 최적화

### Java 프로세스 재사용

```python
class JavaProcessPool:
    """Java 프로세스 풀 - 재사용으로 성능 향상"""
    
    def __init__(self, jar_path, pool_size=5):
        self.processes = []
        
        # 프로세스 풀 생성 (장시간 실행)
        for _ in range(pool_size):
            proc = subprocess.Popen(
                ['java', '-jar', jar_path, '--server-mode'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True
            )
            self.processes.append(proc)
    
    def execute(self, tc):
        """사용 가능한 프로세스로 실행"""
        proc = self.get_available_process()
        
        # JSON 입력
        proc.stdin.write(json.dumps(tc) + '\n')
        proc.stdin.flush()
        
        # JSON 출력
        result_line = proc.stdout.readline()
        return json.loads(result_line)
```

### 배치 실행

```java
// Java: 한 번에 여러 TC 처리
public List<ValidationResult> validateBatch(List<TestCase> testCases) {
    return testCases.parallelStream()
        .map(this::validateTestCase)
        .collect(Collectors.toList());
}
```

---

## 장단점 요약

### SqlSessionFactory 방식 (선택)

| 항목 | 평가 |
|------|------|
| **정확성** | ★★★★★ (MyBatis 직접 사용) |
| **구현 복잡도** | ★★★☆☆ (Java + Python 연동) |
| **유지보수성** | ★★★★☆ (Java는 안정적) |
| **확장성** | ★★★★☆ (DB별 커넥션만 추가) |
| **성능** | ★★★☆☆ (프로세스 간 통신) |

### XML 파서 방식 (포기)

| 항목 | 평가 |
|------|------|
| **정확성** | ★★☆☆☆ (직접 구현 → 버그) |
| **구현 복잡도** | ★★★★★ (동적 SQL 지옥) |
| **유지보수성** | ★☆☆☆☆ (깨지기 쉬움) |
| **확장성** | ★★★★★ (Python만) |
| **성능** | ★★★★★ (프로세스 통신 없음) |

**결론**: 정확성 >> 성능

---

## DML 트랜잭션 처리 및 프로시저 스킵

### 안전한 검증을 위한 원칙

1. **DML은 롤백 필수**
   - INSERT/UPDATE/DELETE/MERGE는 자동으로 트랜잭션 처리
   - `connection.setAutoCommit(false)` → 실행 → `connection.rollback()`
   - 실제 데이터 변경 없이 실행 가능 여부만 검증

2. **프로시저는 실행 금지**
   - CALL, EXECUTE, EXEC, BEGIN...END 패턴 감지
   - 실행하지 않고 "skipped" 상태로 리포팅
   - 프로시저는 내부에서 COMMIT을 호출할 수 있어 위험

### ExecutionResult 모델

```java
public class ExecutionResult {
    private boolean success;
    private List<Map<String, Object>> rows;
    private int affectedRows;
    private long executionTimeMs;
    private String sql;
    private String errorMessage;
    
    // 추가 필드
    private boolean rolledBack;     // DML 롤백 여부
    private boolean skipped;        // 프로시저 스킵 여부
    private String skipReason;      // 스킵 이유
    
    public static ExecutionResult skipped(
        String reason, 
        long executionTime,
        String sql,
        String skipType
    ) {
        ExecutionResult result = new ExecutionResult();
        result.skipped = true;
        result.skipReason = reason;
        result.executionTimeMs = executionTime;
        result.sql = sql;
        result.success = false;
        return result;
    }
}
```

### 리포트 예시

```json
{
  "validation_summary": {
    "total_test_cases": 1247,
    "passed": 1189,
    "failed": 58,
    "skipped": 15,
    "success_rate": 95.3,
    
    "skipped_breakdown": {
      "procedure_call": 15
    },
    
    "dml_statistics": {
      "total_dml": 127,
      "insert": 45,
      "update": 62,
      "delete": 20,
      "all_rolled_back": true
    },
    
    "failure_types": {
      "row_count_mismatch": 12,
      "column_mismatch": 5,
      "value_mismatch": 41
    },
    
    "performance_summary": {
      "avg_source_time_ms": 45.2,
      "avg_target_time_ms": 38.7,
      "avg_improvement_percent": 14.4
    }
  },
  
  "skipped_test_cases": [
    {
      "tc_id": "UserMapper_createUserProc_tc001",
      "mapper": "UserMapper",
      "sql_id": "createUserProc",
      "skip_reason": "Procedure call skipped - would modify data",
      "sql": "CALL create_user_proc(?, ?, ?)"
    }
  ],
  
  "slow_queries_top10": [
    {
      "tc_id": "OrderMapper_complexQuery_tc001",
      "source_time_ms": 1250,
      "target_time_ms": 2840,
      "time_increase_ms": 1590,
      "time_increase_percent": 127.2
    }
  ]
}
```

### 콘솔 출력 예시

```
========================================
Validation Completed
========================================

Summary:
  Total Test Cases: 1,247
  ✓ Passed: 1,189 (95.3%)
  ✗ Failed: 58 (4.7%)
  ⊘ Skipped: 15 (1.2%)

Skipped:
  ⊘ Procedure Calls: 15 (cannot validate safely)

DML Statistics:
  🔄 Total DML: 127
     • INSERT: 45
     • UPDATE: 62
     • DELETE: 20
  ✓ All Rolled Back: Yes

Failures:
  Row Count Mismatch: 12
  Column Mismatch: 5
  Value Mismatch: 41

⚠️  WARNING: 15 procedure calls were skipped
   Review these manually: reports/validation-summary.json

Reports Generated:
  • reports/validation-summary.json
  • reports/validation-details.json
  • reports/validation-failures.csv
  • reports/validation-report.html
========================================
```

---

## 문서 버전
- 버전: 2.0
- 작성일: 2026-07-26
- 수정일: 2026-07-26
- 목적: SqlSessionFactory 기반 검증 설계
