-- ============================================================
-- OMA Workshop 샘플 데이터 생성 스크립트
-- Oracle → Aurora PostgreSQL 마이그레이션 실습용
-- 
-- 포함 항목:
--   - 다양한 데이터 타입 (VARCHAR2, NUMBER, DATE, TIMESTAMP, CLOB, BLOB, RAW 등)
--   - 시퀀스, 인덱스, 제약조건
--   - 빌트인 함수 활용 (NVL, DECODE, TO_CHAR, TO_DATE, SUBSTR, INSTR 등)
--   - 사용자 정의 함수 (User-Defined Functions)
--   - 스토어드 프로시저 (Stored Procedures)
--   - 패키지 (Package)
--   - 트리거 (Trigger)
--   - 뷰 (View)
--   - 동의어 (Synonym)
--
-- 실행 방법:
--   sqlplus omaservice/OMAworkshop2024@<HOST>:1521/ORCL @create_sample_schema.sql
-- ============================================================

SET ECHO ON
SET FEEDBACK ON
WHENEVER SQLERROR CONTINUE

-- ============================================================
-- 1. 시퀀스 생성
-- ============================================================
CREATE SEQUENCE SEQ_CUSTOMER START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE SEQ_ORDER START WITH 10001 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE SEQ_PRODUCT START WITH 100 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE SEQ_EMPLOYEE START WITH 1000 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE SEQ_LOG START WITH 1 INCREMENT BY 1 NOCACHE;

-- ============================================================
-- 2. 테이블 생성 — 다양한 데이터 타입
-- ============================================================

-- 고객 마스터 (VARCHAR2, NUMBER, DATE, CLOB, TIMESTAMP)
CREATE TABLE CUSTOMERS (
    CUSTOMER_ID     NUMBER(10)      NOT NULL,
    CUSTOMER_NAME   VARCHAR2(100)   NOT NULL,
    EMAIL           VARCHAR2(200),
    PHONE           VARCHAR2(20),
    ADDRESS         VARCHAR2(500),
    CUSTOMER_TYPE   CHAR(1)         DEFAULT 'P',  -- P: 개인, B: 기업
    CREDIT_LIMIT    NUMBER(12,2)    DEFAULT 0,
    BIRTH_DATE      DATE,
    MEMO            CLOB,
    PHOTO           BLOB,
    REG_DATE        TIMESTAMP       DEFAULT SYSTIMESTAMP,
    UPD_DATE        TIMESTAMP,
    STATUS          VARCHAR2(10)    DEFAULT 'ACTIVE',
    CONSTRAINT PK_CUSTOMERS PRIMARY KEY (CUSTOMER_ID),
    CONSTRAINT CK_CUST_TYPE CHECK (CUSTOMER_TYPE IN ('P', 'B')),
    CONSTRAINT CK_CUST_STATUS CHECK (STATUS IN ('ACTIVE', 'INACTIVE', 'SUSPENDED'))
);

-- 상품 마스터 (NUMBER, VARCHAR2, RAW, FLOAT)
CREATE TABLE PRODUCTS (
    PRODUCT_ID      NUMBER(10)      NOT NULL,
    PRODUCT_NAME    VARCHAR2(200)   NOT NULL,
    CATEGORY        VARCHAR2(50),
    UNIT_PRICE      NUMBER(10,2)    NOT NULL,
    WEIGHT          FLOAT,
    PRODUCT_CODE    RAW(16),
    DESCRIPTION     VARCHAR2(4000),
    IS_ACTIVE       NUMBER(1)       DEFAULT 1,
    CREATED_DATE    DATE            DEFAULT SYSDATE,
    CONSTRAINT PK_PRODUCTS PRIMARY KEY (PRODUCT_ID)
);

-- 주문 (NUMBER, DATE, VARCHAR2, TIMESTAMP WITH TIME ZONE)
CREATE TABLE ORDERS (
    ORDER_ID        NUMBER(12)      NOT NULL,
    CUSTOMER_ID     NUMBER(10)      NOT NULL,
    ORDER_DATE      DATE            NOT NULL,
    SHIP_DATE       DATE,
    TOTAL_AMOUNT    NUMBER(14,2)    DEFAULT 0,
    TAX_AMOUNT      NUMBER(12,2)    DEFAULT 0,
    DISCOUNT_RATE   NUMBER(5,2)     DEFAULT 0,
    ORDER_STATUS    VARCHAR2(20)    DEFAULT 'PENDING',
    PAYMENT_METHOD  VARCHAR2(20),
    REMARKS         VARCHAR2(2000),
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    CONSTRAINT PK_ORDERS PRIMARY KEY (ORDER_ID),
    CONSTRAINT FK_ORDERS_CUST FOREIGN KEY (CUSTOMER_ID) REFERENCES CUSTOMERS(CUSTOMER_ID),
    CONSTRAINT CK_ORD_STATUS CHECK (ORDER_STATUS IN ('PENDING','CONFIRMED','SHIPPED','DELIVERED','CANCELLED'))
);

-- 주문 상세 (복합 PK, NUMBER)
CREATE TABLE ORDER_ITEMS (
    ORDER_ID        NUMBER(12)      NOT NULL,
    ITEM_SEQ        NUMBER(5)       NOT NULL,
    PRODUCT_ID      NUMBER(10)      NOT NULL,
    QUANTITY        NUMBER(8)       NOT NULL,
    UNIT_PRICE      NUMBER(10,2)    NOT NULL,
    DISCOUNT_AMT    NUMBER(10,2)    DEFAULT 0,
    LINE_TOTAL      NUMBER(12,2)    GENERATED ALWAYS AS (QUANTITY * UNIT_PRICE - DISCOUNT_AMT) VIRTUAL,
    CONSTRAINT PK_ORDER_ITEMS PRIMARY KEY (ORDER_ID, ITEM_SEQ),
    CONSTRAINT FK_OI_ORDER FOREIGN KEY (ORDER_ID) REFERENCES ORDERS(ORDER_ID),
    CONSTRAINT FK_OI_PRODUCT FOREIGN KEY (PRODUCT_ID) REFERENCES PRODUCTS(PRODUCT_ID)
);

-- 직원 (NUMBER, VARCHAR2, DATE, 셀프 조인 FK)
CREATE TABLE EMPLOYEES (
    EMPLOYEE_ID     NUMBER(10)      NOT NULL,
    EMPLOYEE_NAME   VARCHAR2(100)   NOT NULL,
    DEPARTMENT      VARCHAR2(50),
    POSITION_TITLE  VARCHAR2(50),
    HIRE_DATE       DATE,
    SALARY          NUMBER(12,2),
    COMMISSION_PCT  NUMBER(4,2),
    MANAGER_ID      NUMBER(10),
    EMAIL           VARCHAR2(200),
    PHONE_EXT       VARCHAR2(10),
    CONSTRAINT PK_EMPLOYEES PRIMARY KEY (EMPLOYEE_ID),
    CONSTRAINT FK_EMP_MGR FOREIGN KEY (MANAGER_ID) REFERENCES EMPLOYEES(EMPLOYEE_ID)
);

-- 감사 로그 (TIMESTAMP, CLOB, NUMBER)
CREATE TABLE AUDIT_LOG (
    LOG_ID          NUMBER(12)      NOT NULL,
    TABLE_NAME      VARCHAR2(50)    NOT NULL,
    OPERATION       VARCHAR2(10)    NOT NULL,
    OLD_VALUE       CLOB,
    NEW_VALUE       CLOB,
    CHANGED_BY      VARCHAR2(50),
    CHANGED_AT      TIMESTAMP       DEFAULT SYSTIMESTAMP,
    CONSTRAINT PK_AUDIT_LOG PRIMARY KEY (LOG_ID)
);

-- 코드 마스터 (범용 코드 테이블)
CREATE TABLE CODE_MASTER (
    CODE_GROUP      VARCHAR2(20)    NOT NULL,
    CODE_VALUE      VARCHAR2(20)    NOT NULL,
    CODE_NAME       VARCHAR2(100)   NOT NULL,
    SORT_ORDER      NUMBER(5)       DEFAULT 0,
    USE_YN          CHAR(1)         DEFAULT 'Y',
    DESCRIPTION     VARCHAR2(500),
    CONSTRAINT PK_CODE_MASTER PRIMARY KEY (CODE_GROUP, CODE_VALUE)
);

-- ============================================================
-- 3. 인덱스 생성
-- ============================================================
CREATE INDEX IDX_CUST_NAME ON CUSTOMERS(CUSTOMER_NAME);
CREATE INDEX IDX_CUST_EMAIL ON CUSTOMERS(EMAIL);
CREATE INDEX IDX_CUST_STATUS ON CUSTOMERS(STATUS);
CREATE INDEX IDX_ORD_DATE ON ORDERS(ORDER_DATE);
CREATE INDEX IDX_ORD_CUST ON ORDERS(CUSTOMER_ID);
CREATE INDEX IDX_ORD_STATUS ON ORDERS(ORDER_STATUS);
CREATE INDEX IDX_PROD_CATEGORY ON PRODUCTS(CATEGORY);
CREATE INDEX IDX_EMP_DEPT ON EMPLOYEES(DEPARTMENT);
CREATE INDEX IDX_EMP_MGR ON EMPLOYEES(MANAGER_ID);
CREATE INDEX IDX_AUDIT_TABLE ON AUDIT_LOG(TABLE_NAME, CHANGED_AT);

-- ============================================================
-- 4. 사용자 정의 함수 (User-Defined Functions)
-- ============================================================

-- 4-1. 금액 포맷팅 함수 (NVL, TO_CHAR, DECODE 활용)
CREATE OR REPLACE FUNCTION FN_FORMAT_AMOUNT(
    p_amount    IN NUMBER,
    p_currency  IN VARCHAR2 DEFAULT 'KRW'
) RETURN VARCHAR2
IS
    v_result VARCHAR2(100);
BEGIN
    v_result := CASE p_currency
        WHEN 'KRW' THEN TO_CHAR(NVL(p_amount, 0), 'FM999,999,999,999')
        WHEN 'USD' THEN '$' || TO_CHAR(NVL(p_amount, 0), 'FM999,999,999.00')
        WHEN 'JPY' THEN TO_CHAR(NVL(p_amount, 0), 'FM999,999,999')
        ELSE TO_CHAR(NVL(p_amount, 0), 'FM999,999,999.00') || ' ' || p_currency
    END;
    RETURN v_result;
END;
/

-- 4-2. 마스킹 함수 (SUBSTR, RPAD, LENGTH 활용)
CREATE OR REPLACE FUNCTION FN_MASK_STRING(
    p_str       IN VARCHAR2,
    p_show_cnt  IN NUMBER DEFAULT 3
) RETURN VARCHAR2
IS
BEGIN
    IF p_str IS NULL OR LENGTH(p_str) <= p_show_cnt THEN
        RETURN p_str;
    END IF;
    RETURN SUBSTR(p_str, 1, p_show_cnt) || RPAD('*', LENGTH(p_str) - p_show_cnt, '*');
END;
/

-- 4-3. 나이 계산 함수 (MONTHS_BETWEEN, TRUNC, SYSDATE 활용)
CREATE OR REPLACE FUNCTION FN_CALC_AGE(
    p_birth_date IN DATE
) RETURN NUMBER
IS
BEGIN
    IF p_birth_date IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN TRUNC(MONTHS_BETWEEN(SYSDATE, p_birth_date) / 12);
END;
/

-- 4-4. 주문 총액 계산 함수 (SUM, NVL, 서브쿼리)
CREATE OR REPLACE FUNCTION FN_GET_ORDER_TOTAL(
    p_order_id IN NUMBER
) RETURN NUMBER
IS
    v_total NUMBER(14,2);
BEGIN
    SELECT NVL(SUM(QUANTITY * UNIT_PRICE - NVL(DISCOUNT_AMT, 0)), 0)
    INTO v_total
    FROM ORDER_ITEMS
    WHERE ORDER_ID = p_order_id;
    RETURN v_total;
END;
/

-- 4-5. 비즈니스 일수 계산 함수 (LOOP, TO_CHAR, BETWEEN)
CREATE OR REPLACE FUNCTION FN_BUSINESS_DAYS(
    p_start_date IN DATE,
    p_end_date   IN DATE
) RETURN NUMBER
IS
    v_count NUMBER := 0;
    v_date  DATE := p_start_date;
BEGIN
    WHILE v_date <= p_end_date LOOP
        IF TO_CHAR(v_date, 'DY', 'NLS_DATE_LANGUAGE=AMERICAN') NOT IN ('SAT', 'SUN') THEN
            v_count := v_count + 1;
        END IF;
        v_date := v_date + 1;
    END LOOP;
    RETURN v_count;
END;
/

-- ============================================================
-- 5. 스토어드 프로시저 (Stored Procedures)
-- ============================================================

-- 5-1. 주문 생성 프로시저 (시퀀스, INSERT, EXCEPTION)
CREATE OR REPLACE PROCEDURE SP_CREATE_ORDER(
    p_customer_id   IN NUMBER,
    p_payment       IN VARCHAR2,
    p_order_id      OUT NUMBER,
    p_remarks       IN VARCHAR2 DEFAULT NULL
)
IS
    v_exists NUMBER;
BEGIN
    -- 고객 존재 확인
    SELECT COUNT(*) INTO v_exists
    FROM CUSTOMERS
    WHERE CUSTOMER_ID = p_customer_id AND STATUS = 'ACTIVE';

    IF v_exists = 0 THEN
        RAISE_APPLICATION_ERROR(-20001, '유효하지 않은 고객입니다. CUSTOMER_ID=' || p_customer_id);
    END IF;

    -- 주문 생성
    p_order_id := SEQ_ORDER.NEXTVAL;
    INSERT INTO ORDERS (ORDER_ID, CUSTOMER_ID, ORDER_DATE, PAYMENT_METHOD, REMARKS)
    VALUES (p_order_id, p_customer_id, SYSDATE, p_payment, p_remarks);

    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;
END;
/

-- 5-2. 주문 상세 추가 프로시저 (UPDATE, SELECT INTO, NVL)
CREATE OR REPLACE PROCEDURE SP_ADD_ORDER_ITEM(
    p_order_id      IN NUMBER,
    p_product_id    IN NUMBER,
    p_quantity       IN NUMBER,
    p_discount_amt  IN NUMBER DEFAULT 0
)
IS
    v_unit_price    NUMBER(10,2);
    v_max_seq       NUMBER(5);
    v_line_total    NUMBER(12,2);
BEGIN
    -- 상품 가격 조회
    SELECT UNIT_PRICE INTO v_unit_price
    FROM PRODUCTS
    WHERE PRODUCT_ID = p_product_id AND IS_ACTIVE = 1;

    -- 시퀀스 번호 계산
    SELECT NVL(MAX(ITEM_SEQ), 0) + 1 INTO v_max_seq
    FROM ORDER_ITEMS
    WHERE ORDER_ID = p_order_id;

    -- 주문 상세 추가
    INSERT INTO ORDER_ITEMS (ORDER_ID, ITEM_SEQ, PRODUCT_ID, QUANTITY, UNIT_PRICE, DISCOUNT_AMT)
    VALUES (p_order_id, v_max_seq, p_product_id, p_quantity, v_unit_price, NVL(p_discount_amt, 0));

    -- 주문 총액 업데이트
    v_line_total := p_quantity * v_unit_price - NVL(p_discount_amt, 0);
    UPDATE ORDERS
    SET TOTAL_AMOUNT = NVL(TOTAL_AMOUNT, 0) + v_line_total
    WHERE ORDER_ID = p_order_id;

    COMMIT;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20002, '유효하지 않은 상품입니다. PRODUCT_ID=' || p_product_id);
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;
END;
/

-- 5-3. 월별 매출 집계 프로시저 (GROUP BY, TO_CHAR, CURSOR, DBMS_OUTPUT)
CREATE OR REPLACE PROCEDURE SP_MONTHLY_SALES_REPORT(
    p_year IN NUMBER
)
IS
    CURSOR c_sales IS
        SELECT TO_CHAR(ORDER_DATE, 'YYYY-MM') AS MONTH,
               COUNT(*) AS ORDER_COUNT,
               SUM(TOTAL_AMOUNT) AS TOTAL_SALES,
               AVG(TOTAL_AMOUNT) AS AVG_ORDER,
               MAX(TOTAL_AMOUNT) AS MAX_ORDER
        FROM ORDERS
        WHERE TO_CHAR(ORDER_DATE, 'YYYY') = TO_CHAR(p_year)
          AND ORDER_STATUS NOT IN ('CANCELLED')
        GROUP BY TO_CHAR(ORDER_DATE, 'YYYY-MM')
        ORDER BY 1;
BEGIN
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE(' Monthly Sales Report - ' || p_year);
    DBMS_OUTPUT.PUT_LINE('========================================');
    FOR r IN c_sales LOOP
        DBMS_OUTPUT.PUT_LINE(
            r.MONTH || ' | ' ||
            LPAD(r.ORDER_COUNT, 5) || '건 | ' ||
            FN_FORMAT_AMOUNT(r.TOTAL_SALES) || ' | 평균 ' ||
            FN_FORMAT_AMOUNT(r.AVG_ORDER)
        );
    END LOOP;
END;
/

-- 5-4. 고객 등급 업데이트 프로시저 (CASE WHEN, UPDATE, ROWNUM)
CREATE OR REPLACE PROCEDURE SP_UPDATE_CUSTOMER_GRADE
IS
    CURSOR c_cust IS
        SELECT c.CUSTOMER_ID,
               NVL(SUM(o.TOTAL_AMOUNT), 0) AS TOTAL_PURCHASE
        FROM CUSTOMERS c
        LEFT JOIN ORDERS o ON c.CUSTOMER_ID = o.CUSTOMER_ID
            AND o.ORDER_DATE >= ADD_MONTHS(SYSDATE, -12)
            AND o.ORDER_STATUS = 'DELIVERED'
        WHERE c.STATUS = 'ACTIVE'
        GROUP BY c.CUSTOMER_ID;
    v_grade VARCHAR2(10);
BEGIN
    FOR r IN c_cust LOOP
        v_grade := CASE
            WHEN r.TOTAL_PURCHASE >= 10000000 THEN 'VIP'
            WHEN r.TOTAL_PURCHASE >= 5000000  THEN 'GOLD'
            WHEN r.TOTAL_PURCHASE >= 1000000  THEN 'SILVER'
            ELSE 'BRONZE'
        END;
        UPDATE CUSTOMERS
        SET MEMO = v_grade || ' (총 구매: ' || FN_FORMAT_AMOUNT(r.TOTAL_PURCHASE) || ')',
            UPD_DATE = SYSTIMESTAMP
        WHERE CUSTOMER_ID = r.CUSTOMER_ID;
    END LOOP;
    COMMIT;
END;
/

-- ============================================================
-- 6. 패키지 (Package)
-- ============================================================

-- 패키지 스펙
CREATE OR REPLACE PACKAGE PKG_CUSTOMER_MGMT
IS
    PROCEDURE ADD_CUSTOMER(
        p_name      IN VARCHAR2,
        p_email     IN VARCHAR2,
        p_phone     IN VARCHAR2 DEFAULT NULL,
        p_type      IN CHAR DEFAULT 'P',
        p_cust_id   OUT NUMBER
    );
    PROCEDURE DEACTIVATE_CUSTOMER(p_customer_id IN NUMBER);
    FUNCTION GET_CUSTOMER_INFO(p_customer_id IN NUMBER) RETURN VARCHAR2;
    FUNCTION SEARCH_CUSTOMERS(p_keyword IN VARCHAR2) RETURN SYS_REFCURSOR;
END PKG_CUSTOMER_MGMT;
/

-- 패키지 바디
CREATE OR REPLACE PACKAGE BODY PKG_CUSTOMER_MGMT
IS
    PROCEDURE ADD_CUSTOMER(
        p_name      IN VARCHAR2,
        p_email     IN VARCHAR2,
        p_phone     IN VARCHAR2 DEFAULT NULL,
        p_type      IN CHAR DEFAULT 'P',
        p_cust_id   OUT NUMBER
    )
    IS
    BEGIN
        p_cust_id := SEQ_CUSTOMER.NEXTVAL;
        INSERT INTO CUSTOMERS (CUSTOMER_ID, CUSTOMER_NAME, EMAIL, PHONE, CUSTOMER_TYPE)
        VALUES (p_cust_id, p_name, p_email, p_phone, p_type);
        COMMIT;
    END;

    PROCEDURE DEACTIVATE_CUSTOMER(p_customer_id IN NUMBER)
    IS
        v_pending NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_pending
        FROM ORDERS
        WHERE CUSTOMER_ID = p_customer_id
          AND ORDER_STATUS IN ('PENDING', 'CONFIRMED', 'SHIPPED');

        IF v_pending > 0 THEN
            RAISE_APPLICATION_ERROR(-20010, '처리 중인 주문이 있어 비활성화할 수 없습니다.');
        END IF;

        UPDATE CUSTOMERS
        SET STATUS = 'INACTIVE', UPD_DATE = SYSTIMESTAMP
        WHERE CUSTOMER_ID = p_customer_id;
        COMMIT;
    END;

    FUNCTION GET_CUSTOMER_INFO(p_customer_id IN NUMBER) RETURN VARCHAR2
    IS
        v_info VARCHAR2(500);
    BEGIN
        SELECT CUSTOMER_NAME || ' (' ||
               DECODE(CUSTOMER_TYPE, 'P', '개인', 'B', '기업') || ') ' ||
               NVL(EMAIL, '-') || ' / ' ||
               NVL(PHONE, '-') || ' / 신용한도: ' ||
               FN_FORMAT_AMOUNT(CREDIT_LIMIT)
        INTO v_info
        FROM CUSTOMERS
        WHERE CUSTOMER_ID = p_customer_id;
        RETURN v_info;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN '고객 없음 (ID=' || p_customer_id || ')';
    END;

    FUNCTION SEARCH_CUSTOMERS(p_keyword IN VARCHAR2) RETURN SYS_REFCURSOR
    IS
        v_cursor SYS_REFCURSOR;
    BEGIN
        OPEN v_cursor FOR
            SELECT CUSTOMER_ID, CUSTOMER_NAME, EMAIL, PHONE, STATUS
            FROM CUSTOMERS
            WHERE UPPER(CUSTOMER_NAME) LIKE '%' || UPPER(p_keyword) || '%'
               OR UPPER(EMAIL) LIKE '%' || UPPER(p_keyword) || '%'
            ORDER BY CUSTOMER_NAME;
        RETURN v_cursor;
    END;
END PKG_CUSTOMER_MGMT;
/

-- ============================================================
-- 7. 트리거 (Trigger)
-- ============================================================

-- 주문 상태 변경 감사 트리거
CREATE OR REPLACE TRIGGER TRG_ORDER_STATUS_AUDIT
AFTER UPDATE OF ORDER_STATUS ON ORDERS
FOR EACH ROW
BEGIN
    INSERT INTO AUDIT_LOG (LOG_ID, TABLE_NAME, OPERATION, OLD_VALUE, NEW_VALUE, CHANGED_BY, CHANGED_AT)
    VALUES (SEQ_LOG.NEXTVAL, 'ORDERS', 'UPDATE',
            'ORDER_ID=' || :OLD.ORDER_ID || ', STATUS=' || :OLD.ORDER_STATUS,
            'ORDER_ID=' || :NEW.ORDER_ID || ', STATUS=' || :NEW.ORDER_STATUS,
            USER, SYSTIMESTAMP);
END;
/

-- 고객 INSERT 감사 트리거
CREATE OR REPLACE TRIGGER TRG_CUSTOMER_INSERT_AUDIT
AFTER INSERT ON CUSTOMERS
FOR EACH ROW
BEGIN
    INSERT INTO AUDIT_LOG (LOG_ID, TABLE_NAME, OPERATION, NEW_VALUE, CHANGED_BY, CHANGED_AT)
    VALUES (SEQ_LOG.NEXTVAL, 'CUSTOMERS', 'INSERT',
            'CUSTOMER_ID=' || :NEW.CUSTOMER_ID || ', NAME=' || :NEW.CUSTOMER_NAME,
            USER, SYSTIMESTAMP);
END;
/

-- ============================================================
-- 8. 뷰 (View) — 빌트인 함수 활용
-- ============================================================

-- 주문 요약 뷰 (DECODE, NVL, TO_CHAR, CASE WHEN, RANK)
CREATE OR REPLACE VIEW VW_ORDER_SUMMARY AS
SELECT o.ORDER_ID,
       c.CUSTOMER_NAME,
       DECODE(c.CUSTOMER_TYPE, 'P', '개인', 'B', '기업', '기타') AS CUST_TYPE,
       TO_CHAR(o.ORDER_DATE, 'YYYY-MM-DD') AS ORDER_DATE_STR,
       o.TOTAL_AMOUNT,
       NVL(o.TAX_AMOUNT, 0) AS TAX_AMOUNT,
       o.TOTAL_AMOUNT - NVL(o.TAX_AMOUNT, 0) AS NET_AMOUNT,
       o.ORDER_STATUS,
       CASE o.ORDER_STATUS
           WHEN 'PENDING'   THEN '대기'
           WHEN 'CONFIRMED' THEN '확인'
           WHEN 'SHIPPED'   THEN '배송중'
           WHEN 'DELIVERED'  THEN '완료'
           WHEN 'CANCELLED' THEN '취소'
       END AS STATUS_KR,
       RANK() OVER (PARTITION BY o.CUSTOMER_ID ORDER BY o.TOTAL_AMOUNT DESC) AS AMOUNT_RANK
FROM ORDERS o
JOIN CUSTOMERS c ON o.CUSTOMER_ID = c.CUSTOMER_ID;

-- 상품 판매 현황 뷰 (GROUP BY, SUM, COUNT, AVG, 분석함수)
CREATE OR REPLACE VIEW VW_PRODUCT_SALES AS
SELECT p.PRODUCT_ID,
       p.PRODUCT_NAME,
       p.CATEGORY,
       p.UNIT_PRICE AS LIST_PRICE,
       NVL(SUM(oi.QUANTITY), 0) AS TOTAL_QTY_SOLD,
       NVL(SUM(oi.QUANTITY * oi.UNIT_PRICE), 0) AS TOTAL_REVENUE,
       COUNT(DISTINCT oi.ORDER_ID) AS ORDER_COUNT,
       ROUND(NVL(AVG(oi.UNIT_PRICE), 0), 2) AS AVG_SELL_PRICE,
       ROUND(RATIO_TO_REPORT(NVL(SUM(oi.QUANTITY * oi.UNIT_PRICE), 0)) OVER () * 100, 2) AS REVENUE_PCT
FROM PRODUCTS p
LEFT JOIN ORDER_ITEMS oi ON p.PRODUCT_ID = oi.PRODUCT_ID
GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME, p.CATEGORY, p.UNIT_PRICE;

-- 직원 조직도 뷰 (CONNECT BY, LEVEL, SYS_CONNECT_BY_PATH)
CREATE OR REPLACE VIEW VW_ORG_CHART AS
SELECT EMPLOYEE_ID,
       EMPLOYEE_NAME,
       DEPARTMENT,
       POSITION_TITLE,
       MANAGER_ID,
       LEVEL AS ORG_LEVEL,
       LPAD(' ', (LEVEL - 1) * 4) || EMPLOYEE_NAME AS ORG_TREE,
       SYS_CONNECT_BY_PATH(EMPLOYEE_NAME, ' > ') AS FULL_PATH
FROM EMPLOYEES
START WITH MANAGER_ID IS NULL
CONNECT BY PRIOR EMPLOYEE_ID = MANAGER_ID
ORDER SIBLINGS BY EMPLOYEE_NAME;

-- ============================================================
-- 9. 동의어 (Synonym)
-- NOTE: CREATE SYNONYM 권한이 없는 경우 아래는 건너뜁니다.
--       admin 계정에서 GRANT CREATE SYNONYM TO omaservice; 실행 후 재시도하세요.
-- ============================================================
-- CREATE OR REPLACE SYNONYM CUST FOR CUSTOMERS;
-- CREATE OR REPLACE SYNONYM PROD FOR PRODUCTS;
-- CREATE OR REPLACE SYNONYM ORD FOR ORDERS;

-- ============================================================
-- 10. 코드 마스터 데이터
-- ============================================================
INSERT INTO CODE_MASTER VALUES ('CUST_TYPE', 'P', '개인고객', 1, 'Y', '개인 고객');
INSERT INTO CODE_MASTER VALUES ('CUST_TYPE', 'B', '기업고객', 2, 'Y', '기업 고객');
INSERT INTO CODE_MASTER VALUES ('ORD_STATUS', 'PENDING', '대기', 1, 'Y', '주문 대기');
INSERT INTO CODE_MASTER VALUES ('ORD_STATUS', 'CONFIRMED', '확인', 2, 'Y', '주문 확인');
INSERT INTO CODE_MASTER VALUES ('ORD_STATUS', 'SHIPPED', '배송중', 3, 'Y', '배송 중');
INSERT INTO CODE_MASTER VALUES ('ORD_STATUS', 'DELIVERED', '완료', 4, 'Y', '배송 완료');
INSERT INTO CODE_MASTER VALUES ('ORD_STATUS', 'CANCELLED', '취소', 5, 'Y', '주문 취소');
INSERT INTO CODE_MASTER VALUES ('PAY_METHOD', 'CARD', '카드결제', 1, 'Y', '신용/체크카드');
INSERT INTO CODE_MASTER VALUES ('PAY_METHOD', 'BANK', '계좌이체', 2, 'Y', '실시간 계좌이체');
INSERT INTO CODE_MASTER VALUES ('PAY_METHOD', 'CASH', '현금', 3, 'Y', '현금 결제');
INSERT INTO CODE_MASTER VALUES ('CATEGORY', 'ELEC', '전자제품', 1, 'Y', '전자기기 및 가전');
INSERT INTO CODE_MASTER VALUES ('CATEGORY', 'FOOD', '식품', 2, 'Y', '식료품');
INSERT INTO CODE_MASTER VALUES ('CATEGORY', 'CLOTH', '의류', 3, 'Y', '의류 및 패션');
INSERT INTO CODE_MASTER VALUES ('CATEGORY', 'BOOK', '도서', 4, 'Y', '서적');
COMMIT;

-- ============================================================
-- 11. 샘플 데이터 INSERT
-- ============================================================

-- 직원 (조직도 테스트용)
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '김대표', '경영진', 'CEO', TO_DATE('2010-03-01','YYYY-MM-DD'), 120000000, NULL, NULL, 'ceo@oma.com', '100');
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '이부장', '영업부', '부장', TO_DATE('2012-06-15','YYYY-MM-DD'), 85000000, 0.15, 1000, 'lee@oma.com', '200');
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '박과장', '개발부', '과장', TO_DATE('2015-01-10','YYYY-MM-DD'), 70000000, 0.10, 1000, 'park@oma.com', '300');
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '최대리', '영업부', '대리', TO_DATE('2018-09-01','YYYY-MM-DD'), 55000000, 0.08, 1001, 'choi@oma.com', '201');
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '정사원', '개발부', '사원', TO_DATE('2022-03-02','YYYY-MM-DD'), 42000000, NULL, 1002, 'jung@oma.com', '301');
INSERT INTO EMPLOYEES VALUES (SEQ_EMPLOYEE.NEXTVAL, '한인턴', '개발부', '인턴', TO_DATE('2024-07-01','YYYY-MM-DD'), 24000000, NULL, 1002, 'han@oma.com', '302');
COMMIT;

-- 상품 (다양한 카테고리)
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '노트북 Pro 15', 'ELEC', 1890000, 2.1, UTL_RAW.CAST_TO_RAW('NB-PRO-15'), '15인치 고성능 노트북', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '무선 마우스 M200', 'ELEC', 35000, 0.08, UTL_RAW.CAST_TO_RAW('MS-M200'), '블루투스 무선 마우스', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '기계식 키보드 K700', 'ELEC', 129000, 0.85, UTL_RAW.CAST_TO_RAW('KB-K700'), '체리 적축 기계식 키보드', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '유기농 현미 5kg', 'FOOD', 25000, 5.0, UTL_RAW.CAST_TO_RAW('FD-RICE-5'), '국내산 유기농 현미', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '프리미엄 올리브오일 1L', 'FOOD', 18000, 1.05, UTL_RAW.CAST_TO_RAW('FD-OLIVE-1'), '이탈리아산 엑스트라 버진', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '겨울 패딩 점퍼', 'CLOTH', 199000, 0.75, UTL_RAW.CAST_TO_RAW('CL-PAD-01'), '경량 구스다운 패딩', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '클린 코드', 'BOOK', 33000, 0.6, UTL_RAW.CAST_TO_RAW('BK-CLEAN'), '로버트 C. 마틴 저', 1, SYSDATE);
INSERT INTO PRODUCTS VALUES (SEQ_PRODUCT.NEXTVAL, '27인치 모니터 4K', 'ELEC', 450000, 4.5, UTL_RAW.CAST_TO_RAW('MN-4K-27'), 'IPS 4K UHD 모니터', 1, SYSDATE);
COMMIT;

-- 고객 (패키지를 통한 생성 + 직접 INSERT 혼합)
DECLARE
    v_id NUMBER;
BEGIN
    PKG_CUSTOMER_MGMT.ADD_CUSTOMER('홍길동', 'hong@example.com', '010-1234-5678', 'P', v_id);
    UPDATE CUSTOMERS SET BIRTH_DATE = TO_DATE('1985-03-15','YYYY-MM-DD'), CREDIT_LIMIT = 5000000, ADDRESS = '서울시 강남구 테헤란로 123' WHERE CUSTOMER_ID = v_id;

    PKG_CUSTOMER_MGMT.ADD_CUSTOMER('김영희', 'kim@example.com', '010-2345-6789', 'P', v_id);
    UPDATE CUSTOMERS SET BIRTH_DATE = TO_DATE('1990-11-22','YYYY-MM-DD'), CREDIT_LIMIT = 3000000, ADDRESS = '부산시 해운대구 마린시티 45' WHERE CUSTOMER_ID = v_id;

    PKG_CUSTOMER_MGMT.ADD_CUSTOMER('(주)테크솔루션', 'info@techsol.co.kr', '02-555-1234', 'B', v_id);
    UPDATE CUSTOMERS SET CREDIT_LIMIT = 50000000, ADDRESS = '서울시 서초구 서초대로 234' WHERE CUSTOMER_ID = v_id;

    PKG_CUSTOMER_MGMT.ADD_CUSTOMER('박철수', 'park@example.com', '010-3456-7890', 'P', v_id);
    UPDATE CUSTOMERS SET BIRTH_DATE = TO_DATE('1978-07-08','YYYY-MM-DD'), CREDIT_LIMIT = 10000000, ADDRESS = '대전시 유성구 대학로 67' WHERE CUSTOMER_ID = v_id;

    PKG_CUSTOMER_MGMT.ADD_CUSTOMER('(주)그린푸드', 'order@greenfood.kr', '031-777-8888', 'B', v_id);
    UPDATE CUSTOMERS SET CREDIT_LIMIT = 30000000, ADDRESS = '경기도 성남시 분당구 판교로 89' WHERE CUSTOMER_ID = v_id;

    COMMIT;
END;
/

-- 주문 & 주문상세 (프로시저 활용)
DECLARE
    v_order_id NUMBER;
BEGIN
    -- 홍길동 주문 1
    SP_CREATE_ORDER(1, 'CARD', v_order_id, '빠른 배송 요청');
    SP_ADD_ORDER_ITEM(v_order_id, 100, 1, 50000);   -- 노트북
    SP_ADD_ORDER_ITEM(v_order_id, 101, 2, 0);        -- 마우스 x2
    UPDATE ORDERS SET ORDER_STATUS = 'DELIVERED', SHIP_DATE = SYSDATE - 5, TAX_AMOUNT = ROUND(TOTAL_AMOUNT * 0.1, 2) WHERE ORDER_ID = v_order_id;

    -- 김영희 주문
    SP_CREATE_ORDER(2, 'BANK', v_order_id);
    SP_ADD_ORDER_ITEM(v_order_id, 103, 3, 0);        -- 현미 x3
    SP_ADD_ORDER_ITEM(v_order_id, 104, 2, 5000);     -- 올리브오일 x2 할인
    UPDATE ORDERS SET ORDER_STATUS = 'SHIPPED', TAX_AMOUNT = ROUND(TOTAL_AMOUNT * 0.1, 2) WHERE ORDER_ID = v_order_id;

    -- 테크솔루션 대량 주문
    SP_CREATE_ORDER(3, 'CARD', v_order_id, '법인카드 결제');
    SP_ADD_ORDER_ITEM(v_order_id, 100, 10, 500000);  -- 노트북 10대 대량할인
    SP_ADD_ORDER_ITEM(v_order_id, 101, 10, 0);       -- 마우스 10개
    SP_ADD_ORDER_ITEM(v_order_id, 102, 10, 100000);  -- 키보드 10개 할인
    SP_ADD_ORDER_ITEM(v_order_id, 107, 10, 200000);  -- 모니터 10대 할인
    UPDATE ORDERS SET ORDER_STATUS = 'CONFIRMED', TAX_AMOUNT = ROUND(TOTAL_AMOUNT * 0.1, 2) WHERE ORDER_ID = v_order_id;

    -- 박철수 주문
    SP_CREATE_ORDER(4, 'CASH', v_order_id);
    SP_ADD_ORDER_ITEM(v_order_id, 106, 1, 0);        -- 클린코드
    SP_ADD_ORDER_ITEM(v_order_id, 105, 1, 20000);    -- 패딩 할인
    UPDATE ORDERS SET ORDER_STATUS = 'DELIVERED', SHIP_DATE = SYSDATE - 2, TAX_AMOUNT = ROUND(TOTAL_AMOUNT * 0.1, 2) WHERE ORDER_ID = v_order_id;

    -- 그린푸드 주문
    SP_CREATE_ORDER(5, 'BANK', v_order_id, '월간 정기 주문');
    SP_ADD_ORDER_ITEM(v_order_id, 103, 100, 250000); -- 현미 100포 대량할인
    SP_ADD_ORDER_ITEM(v_order_id, 104, 50, 100000);  -- 올리브오일 50개 할인
    UPDATE ORDERS SET ORDER_STATUS = 'PENDING', TAX_AMOUNT = ROUND(TOTAL_AMOUNT * 0.1, 2) WHERE ORDER_ID = v_order_id;

    COMMIT;
END;
/

-- ============================================================
-- 12. 검증 쿼리 — 빌트인 함수 활용 (마이그레이션 후 비교용)
-- ============================================================

-- 빌트인 함수 테스트 쿼리들 (마이그레이션 후 결과 비교)
-- 이 쿼리들은 OMA 앱 변환/검증 시 소스-타겟 비교에 활용됩니다.

-- NVL, DECODE, TO_CHAR
SELECT CUSTOMER_ID,
       FN_MASK_STRING(CUSTOMER_NAME) AS MASKED_NAME,
       NVL(EMAIL, 'N/A') AS EMAIL,
       DECODE(CUSTOMER_TYPE, 'P', 'Personal', 'B', 'Business', 'Unknown') AS TYPE,
       TO_CHAR(REG_DATE, 'YYYY-MM-DD HH24:MI:SS') AS REG_DATE
FROM CUSTOMERS;

-- SUBSTR, INSTR, REPLACE, UPPER, LOWER, TRIM
SELECT PRODUCT_ID,
       UPPER(SUBSTR(PRODUCT_NAME, 1, 10)) AS SHORT_NAME,
       LOWER(CATEGORY) AS CATEGORY_LOWER,
       REPLACE(DESCRIPTION, ' ', '_') AS DESC_NO_SPACE,
       TRIM(PRODUCT_NAME) AS TRIMMED_NAME,
       INSTR(PRODUCT_NAME, ' ') AS FIRST_SPACE_POS
FROM PRODUCTS;

-- ROUND, CEIL, FLOOR, MOD, ABS, POWER
SELECT ORDER_ID,
       TOTAL_AMOUNT,
       ROUND(TOTAL_AMOUNT / 1.1, 2) AS NET_AMOUNT,
       CEIL(TOTAL_AMOUNT / 10000) AS CEIL_10K,
       FLOOR(TOTAL_AMOUNT / 10000) AS FLOOR_10K,
       MOD(ORDER_ID, 3) AS MOD_3,
       ABS(TOTAL_AMOUNT - 1000000) AS DIFF_FROM_1M
FROM ORDERS;

-- 날짜 함수: ADD_MONTHS, MONTHS_BETWEEN, LAST_DAY, NEXT_DAY, EXTRACT
SELECT ORDER_ID,
       ORDER_DATE,
       ADD_MONTHS(ORDER_DATE, 3) AS PLUS_3M,
       MONTHS_BETWEEN(SYSDATE, ORDER_DATE) AS MONTHS_AGO,
       LAST_DAY(ORDER_DATE) AS MONTH_END,
       NEXT_DAY(ORDER_DATE, 'MONDAY') AS NEXT_MON,
       EXTRACT(YEAR FROM ORDER_DATE) AS ORD_YEAR,
       EXTRACT(MONTH FROM ORDER_DATE) AS ORD_MONTH
FROM ORDERS;

-- 윈도우 함수: ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD, SUM OVER
SELECT ORDER_ID,
       CUSTOMER_ID,
       TOTAL_AMOUNT,
       ROW_NUMBER() OVER (ORDER BY TOTAL_AMOUNT DESC) AS RN,
       RANK() OVER (ORDER BY TOTAL_AMOUNT DESC) AS RNK,
       DENSE_RANK() OVER (ORDER BY TOTAL_AMOUNT DESC) AS DRNK,
       LAG(TOTAL_AMOUNT) OVER (ORDER BY ORDER_DATE) AS PREV_AMOUNT,
       LEAD(TOTAL_AMOUNT) OVER (ORDER BY ORDER_DATE) AS NEXT_AMOUNT,
       SUM(TOTAL_AMOUNT) OVER (ORDER BY ORDER_DATE ROWS UNBOUNDED PRECEDING) AS RUNNING_TOTAL
FROM ORDERS;

-- LISTAGG (Oracle 특화)
SELECT CUSTOMER_ID,
       LISTAGG(TO_CHAR(ORDER_ID), ', ') WITHIN GROUP (ORDER BY ORDER_DATE) AS ORDER_LIST
FROM ORDERS
GROUP BY CUSTOMER_ID;

PROMPT ============================================================
PROMPT  OMA Workshop 샘플 데이터 생성 완료!
PROMPT  - 테이블: 7개
PROMPT  - 시퀀스: 5개
PROMPT  - 함수: 5개
PROMPT  - 프로시저: 4개
PROMPT  - 패키지: 1개
PROMPT  - 트리거: 2개
PROMPT  - 뷰: 3개
PROMPT  - 동의어: 3개
PROMPT ============================================================

EXIT;
