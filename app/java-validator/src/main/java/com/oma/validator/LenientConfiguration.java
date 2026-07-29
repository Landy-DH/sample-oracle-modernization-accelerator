package com.oma.validator;

import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.type.TypeAliasRegistry;
import org.apache.ibatis.type.TypeException;

import java.util.HashMap;

/**
 * 미지 타입 별칭을 관대하게 처리하는 MyBatis Configuration
 *
 * 검증은 SQL 추출(getBoundSql)과 실행만 하며, resultType/parameterType의 실제
 * 클래스는 사용하지 않는다(결과는 DatabaseExecutor가 ResultSet에서 직접 Map으로 읽음).
 * 그런데 매퍼 파싱 단계에서 프로젝트 고유 별칭(camelMap, xxxVO/xxxDTO 등)을 해석하지
 * 못하면 매퍼 로드가 실패한다.
 *
 * 이 Configuration은 TypeAliasRegistry를 오버라이드해, 해석 불가한 별칭을 만나면
 * 예외 대신 java.util.HashMap 으로 대체한다. 따라서 어떤 프로젝트 별칭이든 파싱을
 * 통과시킨다 (별칭의 실제 타입은 검증에 영향 없음).
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - resolveAlias 실패 시 HashMap 폴백하는 TypeAliasRegistry 주입
 */
public class LenientConfiguration extends org.apache.ibatis.session.Configuration {

    public LenientConfiguration(Environment environment) {
        super(environment);
        setMapUnderscoreToCamelCase(false);
    }

    /**
     * 미지 별칭을 HashMap으로 폴백하는 레지스트리를 반환한다.
     */
    @Override
    public TypeAliasRegistry getTypeAliasRegistry() {
        return LENIENT_REGISTRY;
    }

    /** 부모 생성자에서 typeAliasRegistry 필드 초기화 시점 문제를 피하려고 static 사용 */
    private static final TypeAliasRegistry LENIENT_REGISTRY = new TypeAliasRegistry() {
        @Override
        public <T> Class<T> resolveAlias(String string) {
            try {
                return super.resolveAlias(string);
            } catch (TypeException e) {
                // 해석 불가한 프로젝트 고유 별칭 → 검증엔 무관하므로 HashMap 대체
                @SuppressWarnings("unchecked")
                Class<T> fallback = (Class<T>) HashMap.class;
                return fallback;
            }
        }
    };
}
