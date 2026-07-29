package com.oma.validator;

import javax.sql.DataSource;
import java.io.PrintWriter;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.logging.Logger;

/**
 * 단일 커넥션을 감싸는 DataSource (MyBatis Environment 구성용)
 *
 * SQL 추출(getBoundSql)은 실제 DB 커넥션을 쓰지 않지만 MyBatis Environment 생성에
 * DataSource가 필요하다. 실행은 ValidationService가 별도 커넥션으로 직접 수행하므로,
 * 이 DataSource가 주는 커넥션은 닫지 않도록 close를 무시하는 래퍼로 반환한다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 *   - getConnection()은 동일 커넥션 반환, 외부 소유이므로 close 무시
 */
public class SingleConnectionDataSource implements DataSource {

    private final Connection connection;

    public SingleConnectionDataSource(Connection connection) {
        this.connection = connection;
    }

    @Override
    public Connection getConnection() {
        // close() 호출만 무시하고 나머지는 실제 커넥션에 위임하는 프록시
        return (Connection) Proxy.newProxyInstance(
                Connection.class.getClassLoader(),
                new Class<?>[]{Connection.class},
                (proxy, method, methodArgs) -> {
                    if ("close".equals(method.getName())) {
                        return null;
                    }
                    return method.invoke(connection, methodArgs);
                });
    }

    @Override
    public Connection getConnection(String username, String password) {
        return getConnection();
    }

    @Override
    public PrintWriter getLogWriter() {
        return null;
    }

    @Override
    public void setLogWriter(PrintWriter out) {
        // no-op
    }

    @Override
    public void setLoginTimeout(int seconds) {
        // no-op
    }

    @Override
    public int getLoginTimeout() {
        return 0;
    }

    @Override
    public Logger getParentLogger() throws SQLFeatureNotSupportedException {
        throw new SQLFeatureNotSupportedException();
    }

    @Override
    public <T> T unwrap(Class<T> iface) throws SQLException {
        if (iface.isInstance(this)) {
            return iface.cast(this);
        }
        throw new SQLException("Cannot unwrap to " + iface.getName());
    }

    @Override
    public boolean isWrapperFor(Class<?> iface) {
        return iface.isInstance(this);
    }
}
