import csv
import json
import uuid
from pathlib import Path

import pytest

from gamepersona.ingest import import_kaggle
from gamepersona.storage import Store


@pytest.fixture
def tmp_path():
    # Python 3.14's mode=0700 tmpdir ACL excludes the Windows sandbox SID.
    # Inherit the workspace ACL instead; generated test data stays under .cache.
    path = Path(".cache/test-runs").resolve() / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "games.csv").write_text("app_id,title\n1,One\n2,Two\n3,Three\n4,Four\n",encoding="utf-8")
    (root / "users.csv").write_text("user_id,products,reviews\n1,4,4\n2,4,4\n3,4,4\n",encoding="utf-8")
    meta = [{"app_id":1,"tags":["Action","Action"," "]},
            {"app_id":2,"tags":[]},{"app_id":3,"tags":["Story"],"type":"dlc"},
            {"app_id":4,"tags":{"bad":1}}]
    (root / "games_metadata.json").write_text("\n".join(json.dumps(r) for r in meta),encoding="utf-8")
    records = [
        [1,1,"r1",60,"2024-01-01","true"],
        [1,1,"r1",60,"2024-01-01","true"],  # exact duplicate
        [2,1,"r2",0,"2024-01-01","false"],
        [3,2,"r3","","2024-01-01","true"],
        [3,3,"r4",-1,"2024-01-01","true"],
        [4,2,"r5","bad","2024-01-01","true"],
        [4,3,"r6","nan","2024-01-01","true"],
        [999,1,"r7",5,"2024-01-01","true"],
        [1,2,"r8",10,"2024-01-01","true"],
        [1,2,"r9",20,"2024-01-02","true"],
    ]
    with (root / "recommendations.csv").open("w",newline="",encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["app_id","user_id","review_id","hours","date","is_recommended"])
        writer.writerows(records)
    return root


@pytest.fixture
def imported(tmp_path,dataset):
    store = Store(tmp_path / "artifacts")
    import_kaggle(store,"kg",dataset,hours_unit="minutes",hours_evidence="fixture spec: minutes",
                  dataset_version="fixture-v1",memory_limit="256MiB",threads=1)
    return store
