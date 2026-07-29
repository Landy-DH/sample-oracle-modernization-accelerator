package com.oma.validator.model;

import java.util.List;
import java.util.Map;

/**
 * 테스트 케이스 모델 (Python generator가 생성한 TC JSON과 대응)
 *
 * Python 측 test_case JSON을 Gson으로 역직렬화한다.
 * statementId = mapper namespace + "." + sql_id 로 구성해 MyBatis에서 조회한다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - test_case_id/mapper/sql_id/namespace/parameters/expected_branches 필드
 *   - getStatementId(): namespace 우선, 없으면 mapper 사용
 */
public class TestCase {

    private String test_case_id;
    private String mapper;
    private String sql_id;
    private String namespace;
    private Map<String, Object> parameters;
    private List<String> expected_branches;

    public String getTestCaseId() {
        return test_case_id;
    }

    public String getMapper() {
        return mapper;
    }

    public String getSqlId() {
        return sql_id;
    }

    public String getNamespace() {
        return namespace;
    }

    public Map<String, Object> getParameters() {
        return parameters;
    }

    public List<String> getExpectedBranches() {
        return expected_branches;
    }

    /**
     * MyBatis MappedStatement 조회용 statement id를 만든다.
     * namespace가 있으면 "namespace.sqlId", 없으면 "mapper.sqlId".
     *
     * @return statement id
     */
    public String getStatementId() {
        String prefix = (namespace != null && !namespace.isEmpty()) ? namespace : mapper;
        return prefix + "." + sql_id;
    }
}
