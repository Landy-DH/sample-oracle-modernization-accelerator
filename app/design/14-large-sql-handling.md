# 대용량 SQL 및 결과셋 처리

## 목적

매우 큰 SQL 문 변환 시 LLM 토큰 제한과 검증 시 대용량 결과셋 메모리 문제 해결

---

## 1. 문제 정의

### 1.1 대용량 SQL 변환 문제

**시나리오**:
```xml
<select id="massiveQuery">
  SELECT 
    u.user_id,
    u.username,
    u.email,
    ... (100+ columns)
  FROM users u
  LEFT JOIN orders o ON u.user_id = o.user_id
  LEFT JOIN products p ON o.product_id = p.product_id
  ... (20+ joins)
  WHERE 1=1
  <if test="userId != null">
    AND u.user_id = #{userId}
  </if>
  ... (50+ dynamic conditions)
  ORDER BY u.created_date DESC
</select>
```

**문제점**:
- SQL이 50,000+ 자 (약 15K 토큰)
- LLM 입력 토큰 제한 (예: 100K)
- 프롬프트 + 딕셔너리 + SQL = 토큰 초과 가능
- 네트워크 전송 시 끊김 가능

---

### 1.2 대용량 결과셋 검증 문제

**시나리오**:
```sql
SELECT * FROM orders WHERE created_date > '2020-01-01'
-- 결과: 500,000 rows
```

**문제점**:
- Java에서 50만 행을 메모리에 로드 → OutOfMemoryError
- Python으로 전송 → JSON 수십~수백 MB
- 비교 시간 매우 오래 걸림

---

## 2. 대용량 SQL 처리 전략

### 2.1 감지 및 분류

```python
# oma/converter/sql_analyzer.py

class SqlAnalyzer:
    """SQL 크기 및 복잡도 분석"""
    
    def __init__(self, config):
        self.config = config
        self.large_threshold = config.get('LLM_LARGE_SQL_THRESHOLD', 50000)
    
    def analyze(self, sql_content):
        """SQL 분석"""
        
        char_count = len(sql_content)
        token_estimate = char_count // 3  # 대략 3 char = 1 token
        
        # 복잡도 측정
        join_count = sql_content.upper().count('JOIN')
        if_count = sql_content.count('<if')
        choose_count = sql_content.count('<choose')
        
        complexity = join_count + if_count * 2 + choose_count * 3
        
        return {
            'char_count': char_count,
            'token_estimate': token_estimate,
            'is_large': char_count > self.large_threshold,
            'complexity': complexity,
            'complexity_level': self.classify_complexity(complexity)
        }
    
    def classify_complexity(self, score):
        if score < 10:
            return 'simple'
        elif score < 30:
            return 'moderate'
        elif score < 100:
            return 'complex'
        else:
            return 'very_complex'
```

---

### 2.2 전략 선택

```python
def select_conversion_strategy(analysis):
    """SQL 크기/복잡도에 따른 전략 선택"""
    
    if not analysis['is_large']:
        # 일반 SQL - 기본 전략
        return 'standard'
    
    elif analysis['complexity_level'] in ['simple', 'moderate']:
        # 크지만 단순 - 그냥 처리
        return 'standard_with_compression'
    
    elif analysis['complexity_level'] == 'complex':
        # 크고 복잡 - 청킹
        return 'chunked'
    
    else:
        # 매우 크고 복잡 - 수동 검토
        return 'manual_review'
```

---

### 2.3 전략 A: 표준 (압축)

**적용**: 큰 SQL이지만 구조가 단순

```python
def standard_with_compression(sql_content, dictionary):
    """프롬프트 압축"""
    
    # 1. 딕셔너리 최소화
    # 전체 딕셔너리 대신 SQL에서 실제 사용된 컬럼만 추출
    used_columns = extract_columns_from_sql(sql_content)
    mini_dict = {k: v for k, v in dictionary.items() if k in used_columns}
    
    # 2. 프롬프트 단축
    short_prompt = """
Convert this Oracle SQL to PostgreSQL.
Apply type casting based on dictionary.
Return JSON: {converted_sql, type_casts, changes}.

Dictionary (used columns only):
{mini_dict}

SQL:
{sql_content}
"""
    
    # 3. LLM 호출
    response = llm_client.call_llm(short_prompt)
    
    return response
```

**장점**:
- 단순하고 빠름
- 정확성 유지

**단점**:
- 여전히 토큰 제한에 걸릴 수 있음

---

### 2.4 전략 B: 청킹 (분할 변환)

**적용**: 매우 큰 복잡한 SQL

```python
def chunked_conversion(sql_content, dictionary):
    """SQL을 의미 단위로 분할 후 변환"""
    
    # 1. SQL 분할 (의미 단위)
    chunks = split_sql_semantically(sql_content)
    
    # chunks 예시:
    # [
    #   { type: 'select', content: 'SELECT u.user_id, u.username...' },
    #   { type: 'from', content: 'FROM users u' },
    #   { type: 'joins', content: 'LEFT JOIN orders o... LEFT JOIN products p...' },
    #   { type: 'where', content: 'WHERE 1=1...' },
    #   { type: 'dynamic', content: '<if test="userId != null">...</if>' },
    #   { type: 'order_by', content: 'ORDER BY u.created_date DESC' }
    # ]
    
    # 2. 각 청크 개별 변환
    converted_chunks = []
    for chunk in chunks:
        converted = convert_chunk(chunk, dictionary)
        converted_chunks.append(converted)
    
    # 3. 청크 재조립
    final_sql = reassemble_chunks(converted_chunks)
    
    # 4. 전체 검증 (구문 체크)
    validate_sql_syntax(final_sql)
    
    return final_sql


def split_sql_semantically(sql):
    """SQL을 의미 단위로 분할"""
    
    chunks = []
    
    # SELECT 절
    select_match = re.search(r'SELECT\s+(.+?)\s+FROM', sql, re.DOTALL | re.IGNORECASE)
    if select_match:
        chunks.append({
            'type': 'select',
            'content': f"SELECT {select_match.group(1).strip()}"
        })
    
    # FROM 절
    from_match = re.search(r'FROM\s+(\w+\s+\w+)', sql, re.IGNORECASE)
    if from_match:
        chunks.append({
            'type': 'from',
            'content': f"FROM {from_match.group(1).strip()}"
        })
    
    # JOIN 절들
    join_pattern = r'((?:LEFT|RIGHT|INNER|OUTER)?\s*JOIN\s+\w+\s+\w+\s+ON\s+[^<]+?)(?=LEFT|RIGHT|INNER|OUTER|JOIN|WHERE|<|$)'
    joins = re.findall(join_pattern, sql, re.IGNORECASE | re.DOTALL)
    for join in joins:
        chunks.append({
            'type': 'join',
            'content': join.strip()
        })
    
    # WHERE 절 (정적 부분)
    where_match = re.search(r'WHERE\s+(.+?)(?=<|ORDER|GROUP|$)', sql, re.DOTALL | re.IGNORECASE)
    if where_match:
        chunks.append({
            'type': 'where',
            'content': f"WHERE {where_match.group(1).strip()}"
        })
    
    # 동적 SQL 블록들
    dynamic_blocks = re.findall(r'(<(?:if|choose|foreach|include)[^>]*>.*?</(?:if|choose|foreach|include)>)', sql, re.DOTALL)
    for block in dynamic_blocks:
        chunks.append({
            'type': 'dynamic',
            'content': block
        })
    
    # ORDER BY
    order_match = re.search(r'ORDER\s+BY\s+(.+?)(?=<|LIMIT|$)', sql, re.DOTALL | re.IGNORECASE)
    if order_match:
        chunks.append({
            'type': 'order_by',
            'content': f"ORDER BY {order_match.group(1).strip()}"
        })
    
    return chunks


def convert_chunk(chunk, dictionary):
    """단일 청크 변환"""
    
    if chunk['type'] in ['select', 'from', 'join', 'where', 'order_by']:
        # 정적 SQL - 표준 변환
        prompt = f"""
Convert this Oracle SQL fragment to PostgreSQL.
Type: {chunk['type']}
SQL: {chunk['content']}

Dictionary: {relevant columns}

Return only converted SQL.
"""
        
        response = llm_client.call_llm(prompt)
        return {
            'type': chunk['type'],
            'content': response['converted_sql']
        }
    
    elif chunk['type'] == 'dynamic':
        # 동적 SQL - 타입 캐스팅만
        prompt = f"""
Apply PostgreSQL type casting to this MyBatis dynamic SQL.
Keep all MyBatis tags intact.
SQL: {chunk['content']}

Dictionary: {relevant columns}

Return only converted SQL with type casts.
"""
        
        response = llm_client.call_llm(prompt)
        return {
            'type': 'dynamic',
            'content': response['converted_sql']
        }


def reassemble_chunks(chunks):
    """청크들을 재조립"""
    
    # 순서대로 조립
    parts = []
    
    # SELECT
    select_chunks = [c for c in chunks if c['type'] == 'select']
    if select_chunks:
        parts.append(select_chunks[0]['content'])
    
    # FROM
    from_chunks = [c for c in chunks if c['type'] == 'from']
    if from_chunks:
        parts.append(from_chunks[0]['content'])
    
    # JOINs
    join_chunks = [c for c in chunks if c['type'] == 'join']
    for join in join_chunks:
        parts.append(join['content'])
    
    # WHERE
    where_chunks = [c for c in chunks if c['type'] == 'where']
    if where_chunks:
        parts.append(where_chunks[0]['content'])
    
    # 동적 블록들
    dynamic_chunks = [c for c in chunks if c['type'] == 'dynamic']
    for dyn in dynamic_chunks:
        parts.append(dyn['content'])
    
    # ORDER BY
    order_chunks = [c for c in chunks if c['type'] == 'order_by']
    if order_chunks:
        parts.append(order_chunks[0]['content'])
    
    return '\n'.join(parts)
```

**장점**:
- 매우 큰 SQL도 처리 가능
- 토큰 제한 회피

**단점**:
- 복잡함
- 재조립 시 실수 가능성
- LLM 호출 횟수 증가 (비용 증가)

---

### 2.5 전략 C: 수동 검토

**적용**: 청킹으로도 어려운 극단적 케이스

```python
def manual_review_required(sql_content, analysis):
    """수동 검토 필요"""
    
    # 1. 원본 보존
    backup_path = f"{work_dir}/manual_review/{mapper_name}_{sql_id}.xml"
    save_file(backup_path, sql_content)
    
    # 2. 리포트 생성
    report = {
        "mapper": mapper_name,
        "sql_id": sql_id,
        "reason": "too_large_and_complex",
        "char_count": analysis['char_count'],
        "complexity": analysis['complexity'],
        "recommendation": "Consider refactoring this SQL into smaller queries or stored procedure",
        "file": backup_path
    }
    
    # 3. 스킵
    return {
        "status": "skipped",
        "reason": "manual_review_required",
        "report": report
    }
```

---

## 3. 대용량 결과셋 처리

### 3.1 감지

```java
// DatabaseExecutor.java

public ExecutionResult execute(ExtractedSql extractedSql) {
    
    try (PreparedStatement ps = connection.prepareStatement(
        extractedSql.getSql(),
        ResultSet.TYPE_FORWARD_ONLY,
        ResultSet.CONCUR_READ_ONLY
    )) {
        
        // Fetch size 설정 (메모리 효율)
        ps.setFetchSize(1000);
        
        bindParameters(ps, extractedSql);
        
        boolean hasResultSet = ps.execute();
        
        if (hasResultSet) {
            ResultSet rs = ps.getResultSet();
            
            // 결과셋 크기 추정
            int estimatedSize = estimateResultSetSize(rs);
            
            if (estimatedSize > 10000) {
                // 대용량 - 샘플링
                return executeLargeResultSet(rs, estimatedSize);
            } else {
                // 일반 - 전체 로드
                return executeNormalResultSet(rs);
            }
        }
        
    } catch (SQLException e) {
        // ...
    }
}
```

---

### 3.2 샘플링 전략

```java
private ExecutionResult executeLargeResultSet(ResultSet rs, int estimatedSize) 
    throws SQLException {
    
    List<Map<String, Object>> sampledRows = new ArrayList<>();
    
    // 전략: 처음 1000 + 중간 샘플 3000 + 마지막 1000 = 5000
    
    int sampleSize = 5000;
    int headSize = 1000;
    int tailSize = 1000;
    int middleSize = sampleSize - headSize - tailSize;
    
    // 1. 처음 1000개
    int rowCount = 0;
    while (rs.next() && rowCount < headSize) {
        sampledRows.add(extractRow(rs));
        rowCount++;
    }
    
    // 2. 중간 샘플링 (균등 분포)
    int skipInterval = Math.max(1, (estimatedSize - headSize - tailSize) / middleSize);
    int skipCounter = 0;
    
    while (rs.next() && sampledRows.size() < headSize + middleSize) {
        rowCount++;
        
        if (skipCounter % skipInterval == 0) {
            sampledRows.add(extractRow(rs));
        }
        skipCounter++;
    }
    
    // 3. 마지막으로 이동하기 위해 나머지 순회
    List<Map<String, Object>> tailBuffer = new ArrayList<>(tailSize);
    while (rs.next()) {
        rowCount++;
        tailBuffer.add(extractRow(rs));
        
        // 링 버퍼 (마지막 N개만 유지)
        if (tailBuffer.size() > tailSize) {
            tailBuffer.remove(0);
        }
    }
    
    // 4. 마지막 1000개 추가
    sampledRows.addAll(tailBuffer);
    
    return ExecutionResult.success(
        sampledRows,
        rowCount,  // 실제 총 행 수
        executionTime,
        extractedSql.getSql()
    ).withSampling(true, sampleSize, rowCount);
}
```

---

### 3.3 결과 비교 (샘플링된 경우)

```python
# oma/validation/comparator.py

def compare_results(source_result, target_result):
    """결과 비교"""
    
    # 샘플링 여부 확인
    source_sampled = source_result.get('sampled', False)
    target_sampled = target_result.get('sampled', False)
    
    if source_sampled or target_sampled:
        return compare_sampled_results(source_result, target_result)
    else:
        return compare_full_results(source_result, target_result)


def compare_sampled_results(source_result, target_result):
    """샘플링된 결과 비교"""
    
    # 1. 총 행 수 비교
    source_total = source_result['row_count']
    target_total = target_result['row_count']
    
    count_matched = source_total == target_total
    
    # 2. 샘플 데이터 비교
    source_samples = source_result['rows']
    target_samples = target_result['rows']
    
    # 샘플 크기가 다를 수 있음 (더 작은 쪽 기준)
    compare_size = min(len(source_samples), len(target_samples))
    
    matched_samples = 0
    mismatches = []
    
    for i in range(compare_size):
        if compare_row(source_samples[i], target_samples[i]):
            matched_samples += 1
        else:
            mismatches.append({
                'sample_index': i,
                'source': source_samples[i],
                'target': target_samples[i]
            })
    
    sample_match_rate = matched_samples / compare_size
    
    return {
        'matched': count_matched and sample_match_rate > 0.95,
        'row_count_matched': count_matched,
        'sampled': True,
        'source_total_rows': source_total,
        'target_total_rows': target_total,
        'samples_compared': compare_size,
        'samples_matched': matched_samples,
        'sample_match_rate': sample_match_rate,
        'mismatches': mismatches[:10],  # 최대 10개만
        'confidence': 'medium' if sample_match_rate > 0.95 else 'low',
        'note': 'Large result set - sampled comparison (5,000 rows)'
    }
```

---

## 4. 설정 및 임계값

### oma.properties 추가 설정

```properties
# Large SQL Handling
LLM_MAX_TOKENS=100000               # Max tokens per request
LLM_LARGE_SQL_THRESHOLD=50000       # SQL over this = large (chars)
LLM_CHUNK_OVERLAP=500               # Overlap when chunking

# Large ResultSet Handling
VALIDATION_LARGE_RESULTSET_THRESHOLD=10000   # Rows
VALIDATION_SAMPLE_SIZE=5000                   # Sample size for large resultsets
VALIDATION_HEAD_SIZE=1000                     # First N rows
VALIDATION_TAIL_SIZE=1000                     # Last N rows
```

---

## 5. 리포트

### 5.1 대용량 SQL 리포트

```json
{
  "large_sql_report": [
    {
      "mapper": "ReportMapper.xml",
      "sql_id": "massiveReport",
      "char_count": 75000,
      "token_estimate": 25000,
      "complexity": 145,
      "strategy_used": "chunked",
      "chunks_created": 8,
      "llm_calls": 8,
      "status": "success"
    },
    {
      "mapper": "LegacyMapper.xml",
      "sql_id": "hugeQuery",
      "char_count": 120000,
      "token_estimate": 40000,
      "complexity": 350,
      "strategy_used": "manual_review",
      "status": "skipped",
      "reason": "Too large and complex - manual refactoring recommended"
    }
  ]
}
```

---

### 5.2 대용량 결과셋 리포트

```json
{
  "large_resultset_report": [
    {
      "tc_id": "OrderMapper_getAllOrders_tc001",
      "source_total_rows": 523000,
      "target_total_rows": 523000,
      "sampled": true,
      "samples_compared": 5000,
      "samples_matched": 4987,
      "sample_match_rate": 0.9974,
      "confidence": "medium",
      "note": "Large result set - sampled 5,000 out of 523,000 rows"
    }
  ]
}
```

---

## 6. 콘솔 출력

```
⚠️  Large SQL Detected

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mapper: ReportMapper.xml
SQL ID: massiveReport
Size: 75,000 characters (~25K tokens)
Complexity: 145 (very_complex)

Strategy: Chunked Conversion
  • Split into 8 semantic chunks
  • Convert each chunk separately
  • Reassemble and validate

Status: ✓ Success
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


⚠️  Large Result Set Detected

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TC: OrderMapper_getAllOrders_tc001

Result Size: 523,000 rows (source), 523,000 rows (target)

Sampling Strategy Applied:
  • Head: 1,000 rows
  • Middle: 3,000 rows (sampled)
  • Tail: 1,000 rows
  • Total compared: 5,000 rows

Match Rate: 99.74% (4,987 / 5,000 matched)
Confidence: Medium

Status: ✓ Passed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-27
- 목적: 대용량 SQL 및 결과셋 처리 전략
