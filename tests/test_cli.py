from gamepersona.cli import main


def test_cli_pending_download_does_not_create_snapshot(tmp_path,capsys):
    partial=tmp_path / "archive.zip.crdownload"
    partial.write_bytes(b"pending")
    root=tmp_path / "artifacts"
    assert main(["--root",str(root),"import","--source",str(partial),"--snapshot","pending"])==1
    assert not root.exists()
    assert "下载尚未完成" in capsys.readouterr().err


def test_missing_credentials_no_snapshot(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv("STEAM_API_KEY",raising=False)
    monkeypatch.delenv("STEAM_ID",raising=False)
    root=tmp_path / "artifacts"
    assert main(["--root",str(root),"fetch-steam","--snapshot","account"])==1
    assert not root.exists()
    assert "本地配置" in capsys.readouterr().err
