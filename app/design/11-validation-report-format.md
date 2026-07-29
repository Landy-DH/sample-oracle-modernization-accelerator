# 검증 결과 리포트 형식

## 개요

검증 결과를 다양한 형태로 제공하여 사용자가 쉽게 이해하고 조치할 수 있도록 합니다.

---

## 1. 콘솔 출력 (실시간)

### 1.1 진행 상황

```
========================================
OMA Validation Started
========================================

Configuration:
  Source DB: Oracle 19c (your_source_host:1521/orcl)
  Target DB: PostgreSQL 15 (your_target_host:5432/appdb)
  Test Cases: 1,247
  Parallel Workers: 8

----------------------------------------
Progress: [████████████████░░░░░░░░░░] 62% (774/1247)
  ✓ Passed: 718
  ✗ Failed: 56
  ⏱  Avg Time: 152ms
  ⏳ ETA: 2m 15s
----------------------------------------
```

### 1.2 실패 시 즉시 출력

```
❌ FAILED: OrderMapper_complexQuery_tc003
   Reason: Row count mismatch
   Expected: 125 rows
   Actual: 123 rows
   Time: Source 245ms → Target 189ms
   Location: /projects/oma/testcases/OrderMapper_complexQuery_tc003.json
```

### 1.3 최종 요약

```
========================================
Validation Completed
========================================

Summary:
  Total Test Cases: 1,247
  ✓ Passed: 1,189 (95.3%)
  ✗ Failed: 58 (4.7%)
  ⚠ Warnings: 12

Performance:
  Total Time: 8m 34s
  Avg Source Time: 45.2ms
  Avg Target Time: 38.7ms
  ⚡ Target Faster: 14.4%

Failure Breakdown:
  Row Count Mismatch: 12 (20.7%)
  Column Mismatch: 5 (8.6%)
  Value Mismatch: 41 (70.7%)
  Execution Error: 0 (0.0%)

Reports Generated:
  • reports/validation-summary.json
  • reports/validation-details.json
  • reports/validation-failures.csv
  • reports/validation-report.html

Next Steps:
  1. Review failures: reports/validation-failures.csv
  2. Check detailed report: reports/validation-report.html
  3. Fix issues and re-run: python scripts/run_validation.py --retry-failed
========================================
```

---

## 2. JSON 리포트

### 2.1 요약 리포트

**파일**: `${REPORT_DIR}/validation-summary.json`

```json
{
  "validation_run": {
    "run_id": "20260726_143022",
    "started_at": "2026-07-26T14:30:22Z",
    "completed_at": "2026-07-26T14:38:56Z",
    "duration_seconds": 514
  },
  
  "configuration": {
    "source_db": {
      "type": "oracle",
      "host": "your_source_host",
      "port": 1521,
      "database": "orcl"
    },
    "target_db": {
      "type": "postgres",
      "host": "your_target_host",
      "port": 5432,
      "database": "appdb"
    },
    "parallel_workers": 8
  },
  
  "summary": {
    "total_test_cases": 1247,
    "passed": 1189,
    "failed": 58,
    "warnings": 12,
    "success_rate": 95.3,
    
    "failure_breakdown": {
      "row_count_mismatch": 12,
      "column_mismatch": 5,
      "value_mismatch": 41,
      "execution_error": 0
    }
  },
  
  "performance": {
    "total_queries": 1247,
    "source_total_time_ms": 56394,
    "target_total_time_ms": 48253,
    "source_avg_time_ms": 45.2,
    "target_avg_time_ms": 38.7,
    "target_improvement_percent": 14.4,
    
    "slow_queries_threshold_ms": 1000,
    "slow_queries_count": 23
  },
  
  "top_failures": [
    {
      "tc_id": "OrderMapper_complexQuery_tc003",
      "mapper": "OrderMapper",
      "sql_id": "complexQuery",
      "failure_type": "row_count_mismatch",
      "severity": "high"
    }
  ],
  
  "recommendations": [
    "Review 12 row count mismatches - may indicate data sync issues",
    "Check 5 column mismatches - possible schema differences",
    "23 slow queries detected - consider optimization"
  ]
}
```

---

### 2.2 상세 리포트

**파일**: `${REPORT_DIR}/validation-details.json`

```json
{
  "run_id": "20260726_143022",
  
  "test_cases": [
    {
      "tc_id": "UserMapper_searchUsers_tc001",
      "mapper": "UserMapper",
      "sql_id": "searchUsers",
      "status": "passed",
      
      "source_result": {
        "success": true,
        "row_count": 5,
        "execution_time_ms": 23,
        "sql": "SELECT user_id, username, status FROM users WHERE user_id = ? AND status = ?"
      },
      
      "target_result": {
        "success": true,
        "row_count": 5,
        "execution_time_ms": 18,
        "sql": "SELECT user_id, username, status FROM users WHERE user_id = $1::INTEGER AND status = $2"
      },
      
      "comparison": {
        "matched": true,
        "row_count_matched": true,
        "columns_matched": true,
        "values_matched": true,
        "time_difference_ms": -5,
        "time_difference_percent": -21.7
      }
    },
    
    {
      "tc_id": "OrderMapper_complexQuery_tc003",
      "mapper": "OrderMapper",
      "sql_id": "complexQuery",
      "status": "failed",
      
      "source_result": {
        "success": true,
        "row_count": 125,
        "columns": ["order_id", "user_id", "amount", "status"],
        "execution_time_ms": 245,
        "sql": "SELECT o.order_id, o.user_id, o.amount, o.status FROM orders o WHERE o.status = ? AND o.amount > ?"
      },
      
      "target_result": {
        "success": true,
        "row_count": 123,
        "columns": ["order_id", "user_id", "amount", "status"],
        "execution_time_ms": 189,
        "sql": "SELECT o.order_id, o.user_id, o.amount, o.status FROM orders o WHERE o.status = $1 AND o.amount > $2::NUMERIC"
      },
      
      "comparison": {
        "matched": false,
        "row_count_matched": false,
        "columns_matched": true,
        "values_matched": false,
        
        "differences": [
          {
            "type": "row_count_mismatch",
            "source": 125,
            "target": 123,
            "difference": -2
          }
        ],
        
        "missing_rows": [
          {"order_id": 10523, "user_id": 789, "amount": 15000.00, "status": "A"},
          {"order_id": 10891, "user_id": 456, "amount": 22500.50, "status": "A"}
        ],
        
        "time_difference_ms": -56,
        "time_difference_percent": -22.9
      },
      
      "failure_analysis": {
        "severity": "high",
        "likely_cause": "data_sync_issue",
        "suggestion": "Check if source and target databases are in sync. Missing 2 rows in target DB.",
        "action": "manual_review_required"
      }
    },
    
    {
      "tc_id": "ProductMapper_getPrice_tc002",
      "mapper": "ProductMapper",
      "sql_id": "getPrice",
      "status": "failed",
      
      "source_result": {
        "success": true,
        "row_count": 1,
        "rows": [{"product_id": 100, "price": 99.99}],
        "execution_time_ms": 12
      },
      
      "target_result": {
        "success": true,
        "row_count": 1,
        "rows": [{"product_id": 100, "price": 99.989999999999995}],
        "execution_time_ms": 9
      },
      
      "comparison": {
        "matched": false,
        "row_count_matched": true,
        "columns_matched": true,
        "values_matched": false,
        
        "value_differences": [
          {
            "row_index": 0,
            "column": "price",
            "source_value": 99.99,
            "target_value": 99.989999999999995,
            "difference": -0.000000000000005,
            "within_tolerance": true
          }
        ]
      },
      
      "failure_analysis": {
        "severity": "low",
        "likely_cause": "floating_point_precision",
        "suggestion": "Difference is within tolerance (< 0.001). Consider using NUMERIC type instead of DOUBLE PRECISION.",
        "action": "warning_only"
      }
    }
  ]
}
```

---

## 3. CSV 리포트 (Excel용)

**파일**: `${REPORT_DIR}/validation-failures.csv`

```csv
tc_id,mapper,sql_id,status,failure_type,severity,source_rows,target_rows,row_diff,source_time_ms,target_time_ms,suggestion,action
OrderMapper_complexQuery_tc003,OrderMapper,complexQuery,failed,row_count_mismatch,high,125,123,-2,245,189,Check data sync between source and target,manual_review
ProductMapper_getPrice_tc002,ProductMapper,getPrice,failed,value_mismatch,low,1,1,0,12,9,Floating point precision issue - within tolerance,warning_only
UserMapper_getUsersByStatus_tc005,UserMapper,getUsersByStatus,failed,column_mismatch,critical,50,50,0,34,28,Column 'created_date' missing in target result,schema_issue
OrderMapper_getOrders_tc007,OrderMapper,getOrders,failed,value_mismatch,medium,10,10,0,56,43,3 rows have different 'amount' values,data_mismatch
```

---

## 4. HTML 리포트 (시각화)

**파일**: `${REPORT_DIR}/validation-report.html`

### 구조

```html
<!DOCTYPE html>
<html>
<head>
    <title>OMA Validation Report - 2026-07-26</title>
    <style>
        /* Bootstrap + Custom CSS */
    </style>
</head>
<body>
    <!-- 1. 대시보드 -->
    <section id="dashboard">
        <h1>Validation Summary</h1>
        
        <!-- 성공률 게이지 -->
        <div class="gauge">
            <svg><!-- 95.3% 원형 게이지 --></svg>
            <div class="gauge-text">95.3% Success</div>
        </div>
        
        <!-- 통계 카드 -->
        <div class="stats-grid">
            <div class="stat-card passed">
                <div class="stat-number">1,189</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat-card failed">
                <div class="stat-number">58</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card warning">
                <div class="stat-number">12</div>
                <div class="stat-label">Warnings</div>
            </div>
        </div>
        
        <!-- 실패 유형 파이 차트 -->
        <div class="chart">
            <canvas id="failureTypeChart"></canvas>
        </div>
        
        <!-- 성능 비교 바 차트 -->
        <div class="chart">
            <canvas id="performanceChart"></canvas>
        </div>
    </section>
    
    <!-- 2. 실패 목록 -->
    <section id="failures">
        <h2>Failed Test Cases (58)</h2>
        
        <table class="failures-table">
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Test Case</th>
                    <th>Mapper</th>
                    <th>SQL ID</th>
                    <th>Failure Type</th>
                    <th>Details</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                <tr class="severity-high" onclick="showDetails('tc003')">
                    <td><span class="badge-high">HIGH</span></td>
                    <td>OrderMapper_complexQuery_tc003</td>
                    <td>OrderMapper</td>
                    <td>complexQuery</td>
                    <td>Row Count Mismatch</td>
                    <td>125 → 123 (-2 rows)</td>
                    <td><button class="btn-review">Review</button></td>
                </tr>
                <!-- ... -->
            </tbody>
        </table>
    </section>
    
    <!-- 3. 상세 비교 (클릭 시 확장) -->
    <section id="details">
        <h2>Test Case Details</h2>
        
        <div id="tc003-details" class="tc-details">
            <h3>OrderMapper_complexQuery_tc003</h3>
            
            <!-- SQL 비교 -->
            <div class="sql-comparison">
                <div class="sql-source">
                    <h4>Source SQL (Oracle)</h4>
                    <pre><code>SELECT o.order_id, o.user_id, o.amount, o.status
FROM orders o
WHERE o.status = ?
  AND o.amount > ?</code></pre>
                </div>
                
                <div class="sql-target">
                    <h4>Target SQL (PostgreSQL)</h4>
                    <pre><code>SELECT o.order_id, o.user_id, o.amount, o.status
FROM orders o
WHERE o.status = $1
  AND o.amount > $2::NUMERIC</code></pre>
                </div>
            </div>
            
            <!-- 파라미터 -->
            <div class="parameters">
                <h4>Parameters</h4>
                <table>
                    <tr>
                        <th>Parameter</th>
                        <th>Value</th>
                        <th>Type</th>
                    </tr>
                    <tr>
                        <td>status</td>
                        <td>'A'</td>
                        <td>CHAR(1)</td>
                    </tr>
                    <tr>
                        <td>amount</td>
                        <td>10000</td>
                        <td>NUMERIC</td>
                    </tr>
                </table>
            </div>
            
            <!-- 결과 비교 -->
            <div class="result-comparison">
                <h4>Result Comparison</h4>
                <table>
                    <tr>
                        <th></th>
                        <th>Source (Oracle)</th>
                        <th>Target (PostgreSQL)</th>
                        <th>Difference</th>
                    </tr>
                    <tr>
                        <td>Row Count</td>
                        <td class="mismatch">125</td>
                        <td class="mismatch">123</td>
                        <td class="diff-negative">-2</td>
                    </tr>
                    <tr>
                        <td>Execution Time</td>
                        <td>245 ms</td>
                        <td>189 ms</td>
                        <td class="diff-positive">-56 ms (-22.9%)</td>
                    </tr>
                </table>
            </div>
            
            <!-- 누락된 행 -->
            <div class="missing-rows">
                <h4>Missing Rows in Target (2)</h4>
                <table>
                    <tr>
                        <th>order_id</th>
                        <th>user_id</th>
                        <th>amount</th>
                        <th>status</th>
                    </tr>
                    <tr class="highlight-missing">
                        <td>10523</td>
                        <td>789</td>
                        <td>15000.00</td>
                        <td>A</td>
                    </tr>
                    <tr class="highlight-missing">
                        <td>10891</td>
                        <td>456</td>
                        <td>22500.50</td>
                        <td>A</td>
                    </tr>
                </table>
            </div>
            
            <!-- 분석 및 권장사항 -->
            <div class="analysis">
                <h4>Failure Analysis</h4>
                <dl>
                    <dt>Severity:</dt>
                    <dd><span class="badge-high">HIGH</span></dd>
                    
                    <dt>Likely Cause:</dt>
                    <dd>Data synchronization issue between source and target databases</dd>
                    
                    <dt>Suggestion:</dt>
                    <dd>
                        <ul>
                            <li>Verify that data migration/sync is complete</li>
                            <li>Check if rows with order_id 10523 and 10891 exist in target DB</li>
                            <li>Review data loading logs for errors</li>
                        </ul>
                    </dd>
                    
                    <dt>Action Required:</dt>
                    <dd><strong>Manual Review</strong> - Investigate missing data</dd>
                </dl>
            </div>
        </div>
    </section>
    
    <!-- 4. 성능 분석 -->
    <section id="performance">
        <h2>Performance Analysis</h2>
        
        <!-- 상위 10 느린 쿼리 -->
        <h3>Top 10 Slowest Queries</h3>
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Test Case</th>
                    <th>Source Time</th>
                    <th>Target Time</th>
                    <th>Difference</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>1</td>
                    <td>OrderMapper_complexQuery_tc001</td>
                    <td>1,250 ms</td>
                    <td class="slow">2,840 ms</td>
                    <td class="diff-negative">+1,590 ms (+127%)</td>
                </tr>
                <!-- ... -->
            </tbody>
        </table>
        
        <!-- 성능 향상/저하 분포 -->
        <div class="chart">
            <canvas id="performanceDistributionChart"></canvas>
        </div>
    </section>
    
    <!-- 5. 권장사항 -->
    <section id="recommendations">
        <h2>Recommendations</h2>
        
        <div class="recommendation-card critical">
            <h3>🔴 Critical Issues (5)</h3>
            <ul>
                <li>5 test cases have column mismatches - review schema differences</li>
            </ul>
        </div>
        
        <div class="recommendation-card high">
            <h3>🟠 High Priority (12)</h3>
            <ul>
                <li>12 test cases have row count mismatches - check data sync</li>
                <li>Consider re-running data migration for affected tables</li>
            </ul>
        </div>
        
        <div class="recommendation-card medium">
            <h3>🟡 Medium Priority (41)</h3>
            <ul>
                <li>41 test cases have value mismatches</li>
                <li>23 queries are slower in PostgreSQL - review indexes</li>
            </ul>
        </div>
        
        <div class="recommendation-card low">
            <h3>🟢 Low Priority (12)</h3>
            <ul>
                <li>12 warnings for floating point precision differences</li>
                <li>Consider using NUMERIC type for monetary values</li>
            </ul>
        </div>
    </section>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        // 차트 렌더링 코드
    </script>
</body>
</html>
```

---

## 5. 터미널 Diff 출력 (개발자용)

**실패한 TC에 대해 즉시 확인 가능한 diff**

```
❌ OrderMapper_complexQuery_tc003 FAILED

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FAILURE: Row Count Mismatch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source (Oracle):  125 rows
Target (PostgreSQL): 123 rows
Difference: -2 rows

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Missing Rows in Target:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Row 1:
    order_id: 10523
    user_id: 789
    amount: 15000.00
    status: A

  - Row 2:
    order_id: 10891
    user_id: 456
    amount: 22500.50
    status: A

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Severity: HIGH
  Likely Cause: Data sync issue
  
  Suggestion:
    • Check if data migration completed successfully
    • Query target DB: SELECT * FROM orders WHERE order_id IN (10523, 10891)
    • Review data loading logs
  
  Action: Manual review required

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SQL Comparison:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source SQL:
  SELECT o.order_id, o.user_id, o.amount, o.status
  FROM orders o
  WHERE o.status = ?
    AND o.amount > ?

Target SQL:
  SELECT o.order_id, o.user_id, o.amount, o.status
  FROM orders o
  WHERE o.status = $1
    AND o.amount > $2::NUMERIC

Parameters:
  status: 'A' (CHAR)
  amount: 10000 (NUMERIC)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Performance:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Source Time: 245 ms
  Target Time: 189 ms
  Improvement: -56 ms (-22.9%) ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 6. Slack/Teams 알림 (옵션)

### 검증 완료 시 알림

```
🔔 OMA Validation Completed

✅ Success Rate: 95.3% (1,189 / 1,247)
❌ Failed: 58
⚠️  Warnings: 12
⏱️  Duration: 8m 34s

Failures:
  • Row Count Mismatch: 12
  • Column Mismatch: 5
  • Value Mismatch: 41

🔗 View Report: http://jenkins/oma/reports/validation-report.html

Actions:
  🔍 Review Failures
  🔄 Retry Failed Tests
  📊 View Dashboard
```

---

## 7. 재검증 명령어

### 실패한 TC만 재실행

```bash
# 실패한 TC만 재검증
python scripts/run_validation.py --retry-failed

# 특정 Mapper만 재검증
python scripts/run_validation.py --mapper OrderMapper

# 특정 실패 유형만 재검증
python scripts/run_validation.py --failure-type row_count_mismatch

# 상세 출력
python scripts/run_validation.py --verbose

# Dry run (실제 실행 없이 확인)
python scripts/run_validation.py --dry-run
```

---

## 8. 파일 위치 요약

| 파일 | 경로 | 용도 |
|------|------|------|
| **요약 JSON** | `reports/validation-summary.json` | 전체 통계 및 요약 |
| **상세 JSON** | `reports/validation-details.json` | TC별 상세 결과 |
| **실패 CSV** | `reports/validation-failures.csv` | Excel에서 열기 |
| **HTML 리포트** | `reports/validation-report.html` | 브라우저에서 시각화 |
| **로그 파일** | `reports/validation.log` | 디버깅용 상세 로그 |

---

## 9. 리포트 생성 Python 코드

```python
# oma/validation/reporter.py

class ValidationReporter:
    """검증 결과 리포팅"""
    
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.report_dir = f"{work_dir}/reports"
    
    def generate_all_reports(self, results):
        """모든 형식의 리포트 생성"""
        
        # 1. 콘솔 출력
        self.print_summary(results)
        
        # 2. JSON 리포트
        self.generate_json_summary(results)
        self.generate_json_details(results)
        
        # 3. CSV 리포트
        self.generate_csv_failures(results)
        
        # 4. HTML 리포트
        self.generate_html_report(results)
        
        # 5. 로그 파일
        self.write_log(results)
    
    def print_summary(self, results):
        """콘솔 요약 출력"""
        passed = sum(1 for r in results if r['status'] == 'passed')
        total = len(results)
        
        print(f"\n{'='*50}")
        print(f"Validation Completed")
        print(f"{'='*50}\n")
        print(f"Total: {total}")
        print(f"✓ Passed: {passed} ({passed/total*100:.1f}%)")
        print(f"✗ Failed: {total-passed} ({(total-passed)/total*100:.1f}%)")
        print(f"\nReports: {self.report_dir}/")
        print(f"{'='*50}\n")
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 검증 결과 리포트 형식 정의
