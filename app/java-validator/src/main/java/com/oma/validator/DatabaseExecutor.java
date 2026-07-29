package com.oma.validator;

import com.oma.validator.model.ExecutionResult;
import com.oma.validator.model.ExtractedSql;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * DB 실행기
 *
 * 완성된 SQL(ExtractedSql)을 PreparedStatement로 실행한다.
 * - SELECT: 결과 행 반환 (대용량은 상한까지 샘플링)
 * - DML(INSERT/UPDATE/DELETE/MERGE): 트랜잭션으로 실행 후 반드시 롤백
 *   (실행 가능 여부만 검증, 실제 데이터 변경 없음)
 * - 프로시저(CALL/EXEC/BEGIN..END): 실행하지 않고 스킵 (COMMIT 위험)
 *
 * 안전 원칙: 검증은 소스/타겟 데이터를 변경하지 않는다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - execute(): 프로시저 스킵 / DML 롤백 / SELECT 샘플링
 *   - 파라미터 바인딩, 예외 시 롤백 및 AutoCommit 복원
 * 2026-07-28 | OMA Team | DML 미인식 커밋 버그 수정
 *   - 원인: isDml()/isProcedureCall()이 SQL 원문 앞부분만 검사해
 *     선행 주석(/* *\/, --)이나 WITH(CTE) UPSERT로 시작하는 DML을
 *     DML로 판별하지 못함 → autocommit=true로 실제 커밋되어 소스/타겟
 *     데이터가 변경되고 DUP_KEY가 재발.
 *   - 수정: stripLeading()으로 선행 주석·공백을 제거한 뒤 판별하고,
 *     WITH(...) 뒤에 INSERT/UPDATE/DELETE/MERGE가 오는 CTE도 DML로 인식.
 */
public class DatabaseExecutor {

    /** SELECT 결과 최대 수집 행 수 (초과 시 sampled=true) */
    private static final int MAX_ROWS = 10_000;
    /** JDBC fetch size (메모리 효율) */
    private static final int FETCH_SIZE = 1_000;
    /** 기본 SQL 실행 타임아웃(초). config 미지정 시 사용. */
    private static final int DEFAULT_QUERY_TIMEOUT_SECONDS = 30;

    private final Connection connection;
    private final int queryTimeoutSeconds;

    public DatabaseExecutor(Connection connection) {
        this(connection, DEFAULT_QUERY_TIMEOUT_SECONDS);
    }

    /**
     * @param connection          DB 커넥션
     * @param queryTimeoutSeconds 개별 SQL 실행 타임아웃(초). 0 이하면 기본값 사용.
     *                            필터 없는 대량 조회가 검증 전체를 막지 않도록 하는 상한.
     */
    public DatabaseExecutor(Connection connection, int queryTimeoutSeconds) {
        this.connection = connection;
        this.queryTimeoutSeconds =
                queryTimeoutSeconds > 0 ? queryTimeoutSeconds : DEFAULT_QUERY_TIMEOUT_SECONDS;
    }

    /**
     * SQL을 실행하고 결과를 반환한다.
     *
     * @param extractedSql 완성된 SQL + 바인딩 값
     * @return ExecutionResult
     */
    public ExecutionResult execute(ExtractedSql extractedSql) {
        String sql = extractedSql.getSql();

        if (isProcedureCall(sql)) {
            return ExecutionResult.skipped("Procedure call skipped - may modify data", sql);
        }

        boolean isDml = isDml(sql);
        long start = System.currentTimeMillis();

        try {
            if (isDml) {
                connection.setAutoCommit(false);
            }
            try (PreparedStatement ps = connection.prepareStatement(sql)) {
                ps.setFetchSize(FETCH_SIZE);
                // 대량 조회 하나가 검증 전체를 막지 않도록 실행 시간 상한
                try {
                    ps.setQueryTimeout(queryTimeoutSeconds);
                } catch (SQLException ignore) {
                    // 일부 드라이버 미지원 - 무시
                }
                bindParameters(ps, extractedSql.getParameterValues());

                boolean hasResultSet = ps.execute();
                long elapsed = System.currentTimeMillis() - start;

                if (hasResultSet) {
                    try (ResultSet rs = ps.getResultSet()) {
                        return buildSelectResult(rs, elapsed, sql);
                    }
                }
                int affected = ps.getUpdateCount();
                boolean rolledBack = false;
                if (isDml) {
                    connection.rollback();
                    rolledBack = true;
                }
                return ExecutionResult.dmlSuccess(affected, rolledBack, elapsed, sql);
            } finally {
                if (isDml) {
                    connection.setAutoCommit(true);
                }
            }
        } catch (SQLException e) {
            safeRollback(isDml);
            return ExecutionResult.failure(e.getMessage(),
                    System.currentTimeMillis() - start, sql);
        }
    }

    /**
     * SELECT 결과를 최대 MAX_ROWS까지 수집해 결과를 만든다.
     */
    private ExecutionResult buildSelectResult(ResultSet rs, long elapsed, String sql)
            throws SQLException {
        ResultSetMetaData meta = rs.getMetaData();
        int columnCount = meta.getColumnCount();

        List<String> columns = new ArrayList<>(columnCount);
        for (int i = 1; i <= columnCount; i++) {
            columns.add(meta.getColumnLabel(i));
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        int count = 0;
        boolean sampled = false;
        while (rs.next()) {
            count++;
            if (rows.size() < MAX_ROWS) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= columnCount; i++) {
                    row.put(columns.get(i - 1), rs.getObject(i));
                }
                rows.add(row);
            } else {
                sampled = true;
            }
        }
        return ExecutionResult.selectSuccess(rows, columns, count, sampled, elapsed, sql);
    }

    /**
     * '?' 순서대로 파라미터를 바인딩한다.
     */
    private void bindParameters(PreparedStatement ps, List<Object> values)
            throws SQLException {
        for (int i = 0; i < values.size(); i++) {
            ps.setObject(i + 1, values.get(i));
        }
    }

    /**
     * 예외 발생 시 안전하게 롤백하고 AutoCommit을 복원한다.
     */
    private void safeRollback(boolean isDml) {
        if (!isDml) {
            return;
        }
        try {
            connection.rollback();
            connection.setAutoCommit(true);
        } catch (SQLException ignore) {
            // 롤백 실패는 무시 (연결이 이미 끊긴 경우 등)
        }
    }

    /**
     * 프로시저 호출 여부를 감지한다 (실행 금지 대상).
     */
    private boolean isProcedureCall(String sql) {
        String s = stripLeading(sql).toUpperCase();
        return s.startsWith("CALL ") || s.startsWith("EXECUTE ")
                || s.startsWith("EXEC ") || s.startsWith("{CALL ")
                || (s.startsWith("BEGIN") && s.contains("END"));
    }

    /**
     * DML(INSERT/UPDATE/DELETE/MERGE) 여부를 판별한다 (롤백 대상).
     *
     * 선행 주석/공백을 제거한 뒤 판별한다. WITH(CTE)로 시작하는 UPSERT는
     * 본문에 DML이 포함되므로 함께 DML로 취급한다(실행 후 롤백 대상).
     */
    private boolean isDml(String sql) {
        String s = stripLeading(sql).toUpperCase();
        if (s.startsWith("INSERT") || s.startsWith("UPDATE")
                || s.startsWith("DELETE") || s.startsWith("MERGE")) {
            return true;
        }
        // WITH ... ( ... INSERT/UPDATE/DELETE ... ) 형태의 CTE 기반 UPSERT
        if (s.startsWith("WITH")) {
            return s.contains("INSERT ") || s.contains("UPDATE ")
                    || s.contains("DELETE ") || s.contains("MERGE ");
        }
        return false;
    }

    /**
     * SQL 앞쪽의 선행 공백과 주석(블록 주석, 라인 주석)을 반복 제거한다.
     *
     * 검증 대상 SQL은 흔히 `/* mapper.id *\/` 주석으로 시작하므로,
     * 원문 앞부분만 보고 DML/프로시저 여부를 판별하면 오분류된다.
     *
     * @param sql 원본 SQL (null 허용)
     * @return 선행 주석/공백이 제거된 SQL (없으면 빈 문자열)
     */
    private String stripLeading(String sql) {
        if (sql == null) {
            return "";
        }
        int i = 0;
        int n = sql.length();
        while (i < n) {
            char c = sql.charAt(i);
            if (Character.isWhitespace(c)) {
                i++;
            } else if (c == '/' && i + 1 < n && sql.charAt(i + 1) == '*') {
                int end = sql.indexOf("*/", i + 2);
                if (end < 0) {
                    return "";
                }
                i = end + 2;
            } else if (c == '-' && i + 1 < n && sql.charAt(i + 1) == '-') {
                int nl = sql.indexOf('\n', i + 2);
                if (nl < 0) {
                    return "";
                }
                i = nl + 1;
            } else {
                break;
            }
        }
        return sql.substring(i);
    }
}
