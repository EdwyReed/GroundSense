"""The default web build must not overwrite the running UI."""
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_default_frontend_build_is_separate_from_the_live_static_root():
    package = json.loads((ROOT / 'apps/web/package.json').read_text())
    commands = package['scripts']['build'].split('&&')
    vite = shlex.split(commands[-1].strip())
    assert vite[:2] == ['vite', 'build']
    assert '--outDir' in vite, 'Default Vite dist is the live static root.'
    target = (ROOT / 'apps/web' / vite[vite.index('--outDir') + 1]).resolve()
    assert target == (ROOT / 'apps/web/dist-stage').resolve()
    assert target != (ROOT / 'apps/web/dist').resolve()


def test_deployment_keeps_old_assets_and_promotes_the_index_after_health():
    script = (ROOT / 'scripts/deploy-prototype.sh').read_text()
    assert 'cp -a apps/web/dist-stage/assets/. apps/web/dist/assets/' in script
    assert 'mv apps/web/dist/.index.html.next apps/web/dist/index.html' in script
    assert script.index('mv apps/web/dist/.index.html.next') > script.index('assert r.status==200')


def test_actual_promotion_commands_preserve_existing_clients_assets(tmp_path):
    live, stage = tmp_path / 'apps/web/dist', tmp_path / 'apps/web/dist-stage'
    (live / 'assets').mkdir(parents=True)
    (stage / 'assets').mkdir(parents=True)
    (live / 'index.html').write_text('synthetic-old-index')
    (live / 'assets/old.js').write_text('synthetic-old-asset')
    (stage / 'index.html').write_text('synthetic-new-index')
    (stage / 'assets/new.js').write_text('synthetic-new-asset')
    expected = ['install -d apps/web/dist/assets', 'cp -a apps/web/dist-stage/assets/. apps/web/dist/assets/', 'install -m 644 apps/web/dist-stage/index.html apps/web/dist/.index.html.next', 'mv apps/web/dist/.index.html.next apps/web/dist/index.html']
    script = (ROOT / 'scripts/deploy-prototype.sh').read_text().splitlines()
    assert all(command in script for command in expected)
    subprocess.run(['bash', '-eu', '-c', '\n'.join(line for line in script if line in expected)], cwd=tmp_path, timeout=10, check=True)
    assert (live / 'index.html').read_text() == 'synthetic-new-index'
    assert (live / 'assets/old.js').read_text() == 'synthetic-old-asset'
    assert (live / 'assets/new.js').read_text() == 'synthetic-new-asset'
