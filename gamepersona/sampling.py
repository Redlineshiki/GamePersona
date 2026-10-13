from __future__ import annotations

from .database import connect, export, rows
from .storage import Store, read_json, write_json


def select_games(store: Store, snapshot: str, kaggle: str, steam: str | None = None,
                 seed: str = "gamepersona-stage1-v1", top: int = 1500, stratified: int = 1500) -> dict:
    if top < 0 or stratified < 0:
        raise ValueError("选样数量不得为负")
    store.load(kaggle, "kaggle")
    if steam:
        store.load(steam, "steam")
    path, manifest = store.create(snapshot, "selection", {
        "kaggle_snapshot": kaggle, "steam_snapshot": steam, "seed": seed,
        "top_target": top, "stratified_target": stratified,
        "popularity": "distinct observed review users per matched AppID",
        "stratification": "5 popularity tiers, first sorted metadata tag, tag sparsity; equal round-robin",
        "ordering": "md5 of seed and AppID; no Python randomized hash"})
    con = connect(store.path(kaggle) / "audit.duckdb", read_only=True)
    try:
        # Temp tables do not alter the fixed imported database.
        con.execute("""CREATE TEMP TABLE population AS
          WITH popularity AS (SELECT app_id,count(DISTINCT user_key) review_users FROM records
            WHERE app_id>0 AND game_matched AND user_matched GROUP BY app_id)
          SELECT g.app_id, p.review_users, coalesce(m.tags, []::VARCHAR[]) tags,
            coalesce(m.tags[1], 'unknown') primary_tag,
            CASE WHEN coalesce(len(m.tags),0)=0 THEN 'none'
                 WHEN len(m.tags)<=2 THEN 'sparse' ELSE 'rich' END sparsity
          FROM games g JOIN popularity p ON g.app_id=p.app_id
          LEFT JOIN metadata m ON g.app_id=m.app_id;
          CREATE TEMP TABLE popular AS SELECT * FROM population
            ORDER BY review_users DESC, app_id LIMIT ?;
          """, [top])
        con.execute("""CREATE TEMP TABLE remaining AS
          SELECT *, ntile(5) OVER (ORDER BY review_users,app_id) popularity_tier
          FROM population WHERE app_id NOT IN (SELECT app_id FROM popular)""")
        con.execute("""CREATE TEMP TABLE stratified AS
          WITH ranked AS (SELECT *,
            row_number() OVER (PARTITION BY popularity_tier,primary_tag,sparsity
              ORDER BY md5(? || ':' || app_id::VARCHAR), app_id) ordinal,
            md5(? || ':' || popularity_tier::VARCHAR || ':' || primary_tag || ':' || sparsity) stratum_order
            FROM remaining)
          SELECT * FROM ranked ORDER BY ordinal,stratum_order,app_id LIMIT ?""", [seed, seed, stratified])
        candidates = {}
        for record in rows(con, "SELECT app_id,review_users,tags,primary_tag,sparsity FROM popular ORDER BY app_id"):
            candidates[record["app_id"]] = {**record, "reasons": ["top_review_users"]}
        for record in rows(con, "SELECT app_id,review_users,tags,primary_tag,sparsity,popularity_tier FROM stratified ORDER BY app_id"):
            candidates[record["app_id"]] = {**record, "reasons": ["stratified"]}
        base_count = len(candidates)
        account_count = 0
        if steam:
            for record in read_json(store.path(steam) / "records.json"):
                app_id = record["app_id"]
                if app_id is None:
                    continue
                account_count += 1
                if app_id not in candidates:
                    candidates[app_id] = {"app_id": app_id, "review_users": None, "tags": [],
                                          "primary_tag": "unknown", "sparsity": "unknown", "reasons": []}
                candidates[app_id]["reasons"].append("authorized_account")
        output = [candidates[key] for key in sorted(candidates)]
        write_json(path / "candidates.json", output)
        # Durable machine-readable selection, without account identifiers.
        con.execute("CREATE TEMP TABLE selected_ids(app_id BIGINT, reasons VARCHAR[])")
        if output:
            con.executemany("INSERT INTO selected_ids VALUES (?,?)", [(r["app_id"], r["reasons"]) for r in output])
        export(con, "selected_ids", path / "candidates.parquet")
        store.finish(path, manifest, base_games=base_count, account_games=account_count,
                     total_games=len(output), available_population=con.execute("SELECT count(*) FROM population").fetchone()[0])
        return manifest
    finally:
        con.close()
