package com.oma.validator;

import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;
import com.oma.validator.model.ExecutionResult;
import com.oma.validator.model.ExtractedSql;
import com.oma.validator.model.TestCase;
import com.oma.validator.model.ValidationResult;
import org.apache.ibatis.session.SqlSessionFactory;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;

/**
 * 검증 서비스 (메인 엔트리)
 *
 * stdin으로 검증 요청 JSON을 받아, 소스(원본 매퍼→Oracle)와 타겟(변환 매퍼→PostgreSQL)에서
 * 각 TC의 SQL을 추출·실행하고, 결과를 stdout으로 JSON 출력한다 (Python 브리지와 통신).
 *
 * 핵심: 소스/타겟은 같은 namespace+id라도 SQL이 다르므로 SqlSessionFactory를 2개
 * 구성하고 각각에서 getBoundSql로 추출한다.
 *
 * 요청 JSON 스키마:
 * {
 *   "sourceMapperDir": "...", "targetMapperDir": "...",
 *   "source": {"url","user","password","driver"},
 *   "target": {"url","user","password","driver"},
 *   "testCases": [ {test_case_id, namespace, sql_id, parameters, ...}, ... ]
 * }
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - stdin JSON → 소스/타겟 팩토리+커넥션 구성 → TC별 추출/실행 → stdout JSON
 *   - DriverManager 직접 연결(검증 배치용), 커넥션은 finally에서 정리
 */
public class ValidationService {

    private final SqlExtractor sourceExtractor;
    private final SqlExtractor targetExtractor;
    private final DatabaseExecutor sourceExecutor;
    private final DatabaseExecutor targetExecutor;

    public ValidationService(SqlSessionFactory sourceFactory, SqlSessionFactory targetFactory,
                             Connection sourceConn, Connection targetConn,
                             int queryTimeoutSeconds) {
        this.sourceExtractor = new SqlExtractor(sourceFactory);
        this.targetExtractor = new SqlExtractor(targetFactory);
        this.sourceExecutor = new DatabaseExecutor(sourceConn, queryTimeoutSeconds);
        this.targetExecutor = new DatabaseExecutor(targetConn, queryTimeoutSeconds);
    }

    /**
     * TC 하나를 검증한다 (소스/타겟 각각 추출·실행).
     *
     * @param tc 테스트 케이스
     * @return ValidationResult
     */
    public ValidationResult validate(TestCase tc) {
        try {
            String statementId = tc.getStatementId();
            ExtractedSql sourceSql = sourceExtractor.extractSql(statementId, tc.getParameters());
            ExtractedSql targetSql = targetExtractor.extractSql(statementId, tc.getParameters());

            ExecutionResult sourceResult = sourceExecutor.execute(sourceSql);
            ExecutionResult targetResult = targetExecutor.execute(targetSql);

            return ValidationResult.of(tc.getTestCaseId(), sourceResult, targetResult);
        } catch (Exception e) {
            return ValidationResult.error(tc.getTestCaseId(), e.getMessage());
        }
    }

    // --------------------------------------------------------------- main/IO

    /**
     * 요청 JSON 구조 (Gson 역직렬화용).
     */
    static class Request {
        String sourceMapperDir;
        String targetMapperDir;
        DbConfig source;
        DbConfig target;
        List<TestCase> testCases;
        int queryTimeoutSeconds;  // 개별 SQL 실행 타임아웃(초). 0이면 기본값
    }

    /**
     * DB 접속 정보.
     */
    static class DbConfig {
        String url;
        String user;
        String password;
        String driver;
    }

    public static void main(String[] args) {
        Gson gson = new Gson();
        try {
            Request request = gson.fromJson(readStdin(), Request.class);
            List<ValidationResult> results = run(request);
            System.out.println(gson.toJson(results));
        } catch (JsonSyntaxException e) {
            System.err.println(gson.toJson(java.util.Map.of(
                    "error", "invalid request JSON: " + e.getMessage())));
            System.exit(1);
        } catch (Exception e) {
            System.err.println(gson.toJson(java.util.Map.of(
                    "error", e.getMessage())));
            System.exit(1);
        }
    }

    /**
     * 요청을 받아 팩토리/커넥션을 구성하고 모든 TC를 검증한다.
     *
     * @param request 검증 요청
     * @return TC별 결과 리스트
     * @throws Exception 팩토리/커넥션 구성 실패 시
     */
    static List<ValidationResult> run(Request request) throws Exception {
        Connection sourceConn = null;
        Connection targetConn = null;
        try {
            sourceConn = connect(request.source);
            targetConn = connect(request.target);

            SqlSessionFactory sourceFactory = MapperFactoryBuilder.build(
                    request.sourceMapperDir, new SingleConnectionDataSource(sourceConn), "source");
            SqlSessionFactory targetFactory = MapperFactoryBuilder.build(
                    request.targetMapperDir, new SingleConnectionDataSource(targetConn), "target");

            ValidationService service = new ValidationService(
                    sourceFactory, targetFactory, sourceConn, targetConn,
                    request.queryTimeoutSeconds);

            List<ValidationResult> results = new ArrayList<>();
            for (TestCase tc : request.testCases) {
                results.add(service.validate(tc));
            }
            return results;
        } finally {
            closeQuietly(sourceConn);
            closeQuietly(targetConn);
        }
    }

    /**
     * DbConfig로 JDBC 커넥션을 만든다.
     */
    private static Connection connect(DbConfig cfg) throws Exception {
        if (cfg.driver != null && !cfg.driver.isEmpty()) {
            Class.forName(cfg.driver);
        }
        Properties props = new Properties();
        if (cfg.user != null) {
            props.setProperty("user", cfg.user);
        }
        if (cfg.password != null) {
            props.setProperty("password", cfg.password);
        }
        return DriverManager.getConnection(cfg.url, props);
    }

    private static String readStdin() throws Exception {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append('\n');
            }
        }
        return sb.toString();
    }

    private static void closeQuietly(Connection conn) {
        if (conn != null) {
            try {
                conn.close();
            } catch (Exception ignore) {
                // 무시
            }
        }
    }
}
