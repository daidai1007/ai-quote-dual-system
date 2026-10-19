-- 仅限演练分支 test-quote-scheme-migration-20261019-01 / neondb。
-- SQL 无法用数据库名区分 Neon 分支；必须先人工核对分支选择框。
-- 全文一次运行，保留最后的 ROLLBACK，不得改为 COMMIT。
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TEMP TABLE quote_scheme_number_probe (
    ordinal INTEGER PRIMARY KEY,
    scheme_no TEXT NOT NULL
) ON COMMIT DROP;

DO $$
DECLARE
    i INTEGER;
    generated TEXT;
BEGIN
    FOR i IN 1..3 LOOP
        generated := calc.next_quote_scheme_number();
        IF generated !~ '^BJ-[0-9]{8}-[0-9]{6}$'
           OR substring(generated FROM 4 FOR 8)
              <> to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYYMMDD') THEN
            RAISE EXCEPTION 'FAIL: scheme number format or Shanghai date is incorrect';
        END IF;
        INSERT INTO quote_scheme_number_probe VALUES (i, generated);
    END LOOP;

    IF (SELECT count(DISTINCT scheme_no) FROM quote_scheme_number_probe) <> 3 THEN
        RAISE EXCEPTION 'FAIL: generated scheme numbers are duplicated';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM quote_scheme_number_probe a
        JOIN quote_scheme_number_probe b ON b.ordinal = a.ordinal + 1
        WHERE left(a.scheme_no, 12) = left(b.scheme_no, 12)
          AND right(b.scheme_no, 6)::INTEGER <> right(a.scheme_no, 6)::INTEGER + 1
    ) THEN
        RAISE EXCEPTION 'FAIL: same-day serial numbers are not consecutive';
    END IF;
END;
$$;

SELECT ordinal, scheme_no, 'PASS' AS result
FROM quote_scheme_number_probe
ORDER BY ordinal;

SELECT 'NUMBERING_CHECK_PASS' AS result;
ROLLBACK;
