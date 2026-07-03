"""
数据库管理器测试用例
=====================
测试内容：
  1. 基本 CRUD 操作
  2. 唯一约束 + 去重策略（UPSERT）
  3. 批量插入部分失败处理
  4. 多线程并发写入
  5. 多线程并发读写
  6. CSV 加载
  7. 统计数据

运行：
    cd movie_analysis_system
    python tests/test_db_manager.py

注意：
    测试使用独立的数据库文件 data/test_db.db，不污染主数据库。
"""

import sys
import os
import threading
import time

# 将项目根目录加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database.db_manager import DatabaseManager, DatabaseError


# ──────────────────────────── 测试辅助 ────────────────────────────

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "data", "test_db.db")


def get_test_db() -> DatabaseManager:
    """获取测试用的 DatabaseManager 实例（使用独立数据库）。"""
    return DatabaseManager(TEST_DB)


def clean_test_db() -> None:
    """删除测试数据库文件，保证每次测试从干净状态开始。"""
    db = get_test_db()
    db.close()
    # 需要重置单例状态
    DatabaseManager._instance = None
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    # 删除 WAL 和 SHM 文件
    for ext in ("-wal", "-shm"):
        path = TEST_DB + ext
        if os.path.exists(path):
            os.remove(path)


# ──────────────────────────── 测试 1：基本 CRUD ────────────────────────────

def test_basic_crud() -> None:
    """测试插入、查询、更新（去重）功能。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    # 插入一条
    movie_id = db.insert_movie({
        "title": "测试电影A",
        "genre": "剧情",
        "rating": 8.0,
        "box_office": 5000,
        "ticket_price": 35,
        "director": "测试导演",
        "actors": "演员1;演员2",
    })
    assert movie_id > 0, "插入应返回正数 ID"

    # 查询
    total, records = db.query_movies()
    assert total == 1, f"预期 1 条，实际 {total}"

    # UPSERT 去重：同 title 更新而不是插入新记录
    movie_id2 = db.insert_movie({
        "title": "测试电影A",
        "genre": "剧情/喜剧",
        "rating": 8.5,
    })
    assert movie_id == movie_id2, f"去重失败：ID 不一致 {movie_id} vs {movie_id2}"

    # 验证数据已更新
    total, records = db.query_movies(keyword="测试电影A")
    assert len(records) == 1, f"去重后不应有重复记录"
    assert records[0]["rating"] == 8.5, f"评分应更新为 8.5，实际 {records[0]['rating']}"
    assert records[0]["genre"] == "剧情/喜剧", f"genre 应更新"

    # 票房 top 10
    top = db.get_top10_box_office()
    assert len(top) == 1
    assert top[0]["title"] == "测试电影A"

    # 统计数据
    stats = db.get_statistics()
    assert stats["total_movies"] == 1

    print("[PASS] test_basic_crud")


# ──────────────────────────── 测试 2：批量插入 ────────────────────────────

def test_batch_insert() -> None:
    """测试批量插入和部分失败场景。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    movies = [
        {"title": f"批量电影-{i}", "genre": "科幻", "rating": 7.0 + i * 0.1}
        for i in range(10)
    ]

    result = db.insert_movies_batch(movies)
    assert result["success"] == 10, f"预期 10 条成功，实际 {result['success']}"
    assert result["fail"] == 0

    # 验证
    total, _ = db.query_movies()
    assert total == 10, f"数据库中应有 10 条"

    # 带一条非法数据的批量插入
    bad_movies = [
        {"title": "正常电影", "genre": "喜剧"},
        {"title": None, "genre": "动作"},  # title 不能为 NULL
    ]
    result2 = db.insert_movies_batch(bad_movies)
    assert result2["success"] >= 1  # title NOT NULL 约束可能会让第2条失败
    # 但数据库里已经有 "正常电影"
    total2, _ = db.query_movies(keyword="正常电影")
    assert total2 == 1, f"正常电影应已插入"

    print("[PASS] test_batch_insert")


# ──────────────────────────── 测试 3：并发写入 ────────────────────────────

def test_concurrent_writes() -> None:
    """多线程并发写入测试：20 个线程同时写入，验证数据完整性和锁安全。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        """单个写入线程。"""
        try:
            movie_id = db.insert_movie({
                "title": f"并发写入-{index:03d}",
                "genre": "测试",
                "rating": round(5.0 + (index % 5), 1),
                "box_office": 1000 + index * 10,
            })
            with lock:
                results.append((index, movie_id))
        except Exception as e:
            with lock:
                errors.append((index, str(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"并发写入发现错误: {errors}"
    assert len(results) == 20

    # 验证所有 20 条数据都在库里
    total, _ = db.query_movies(keyword="并发写入")
    assert total == 20, f"预期 20 条，实际 {total}"

    # 清理
    conn = db.get_connection()
    conn.execute("DELETE FROM movies WHERE genre = '测试'")
    conn.commit()

    print("[PASS] test_concurrent_writes")


# ──────────────────────────── 测试 4：并发读写 ────────────────────────────

def test_concurrent_read_write() -> None:
    """多线程并发读写测试：3 个读线程 + 2 个写线程同时运行，验证不崩溃。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    # 预填一些数据供读取
    for i in range(50):
        db.insert_movie({
            "title": f"基准数据-{i:03d}",
            "genre": "剧情",
            "rating": 7.0,
            "box_office": 1000 * (i + 1),
        })

    reader_errors: list = []
    writer_errors: list = []
    error_lock = threading.Lock()

    def reader() -> None:
        """读线程：反复执行各种查询。"""
        try:
            for _ in range(30):
                db.query_movies(limit=20)
                db.get_statistics()
                db.get_top10_box_office()
                db.get_genre_stats()
                db.get_data_status()
                time.sleep(0.005)
        except Exception as e:
            import traceback
            with error_lock:
                reader_errors.append(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    def writer() -> None:
        """写线程：反复插入数据。"""
        try:
            for i in range(15):
                db.insert_movie({
                    "title": f"读写并发-{threading.get_ident()}-{i}",
                    "genre": "测试",
                    "rating": 7.5,
                })
                time.sleep(0.01)
        except Exception as e:
            import traceback
            with error_lock:
                writer_errors.append(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    threads = [threading.Thread(target=reader) for _ in range(3)]
    threads += [threading.Thread(target=writer) for _ in range(2)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(reader_errors) == 0, f"读线程错误: {reader_errors}"
    assert len(writer_errors) == 0, f"写线程错误: {writer_errors}"

    # 清理
    conn = db.get_connection()
    conn.execute("DELETE FROM movies WHERE genre = '测试'")
    conn.commit()

    print("[PASS] test_concurrent_read_write")


# ──────────────────────────── 测试 5：去重可靠性 ────────────────────────────

def test_upsert_dedup_reliability() -> None:
    """验证去重策略的可靠性：同 douban_id 和同 title 各自的去重效果。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    title = f"去重验证-{time.time_ns()}"

    # 通过 title 去重
    id1 = db.insert_movie({"title": title, "genre": "剧情", "rating": 8.0})
    id2 = db.insert_movie({"title": title, "genre": "剧情/喜剧", "rating": 8.5})
    assert id1 == id2, f"title 去重失败: {id1} vs {id2}"

    # 验证数据更新了
    _, records = db.query_movies(keyword=title)
    assert records[0]["rating"] == 8.5

    # 通过 douban_id 去重
    db_id = "TEST_DB_001"
    id3 = db.insert_movie({
        "title": "重复ID电影",
        "genre": "动作",
        "douban_id": db_id,
        "rating": 7.0,
    })
    id4 = db.insert_movie({
        "title": "重复ID电影-新名",
        "genre": "动作/冒险",
        "douban_id": db_id,
        "rating": 7.5,
    })
    assert id3 == id4, f"douban_id 去重失败: {id3} vs {id4}"

    # 清理
    conn = db.get_connection()
    conn.execute("DELETE FROM movies WHERE douban_id = 'TEST_DB_001'")
    conn.execute(f"DELETE FROM movies WHERE title = '{title}'")
    conn.commit()

    print("[PASS] test_upsert_dedup_reliability")


# ──────────────────────────── 测试 6：CSV 加载 ────────────────────────────

def test_csv_loading() -> None:
    """测试从 CSV 文件加载数据到数据库。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    csv_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "backup_movies.csv"
    )
    assert os.path.exists(csv_path), f"CSV 文件不存在: {csv_path}"

    count = db.load_csv_to_db(csv_path)
    assert count >= 50, f"预期至少加载 50 条，实际 {count}"

    # 验证数据可用
    stats = db.get_statistics()
    assert stats["total_movies"] >= 50

    top = db.get_top10_box_office()
    assert len(top) == 10

    genre_stats = db.get_genre_stats()
    assert len(genre_stats) > 0

    print(f"[PASS] test_csv_loading ({count} 条)")


# ──────────────────────────── 测试 7：空表状态 ────────────────────────────

def test_empty_state() -> None:
    """空数据库状态下，所有查询应正常返回而非崩溃。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    # 空表查询
    stats = db.get_statistics()
    assert stats["total_movies"] == 0
    assert stats["highest_rated"] == "无数据"

    top = db.get_top10_box_office()
    assert top == []

    genre = db.get_genre_stats()
    assert genre == []

    status = db.get_data_status()
    assert status["has_data"] is False

    print("[PASS] test_empty_state")


# ──────────────────────────── 测试 8：数据库迁移 ────────────────────────────

def test_migration() -> None:
    """测试数据库迁移接口（当前版本 1.0，不执行实际迁移）。"""
    clean_test_db()
    db = get_test_db()
    db.init_db()

    # 迁移应正常运行（v1.0 无迁移项）
    db.check_and_migrate()

    # 验证版本号仍为 1.0
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_config WHERE key = 'db_version'")
    row = cursor.fetchone()
    assert row is not None, "system_config 中应有 db_version"
    version = row["value"]
    # v1.0 无迁移项，版本不应被提升
    assert version == "1.0", f"预期版本 1.0，实际 {repr(version)}"
    cursor.close()

    print("[PASS] test_migration")


# ──────────────────────────── 运行 ────────────────────────────

def run_all_tests() -> None:
    """运行所有测试用例。"""
    tests = [
        ("空表状态", test_empty_state),
        ("基本 CRUD", test_basic_crud),
        ("去重可靠性", test_upsert_dedup_reliability),
        ("批量插入", test_batch_insert),
        ("CSV 加载", test_csv_loading),
        ("数据库迁移", test_migration),
        ("并发写入", test_concurrent_writes),
        ("并发读写", test_concurrent_read_write),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {name}: 断言失败 - {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 40}")
    print(f"测试完成: {passed} 通过, {failed} 失败")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    # 如果指定了环境变量 DB_PATH，使用指定的路径
    db_path = os.environ.get("DB_PATH", TEST_DB)
    TEST_DB = db_path
    run_all_tests()
