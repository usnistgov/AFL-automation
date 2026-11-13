from pathlib import Path

import yaml


DEPLOY_DIR = Path(__file__).parents[1] / "deploy" / "synology-tiled"


def test_synology_tiled_is_private_and_persistent():
    compose = yaml.safe_load((DEPLOY_DIR / "compose.yaml").read_text())
    service = compose["services"]["tiled"]

    assert service["ports"] == [
        "${TILED_BIND_ADDRESS:-127.0.0.1}:${TILED_PORT:-8000}:8000"
    ]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["secrets"] == ["tiled_api_key"]

    targets = {volume["target"] for volume in service["volumes"]}
    assert targets == {"/catalog", "/data"}


def test_synology_tiled_config_requires_auth_and_supports_afl_writes():
    config = yaml.safe_load((DEPLOY_DIR / "config.yml.template").read_text())
    authentication = config["authentication"]

    assert authentication["allow_anonymous_access"] is False
    assert "single_user_api_key" not in authentication
    assert set(authentication["single_user_api_key_scopes"]) >= {
        "read:metadata",
        "read:data",
        "create",
        "write:metadata",
        "write:data",
    }

    catalog = config["trees"][0]["args"]
    assert catalog["uri"] == "sqlite+aiosqlite:////catalog/catalog.db"
    assert catalog["writable_storage"] == "/data/"


def test_synology_tiled_does_not_contain_a_deployed_secret():
    for path in DEPLOY_DIR.iterdir():
        if path.is_file():
            assert "devkey" not in path.read_text()


def test_synology_tiled_uses_the_supported_api_key_header():
    compose = (DEPLOY_DIR / "compose.yaml").read_text()
    entrypoint = (DEPLOY_DIR / "entrypoint.sh").read_text()

    assert "Authorization':'Apikey '" in compose
    assert "X-Tiled-Api-Key" not in compose
    assert 'export TILED_SINGLE_USER_API_KEY="$api_key"' in entrypoint
