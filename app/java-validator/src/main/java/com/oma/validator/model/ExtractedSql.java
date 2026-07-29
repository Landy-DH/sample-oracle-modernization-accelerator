package com.oma.validator.model;

import java.util.List;

/**
 * MyBatis BoundSql로 완성된 실행 대상 SQL과 바인딩 값
 *
 * getBoundSql이 동적 SQL(<if>/<choose>/<foreach>/<include>)을 모두 평가한 결과.
 * sql은 '?' placeholder를 가진 완성된 SQL, parameterValues는 순서대로 바인딩할 값.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 */
public class ExtractedSql {

    private final String statementId;
    private final String sql;
    private final List<Object> parameterValues;

    public ExtractedSql(String statementId, String sql, List<Object> parameterValues) {
        this.statementId = statementId;
        this.sql = sql;
        this.parameterValues = parameterValues;
    }

    public String getStatementId() {
        return statementId;
    }

    public String getSql() {
        return sql;
    }

    public List<Object> getParameterValues() {
        return parameterValues;
    }
}
