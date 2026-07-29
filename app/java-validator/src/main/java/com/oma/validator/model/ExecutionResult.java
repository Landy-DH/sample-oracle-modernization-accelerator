package com.oma.validator.model;

import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * 단일 DB에서의 SQL 실행 결과
 *
 * SELECT는 rows/rowCount, DML은 affectedRows(+rolledBack), 프로시저는 skipped.
 * 결과 비교(Python comparator)에서 사용된다. 대용량 SELECT는 sampled=true로 표시.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - success/failure/skipped 팩토리, rolledBack/sampled 플래그
 */
public class ExecutionResult {

    private boolean success;
    private boolean skipped;
    private boolean rolledBack;
    private boolean sampled;

    private List<Map<String, Object>> rows;
    private List<String> columns;
    private int rowCount;
    private int affectedRows;
    private long executionTimeMs;
    private String sql;
    private String errorMessage;
    private String skipReason;

    private ExecutionResult() {
        this.rows = Collections.emptyList();
        this.columns = Collections.emptyList();
    }

    /**
     * SELECT 성공 결과를 만든다.
     */
    public static ExecutionResult selectSuccess(
            List<Map<String, Object>> rows, List<String> columns,
            int rowCount, boolean sampled, long timeMs, String sql) {
        ExecutionResult r = new ExecutionResult();
        r.success = true;
        r.rows = rows;
        r.columns = columns;
        r.rowCount = rowCount;
        r.sampled = sampled;
        r.executionTimeMs = timeMs;
        r.sql = sql;
        return r;
    }

    /**
     * DML 성공 결과를 만든다 (롤백됨).
     */
    public static ExecutionResult dmlSuccess(
            int affectedRows, boolean rolledBack, long timeMs, String sql) {
        ExecutionResult r = new ExecutionResult();
        r.success = true;
        r.affectedRows = affectedRows;
        r.rolledBack = rolledBack;
        r.executionTimeMs = timeMs;
        r.sql = sql;
        return r;
    }

    /**
     * 실행 실패 결과를 만든다.
     */
    public static ExecutionResult failure(String errorMessage, long timeMs, String sql) {
        ExecutionResult r = new ExecutionResult();
        r.success = false;
        r.errorMessage = errorMessage;
        r.executionTimeMs = timeMs;
        r.sql = sql;
        return r;
    }

    /**
     * 스킵 결과를 만든다 (프로시저 등).
     */
    public static ExecutionResult skipped(String reason, String sql) {
        ExecutionResult r = new ExecutionResult();
        r.success = false;
        r.skipped = true;
        r.skipReason = reason;
        r.sql = sql;
        return r;
    }

    public boolean isSuccess() {
        return success;
    }

    public boolean isSkipped() {
        return skipped;
    }

    public int getRowCount() {
        return rowCount;
    }
}
