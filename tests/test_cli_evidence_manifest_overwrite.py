

def test_inspect_evidence_cli_refuses_to_overwrite_source_manifest(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest_path = tmp_path / "manifest.json"
    original = json.dumps(_manifest())
    manifest_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-workflow-assurance",
            "inspect-evidence",
            "--manifest",
            str(manifest_path),
            "--output",
            str(manifest_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "must differ from the source manifest" in capsys.readouterr().err
    assert manifest_path.read_text(encoding="utf-8") == original
