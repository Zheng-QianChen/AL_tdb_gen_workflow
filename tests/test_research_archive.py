import json
import pytest
from examples.verify_research_archive import digest, verify
from examples.seven_binary_archive import build


def test_snapshot_detects_modification_and_extra_files(tmp_path):
    raw = tmp_path / 'measurement.json'
    raw.write_text('{"T_K": 1234}', encoding='utf-8')
    manifest = {'files': [{'path': raw.name, 'bytes': raw.stat().st_size, 'sha256': digest(raw)}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert verify(tmp_path)['ok']
    raw.write_text('{"T_K": 1235}', encoding='utf-8')
    assert verify(tmp_path)['errors'][0]['error'] == 'size or SHA256 mismatch'
    (tmp_path / 'untracked.txt').write_text('new evidence')
    assert verify(tmp_path)['unexpected_files'] == ['untracked.txt']


def test_manifest_does_not_follow_paths_outside_snapshot(tmp_path):
    manifest = {'files': [{'path': '../private.json', 'bytes': 0, 'sha256': 'unused'}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    result = verify(tmp_path)
    assert not result['ok']
    assert result['files_checked'] == 0
    assert result['errors'][0]['error'] == 'unsafe path'


def test_archive_never_overwrites_or_recurses_into_input(tmp_path):
    study, target = tmp_path / 'study', tmp_path / 'existing'
    study.mkdir()
    target.mkdir()
    with pytest.raises(FileExistsError):
        build(study, target)
    with pytest.raises(ValueError, match='non-overlapping'):
        build(study, study / 'snapshot')
