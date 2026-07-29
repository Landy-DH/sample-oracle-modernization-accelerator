package com.oma.validator;

import com.oma.validator.model.ExtractedSql;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ParameterMapping;
import org.apache.ibatis.reflection.MetaObject;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * MyBatis 기반 SQL 추출기 (검증의 핵심)
 *
 * getBoundSql(parameters) 한 번으로 동적 SQL(&lt;if&gt;/&lt;choose&gt;/&lt;foreach&gt;/
 * &lt;include&gt;)을 모두 평가한 완성 SQL과 '?' 바인딩 순서/값을 얻는다.
 * XML 파싱/정규식으로는 재현 불가능한 것을 MyBatis가 정확히 처리한다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - extractSql(): getBoundSql로 SQL 완성 + ParameterMapping 순서대로 값 추출
 *   - additionalParameters(foreach 생성 변수) 우선 조회 → parameterObject 폴백
 */
public class SqlExtractor {

    private final SqlSessionFactory sqlSessionFactory;

    public SqlExtractor(SqlSessionFactory sqlSessionFactory) {
        this.sqlSessionFactory = sqlSessionFactory;
    }

    /**
     * TC 파라미터를 적용해 실제 실행될 SQL과 바인딩 값을 추출한다.
     *
     * @param statementId MappedStatement id (namespace.sqlId)
     * @param parameters  TC 파라미터 맵
     * @return 완성된 ExtractedSql
     */
    public ExtractedSql extractSql(String statementId, Map<String, Object> parameters) {
        try (SqlSession session = sqlSessionFactory.openSession()) {
            Configuration configuration = session.getConfiguration();
            MappedStatement ms = configuration.getMappedStatement(statementId);

            // 동적 SQL 전부 평가된 BoundSql 생성
            BoundSql boundSql = ms.getBoundSql(parameters);
            String sql = boundSql.getSql();

            List<Object> values = extractParameterValues(configuration, boundSql, parameters);
            return new ExtractedSql(statementId, sql, values);
        }
    }

    /**
     * ParameterMapping 순서대로 실제 바인딩 값을 뽑는다.
     *
     * foreach 등에서 MyBatis가 만든 추가 파라미터(additionalParameters)를 우선 조회하고,
     * 없으면 parameterObject(Map 또는 POJO)에서 property로 조회한다.
     *
     * @param configuration MyBatis 설정 (MetaObject 생성용)
     * @param boundSql       완성된 BoundSql
     * @param originalParams 원본 파라미터 맵
     * @return '?' 순서에 대응하는 바인딩 값 리스트
     */
    private List<Object> extractParameterValues(
            Configuration configuration, BoundSql boundSql, Map<String, Object> originalParams) {
        List<Object> values = new ArrayList<>();
        List<ParameterMapping> mappings = boundSql.getParameterMappings();
        Object parameterObject = boundSql.getParameterObject();
        MetaObject paramMeta = (parameterObject == null)
                ? null
                : configuration.newMetaObject(parameterObject);

        for (ParameterMapping mapping : mappings) {
            values.add(resolveValue(mapping, boundSql, paramMeta, parameterObject));
        }
        return values;
    }

    /**
     * 단일 ParameterMapping의 바인딩 값을 결정한다.
     */
    private Object resolveValue(ParameterMapping mapping, BoundSql boundSql,
                                MetaObject paramMeta, Object parameterObject) {
        String property = mapping.getProperty();

        // foreach 등에서 생성된 추가 파라미터 우선
        if (boundSql.hasAdditionalParameter(property)) {
            return boundSql.getAdditionalParameter(property);
        }
        if (parameterObject == null) {
            return null;
        }
        // 단일 파라미터가 그대로 값인 경우 (타입 핸들러 등록된 스칼라)
        if (paramMeta != null && paramMeta.hasGetter(property)) {
            return paramMeta.getValue(property);
        }
        if (parameterObject instanceof Map) {
            return ((Map<?, ?>) parameterObject).get(property);
        }
        return parameterObject;
    }
}
