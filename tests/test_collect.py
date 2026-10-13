import json

import httpx
import pytest

from gamepersona.collect import Fetcher, classify_steam, classify_tags, fetch_steam, fetch_steamspy, normalize_steam
from gamepersona.storage import Store, read_json, write_json


def client_for(payload,status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json=payload)))


@pytest.mark.parametrize("payload,state",[
    ({},"insufficient_response"),({"response":{}},"insufficient_response"),
    ({"response":{"game_count":0}},"explicit_empty"),
    ({"response":{"game_count":1,"games":[]}},"insufficient_response"),
    ({"response":{"game_count":True}},"insufficient_response"),
    ({"response":{"game_count":1,"games":[{"appid":1}]}},"success"),
])
def test_steam_response_states(payload,state):
    assert classify_steam(payload)[0]==state


def test_normalize_steam_duration_and_duplicates():
    records = normalize_steam([{"appid":1,"playtime_forever":120}]*2 +
        [{"appid":2,"playtime_forever":0},{"appid":3},{"appid":4,"playtime_forever":-1},
         {"appid":5,"playtime_forever":10},{"appid":5,"playtime_forever":20}],"one")
    assert len(records)==5
    assert records[0]["duration_hours"]==2
    assert records[1]["duration_state"]=="zero"
    assert records[2]["duration_state"]=="unknown"
    assert records[3]["exclusion_reason"]=="duration_negative"
    assert records[4]["exclusion_reason"]=="conflicting_user_game"


@pytest.mark.parametrize("code,state",[(401,"credential_or_access_error"),(403,"credential_or_access_error"),
                                          (429,"rate_limited"),(503,"service_failure")])
def test_http_states(code,state):
    with client_for({},code) as client:
        result = Fetcher(client,retries=0,sleep=lambda _:None).get("https://example.test")
    assert result["status"]==state


@pytest.mark.parametrize("error,state",[(httpx.ReadTimeout,"timeout"),(httpx.ConnectError,"network_failure")])
def test_network_states(error,state):
    def fail(request):
        raise error("secret=request-url",request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        result = Fetcher(client,retries=0).get("https://example.test",{"key":"secret"})
    assert result["status"]==state
    assert "secret" not in json.dumps(result)


def test_retry_limiter_and_retry_after():
    now, starts = [0.0], []
    def sleep(seconds): now[0]+=seconds
    def handler(request):
        starts.append(now[0])
        return httpx.Response(429,headers={"Retry-After":"3"}) if len(starts)==1 else httpx.Response(200,json={})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher=Fetcher(client,sleep=sleep,clock=lambda:now[0])
        assert fetcher.get("https://example.test")["attempts"]==2
        fetcher.get("https://example.test")
    assert starts[1]-starts[0]>=3
    assert starts[2]-starts[1]>=1.0  # official maximum: one ordinary request per second


def test_real_request_parameters_and_no_credential_persistence(tmp_path):
    def handler(request):
        assert request.url.host=="api.steampowered.com"
        assert request.url.params["include_played_free_games"]=="1"
        assert request.url.params["key"]=="sensitive-key"
        return httpx.Response(200,json={"response":{"game_count":1,"games":[{"appid":1,"playtime_forever":60}]}})
    store=Store(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=fetch_steam(store,"account","sensitive-key","76561198000000000",Fetcher(client))
    assert result["read_status"]=="success"
    for p in store.path("account").glob("*.json"):
        assert "sensitive-key" not in p.read_text()
        assert "76561198000000000" not in p.read_text()


@pytest.mark.parametrize("payload,state",[
    ({"appid":999999},"hidden"),({"appid":1,"tags":{}},"no_tags"),
    ({"appid":1,"tags":["Action"]},"invalid_tag_format"),
    ({"appid":1,"tags":{"Action":-1}},"invalid_tag_format"),
    ({"appid":1,"tags":{"Action":0}},"no_positive_votes"),
    ({"appid":1,"tags":{"Action":12}},"available"),({"appid":2},"unmatched_app")])
def test_tag_states(payload,state):
    assert classify_tags(payload,1)[0]==state


def test_resume_and_cross_snapshot_cache(tmp_path):
    store=Store(tmp_path)
    path,manifest=store.create("selection","selection",{})
    write_json(path / "candidates.json",[{"app_id":1},{"app_id":2}])
    store.finish(path,manifest)
    requests=[]
    def handler(request):
        app_id=int(request.url.params["appid"]);requests.append(app_id)
        return httpx.Response(200,json={"appid":app_id,"tags":{"Action":4}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher=Fetcher(client,sleep=lambda _:None)
        partial=fetch_steamspy(store,"spy","selection",fetcher,max_games=1)
        assert partial["uncollected_games"]==1
        assert read_json(store.path("spy") / "tags.json")[1]["status"]=="not_collected"
        complete=fetch_steamspy(store,"spy","selection",fetcher)
        assert complete["state"]=="ready"
        fetch_steamspy(store,"spy2","selection",fetcher)
    assert requests==[1,2]
