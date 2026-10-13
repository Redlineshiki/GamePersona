import csv
import json

import httpx

from gamepersona.audit import audit, replay
from gamepersona.collect import Fetcher, fetch_steam, fetch_steamspy, verify_sources
from gamepersona.ingest import import_kaggle
from gamepersona.sampling import select_games
from gamepersona.storage import Store, write_json


def test_complete_synthetic_acceptance_and_account_union(tmp_path):
    """3000-game path is a fixture test, never a claim of real source acceptance."""
    source=tmp_path / "fixture"
    source.mkdir()
    with (source / "games.csv").open("w",encoding="utf-8") as f:
        f.write("app_id,title\n")
        for i in range(1,3006): f.write(f"{i},Fixture {i}\n")
    (source / "users.csv").write_text("user_id\n1\n",encoding="utf-8")
    with (source / "games_metadata.json").open("w",encoding="utf-8") as f:
        for i in range(1,3006):
            f.write(json.dumps({"app_id":i,"tags":[f"Tag {i%5}","Fixture"]})+"\n")
    with (source / "recommendations.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["app_id","user_id","review_id","hours","date","is_recommended"])
        for i in range(1,3006): writer.writerow([i,1,i,1,"2024-01-01",True])
    store=Store(tmp_path / "artifacts")
    import_kaggle(store,"kg",source,hours_unit="hours",hours_evidence="fixture specification",
                  duration_time_semantics="at_collection",time_evidence="fixture specification",
                  dataset_version="synthetic-fixture",memory_limit="256MiB",threads=1)
    def handler(request):
        if request.url.host=="api.steampowered.com":
            return httpx.Response(200,json={"response":{"game_count":1,"games":[{"appid":4001,"playtime_forever":60}]}})
        if request.url.params.get("request")=="appdetails":
            return httpx.Response(200,json={"appid":int(request.url.params["appid"]),"tags":{"Fixture":10}})
        if request.url.host=="www.kaggle.com":
            return httpx.Response(200,json={"licenseName":"CC0: Public Domain","currentVersionNumber":28})
        return httpx.Response(200,text="Fixture source evidence")
    review=tmp_path / "review.json"
    write_json(review,{"steamspy_public_free_use":{"status":"verified","evidence":"fixture only","rationale":"synthetic acceptance scenario"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher=Fetcher(client,sleep=lambda _:None)
        fetch_steam(store,"steam","fixture-key","76561198000000000",fetcher)
        selected=select_games(store,"selection","kg","steam")
        assert selected["base_games"]==3000
        assert selected["total_games"]==3001
        fetch_steamspy(store,"spy","selection",fetcher)
        verify_sources(store,"sources",fetcher,review)
    result=audit(store,"report",kaggle="kg",steam="steam",steamspy="spy",selection="selection",sources="sources")
    assert result["stage_acceptance"]=={"status":"passed","blockers":[]}
    assert result["online"]["steamspy"]["tag_coverage"]["ratio"]==1
    assert result["offline"]["steamspy"]["tag_coverage"]["ratio"]==3000/3005
    assert replay(store,"report")["status"]=="identical"
