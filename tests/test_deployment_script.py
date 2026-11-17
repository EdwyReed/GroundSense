from pathlib import Path


def test_repeat_deployment_explicitly_restarts_existing_backend():
    """Enabling an already-active unit does not load updated Python code."""
    script = (Path(__file__).parents[1] / 'scripts/deploy-prototype.sh').read_text()
    lines = [line.strip() for line in script.splitlines() if not line.lstrip().startswith('#')]
    assert 'systemctl --user restart groundsense.service' in lines
    assert lines.index('systemctl --user restart groundsense.service') < lines.index("python3 -c '")
