-- 仅限演练分支 test-quote-scheme-migration-20261019-01 / neondb。
-- SQL 无法用数据库名区分 Neon 分支；必须先人工核对分支选择框。
-- 全文一次运行，保留最后的 ROLLBACK，不得改为 COMMIT。
-- 本脚本仅构造数据库约束用例，不代表 API 的合法状态流转或已认证身份。
-- 测试记录和编号计数的修改最终回滚；BIGSERIAL 内部 ID 可能留下空号。
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TEMP TABLE quote_scheme_guard_probe (
    check_name TEXT PRIMARY KEY,
    result TEXT NOT NULL
) ON COMMIT DROP;

DO $$
DECLARE
    test_id BIGINT;
    test_no TEXT;
    field_name TEXT;
    replacement TEXT;
    rejected BOOLEAN;
    constraint_name TEXT;
    test_status TEXT;
    test_used BOOLEAN;
    affected INTEGER;
    original_row JSONB;
BEGIN
    test_no := calc.next_quote_scheme_number();
    INSERT INTO calc.quote_scheme (
        scheme_no, company_name,
        creator_user_id, creator_name_snapshot, creator_name_entered,
        last_editor_user_id, last_editor_name_snapshot
    ) VALUES (
        test_no, '仅供演练：最终回滚',
        'manual-quote-scheme-rehearsal', '演练身份快照', '演练操作人',
        'manual-quote-scheme-rehearsal', '演练操作人'
    ) RETURNING scheme_id INTO test_id;

    -- 必须是方案编号唯一约束拒绝，其他错误不能算测试通过。
    rejected := FALSE;
    BEGIN
        INSERT INTO calc.quote_scheme (
            scheme_no, creator_user_id, creator_name_snapshot, creator_name_entered,
            last_editor_user_id, last_editor_name_snapshot
        ) VALUES (test_no, 'duplicate-probe', '重复编号测试', '重复编号测试',
                  'duplicate-probe', '重复编号测试');
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS constraint_name = CONSTRAINT_NAME;
        IF constraint_name <> 'quote_scheme_scheme_no_key' THEN
            RAISE;
        END IF;
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: duplicate scheme number was accepted';
    END IF;
    INSERT INTO quote_scheme_guard_probe VALUES ('01 方案编号唯一', 'PASS');

    SELECT to_jsonb(s) INTO original_row
    FROM calc.quote_scheme s WHERE scheme_id = test_id;

    FOR field_name, replacement IN
        SELECT * FROM (VALUES
            ('creator_user_id', 'changed-user'),
            ('creator_name_snapshot', '被修改的身份快照'),
            ('creator_name_entered', '被修改的创建人姓名'),
            ('creator_identity_mode', 'AUTHENTICATED'),
            ('creator_department_id', 'changed-department'),
            ('created_at', '2000-01-01 00:00:00+00'),
            ('scheme_no', 'BJ-19000101-999999')
        ) AS changes(column_name, new_value)
    LOOP
        rejected := FALSE;
        BEGIN
            EXECUTE format('UPDATE calc.quote_scheme SET %I = %L WHERE scheme_id = %L',
                           field_name, replacement, test_id);
        EXCEPTION WHEN raise_exception THEN
            IF SQLERRM <> 'quote scheme creator and number are immutable' THEN
                RAISE;
            END IF;
            rejected := TRUE;
        END;
        IF NOT rejected THEN
            RAISE EXCEPTION 'FAIL: immutable field % was changed', field_name;
        END IF;
        IF (SELECT to_jsonb(s) FROM calc.quote_scheme s WHERE scheme_id = test_id)
           IS DISTINCT FROM original_row THEN
            RAISE EXCEPTION 'FAIL: rejected update changed the original row';
        END IF;
        INSERT INTO quote_scheme_guard_probe
        VALUES ('02 禁止修改 ' || field_name, 'PASS');
    END LOOP;

    UPDATE calc.quote_scheme
    SET last_editor_user_id = 'another-rehearsal-editor',
        last_editor_name_snapshot = '后续修改人'
    WHERE scheme_id = test_id;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'FAIL: last-editor update did not update exactly one row';
    END IF;
    INSERT INTO quote_scheme_guard_probe VALUES ('03 允许更新最后修改人', 'PASS');

    -- 直接设置状态仅为构造用例，不是正式业务操作示例。
    -- 非草稿在导出标记为 FALSE 时也必须禁止删除。
    FOR test_status, test_used IN
        SELECT * FROM (VALUES
            ('QUOTED', FALSE), ('ARCHIVED', FALSE), ('VOID', FALSE),
            ('REVISING', FALSE), ('DRAFT', TRUE)
        ) AS cases(status_name, has_export)
    LOOP
        UPDATE calc.quote_scheme
        SET status = test_status, has_successful_export = test_used
        WHERE scheme_id = test_id;
        rejected := FALSE;
        BEGIN
            DELETE FROM calc.quote_scheme WHERE scheme_id = test_id;
        EXCEPTION WHEN raise_exception THEN
            IF SQLERRM <> 'only an unused draft quote scheme can be deleted' THEN
                RAISE;
            END IF;
            rejected := TRUE;
        END;
        IF NOT rejected OR NOT EXISTS (
            SELECT 1 FROM calc.quote_scheme WHERE scheme_id = test_id
        ) THEN
            RAISE EXCEPTION 'FAIL: protected record % / % was deleted', test_status, test_used;
        END IF;
        INSERT INTO quote_scheme_guard_probe
        VALUES ('04 禁止删除 ' || test_status || ' / exported=' || test_used::TEXT, 'PASS');
    END LOOP;

    UPDATE calc.quote_scheme SET status = 'DRAFT', has_successful_export = FALSE
    WHERE scheme_id = test_id;
    DELETE FROM calc.quote_scheme WHERE scheme_id = test_id;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 OR EXISTS (
        SELECT 1 FROM calc.quote_scheme WHERE scheme_id = test_id
    ) THEN
        RAISE EXCEPTION 'FAIL: unused draft could not be deleted';
    END IF;
    INSERT INTO quote_scheme_guard_probe VALUES ('05 未使用草稿允许删除', 'PASS');

    IF (SELECT count(*) FROM quote_scheme_guard_probe) <> 15 THEN
        RAISE EXCEPTION 'FAIL: expected 15 completed checks';
    END IF;
END;
$$;

SELECT check_name, result FROM quote_scheme_guard_probe ORDER BY check_name;
SELECT 'PROTECTION_CHECK_PASS' AS result, count(*) AS passed_checks
FROM quote_scheme_guard_probe WHERE result = 'PASS';
ROLLBACK;

-- 在回滚后检查测试主记录是否有残留；新演练库预期为 0。
SELECT count(*) AS remaining_rehearsal_rows
FROM calc.quote_scheme
WHERE creator_user_id = 'manual-quote-scheme-rehearsal';
