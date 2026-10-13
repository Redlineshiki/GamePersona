from pathlib import Path

import duckdb


def connect(path: Path | str, memory_limit: str = "2GiB", threads: int = 4,
            read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if threads < 1:
        raise ValueError("线程数必须为正整数")
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("SET memory_limit = ?", [memory_limit])
    con.execute("SET threads = ?", [threads])
    if not read_only:
        con.execute("SET preserve_insertion_order = false")
        if str(path) != ":memory:":
            con.execute("SET temp_directory = ?", [str(Path(path).parent / "spill")])
    return con


def literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    result = con.execute(sql)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def export(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    con.execute(f"COPY (SELECT * FROM {table}) TO {literal(path)} (FORMAT PARQUET, COMPRESSION ZSTD)")
