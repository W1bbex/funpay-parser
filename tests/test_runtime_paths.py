import asyncio

import parser


def test_mass_parse_uses_project_queue_from_another_working_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "queue.txt").write_text("123:1\n", encoding="utf-8")
    monkeypatch.setattr(parser, "BASE_DIR", str(project))
    monkeypatch.chdir(outside)

    asyncio.run(parser.mass_parse({"123": {"status": "completed"}}, {}))

    assert (project / "queue.txt").read_text(encoding="utf-8").strip() == "123:1"
    assert not (outside / "queue.txt").exists()
