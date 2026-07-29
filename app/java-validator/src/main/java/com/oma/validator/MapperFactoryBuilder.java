package com.oma.validator;

import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;

import javax.sql.DataSource;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;

/**
 * 디렉토리의 매퍼 XML들을 로드해 SqlSessionFactory를 구성하는 빌더
 *
 * 소스(원본 Oracle 매퍼)용과 타겟(변환된 PostgreSQL 매퍼)용 팩토리를 각각 만든다.
 * 같은 namespace+id라도 SQL 본문이 다르므로 팩토리를 분리해야 정확한 검증이 된다.
 *
 * DataSource는 실제 실행에 쓰이지 않지만(SQL 추출은 커넥션 불필요) MyBatis
 * Environment 구성에 필요해 주입한다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - build(mapperDir, dataSource): 디렉토리 재귀 순회하며 *.xml 매퍼 등록
 *   - 개별 매퍼 로드 실패는 경고 후 계속 (전체 중단 방지)
 */
public final class MapperFactoryBuilder {

    private MapperFactoryBuilder() {
    }

    /**
     * 매퍼 디렉토리로부터 SqlSessionFactory를 만든다.
     *
     * @param mapperDir  매퍼 XML 루트 디렉토리
     * @param dataSource MyBatis Environment용 DataSource
     * @param envId      환경 id (source/target 구분용)
     * @return 구성된 SqlSessionFactory
     * @throws Exception 매퍼 디렉토리 순회 실패 시
     */
    public static SqlSessionFactory build(String mapperDir, DataSource dataSource, String envId)
            throws Exception {
        // 미지 타입 별칭(camelMap, xxxVO 등)을 HashMap으로 폴백하는 관대한 Configuration
        Configuration configuration = new LenientConfiguration(
                new Environment(envId, new JdbcTransactionFactory(), dataSource));

        Path root = Path.of(mapperDir);
        try (Stream<Path> paths = Files.walk(root)) {
            paths.filter(p -> p.toString().endsWith(".xml"))
                 .filter(p -> !p.getFileName().toString().startsWith("._"))
                 .forEach(p -> loadMapper(configuration, p));
        }

        return new SqlSessionFactoryBuilder().build(configuration);
    }

    /**
     * 매퍼 XML 하나를 Configuration에 등록한다 (실패 시 경고 후 계속).
     */
    private static void loadMapper(Configuration configuration, Path path) {
        String resource = path.toString();
        try (InputStream is = Files.newInputStream(path)) {
            XMLMapperBuilder builder = new XMLMapperBuilder(
                    is, configuration, resource, configuration.getSqlFragments());
            builder.parse();
        } catch (Exception e) {
            System.err.println("[WARN] 매퍼 로드 실패 (건너뜀): " + resource
                    + " - " + e.getMessage());
        }
    }
}
