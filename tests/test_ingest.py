import zipfile

import pytest

from gamepersona.database import connect
from gamepersona.ingest import import_kaggle, validate_source
from gamepersona.storage import Store, read_json, sha256


def test_cleaning_and_units(imported):
    manifest = imported.load("kg")
    q = manifest["quality"]
    assert q["csv"]["recommendations"]["parsed_rows"]==10
    assert q["exact_duplicate_rows_removed"]["recommendations"]==1
    assert q["normalized_records"]==9
    assert q["clean_records"]==2
    assert q["quarantined_records"]==7
    assert q["conflicting_user_game_pairs"]==1
    con = connect(imported.path("kg") / "audit.duckdb",read_only=True)
    try:
        records = con.execute("SELECT app_id,duration_hours,is_recommended FROM clean_records ORDER BY app_id").fetchall()
        assert records==[(1,1.0,True),(2,0.0,False)]
        reasons = dict(con.execute("SELECT exclusion_reason,count(*) FROM quarantine GROUP BY 1").fetchall())
        assert reasons=={"duration_unknown":1,"duration_negative":1,"duration_invalid_type":1,
                         "duration_non_finite":1,"unmatched_game":1,"conflicting_user_game":2}
        assert con.execute("SELECT user_key FROM clean_records LIMIT 1").fetchone()[0]=="kaggle:1"
        assert con.execute("SELECT tags FROM metadata WHERE app_id=1").fetchone()[0]==["Action"]
        assert con.execute("SELECT product_kind FROM metadata WHERE app_id=3").fetchone()[0]=="dlc"
        assert con.execute("SELECT product_kind FROM games WHERE app_id=1").fetchone()[0]=="unknown"
    finally:
        con.close()


def test_unknown_units_do_not_produce_hours(tmp_path,dataset):
    store = Store(tmp_path / "data")
    import_kaggle(store,"unverified",dataset)
    con = connect(store.path("unverified") / "audit.duckdb",read_only=True)
    assert con.execute("SELECT count(duration_hours) FROM records").fetchone()[0]==0
    con.close()


@pytest.mark.parametrize("name",["archive.zip.crdownload","archive.part","broken.zip"])
def test_incomplete_or_broken_input_rejected(tmp_path,name):
    source = tmp_path / name
    source.write_bytes(b"partial")
    with pytest.raises(ValueError):
        validate_source(source)


def test_zip_import_and_path_safety(tmp_path,dataset):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good,"w",zipfile.ZIP_DEFLATED) as z:
        for p in dataset.iterdir():
            z.write(p,"folder/"+p.name)
    store = Store(tmp_path / "data")
    result = import_kaggle(store,"zip",good)
    assert len(result["files"])==4
    assert result["input_sha256"]==sha256(good)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad,"w") as z:
        z.writestr("../games.csv","bad")
    with pytest.raises(ValueError,match="不安全"):
        validate_source(bad)


def test_crc_damage_rejected(tmp_path,dataset):
    source = tmp_path / "bad-crc.zip"
    with zipfile.ZipFile(source,"w",zipfile.ZIP_STORED) as z:
        for p in dataset.iterdir():
            z.write(p,p.name)
    content = source.read_bytes().replace(b"One",b"Uno",1)
    source.write_bytes(content)
    with pytest.raises((ValueError,zipfile.BadZipFile)):
        validate_source(source)


def test_missing_column_marks_import_failed(tmp_path,dataset):
    (dataset / "recommendations.csv").write_text("app_id,user_id\n1,1\n",encoding="utf-8")
    store = Store(tmp_path / "data")
    with pytest.raises(ValueError,match="缺少字段"):
        import_kaggle(store,"missing",dataset)
    assert read_json(store.path("missing") / "manifest.json")["state"]=="failed"


def test_csv_and_metadata_bad_lines_are_preserved(tmp_path,dataset):
    with (dataset / "recommendations.csv").open("a",encoding="utf-8") as f:
        f.write("2,3,short\n")
    with (dataset / "games_metadata.json").open("a",encoding="utf-8") as f:
        f.write("\nnot-json\n")
    store = Store(tmp_path / "data")
    result = import_kaggle(store,"rejects",dataset)
    assert result["quality"]["csv"]["recommendations"]["rejected_rows"]==1
    assert result["quality"]["metadata"]["rejected_lines"]==1


def test_evidence_required(tmp_path,dataset):
    with pytest.raises(ValueError,match="hours-evidence"):
        import_kaggle(Store(tmp_path / "data"),"bad",dataset,hours_unit="hours")


def test_snapshot_immutable(imported,dataset):
    with pytest.raises(ValueError,match="已存在"):
        import_kaggle(imported,"kg",dataset)


def test_snapshot_id_cannot_escape(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path).path("../outside")


def test_fractional_ids_dates_booleans_and_duplicate_review_ids(tmp_path,dataset):
    (dataset / "recommendations.csv").write_text(
        "app_id,user_id,review_id,hours,date,is_recommended\n"
        "1.5,1,a,1,2024-01-01,true\n"
        "1,2,b,1,not-date,true\n"
        "2,2,c,1,2024-01-01,not-bool\n"
        "3,1,shared,1,2024-01-01,true\n"
        "4,1,shared,1,2024-01-01,true\n"
        "1,missing,d,1,2024-01-01,true\n",encoding="utf-8")
    store=Store(tmp_path / "artifacts")
    result=import_kaggle(store,"kg",dataset)
    reasons={r["reason"]:r["records"] for r in result["quality"]["exclusion_reasons"]}
    assert reasons=={"invalid_app_id":1,"invalid_review_date":1,"invalid_recommendation":1,
                     "conflicting_review_id":2,"unmatched_user":1}
