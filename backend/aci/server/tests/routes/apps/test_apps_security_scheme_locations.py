from fastapi import status
from fastapi.testclient import TestClient

from aci.common.db.sql_models import App
from aci.common.schemas.app import AppDetails, AppSecuritySchemeLocations
from aci.server import config


def test_security_scheme_locations_returns_placement_metadata(
    test_client: TestClient,
    dummy_api_key_1: str,
    dummy_app_github: App,
) -> None:
    response = test_client.get(
        f"{config.ROUTER_PREFIX_APPS}/security-scheme-locations",
        params={"app_names": [dummy_app_github.name]},
        headers={"x-api-key": dummy_api_key_1},
    )
    assert response.status_code == status.HTTP_200_OK

    results = [AppSecuritySchemeLocations.model_validate(item) for item in response.json()]
    assert len(results) == 1
    locations = results[0].security_scheme_locations

    assert locations.api_key.location == "header"
    assert locations.api_key.name == "X-API-Key"
    assert locations.api_key.prefix is None

    assert locations.oauth2.location == "header"
    assert locations.oauth2.name == "Authorization"
    assert locations.oauth2.prefix == "Bearer"


def test_security_scheme_locations_does_not_leak_secrets(
    test_client: TestClient,
    dummy_api_key_1: str,
    dummy_app_github: App,
) -> None:
    response = test_client.get(
        f"{config.ROUTER_PREFIX_APPS}/security-scheme-locations",
        params={"app_names": [dummy_app_github.name]},
        headers={"x-api-key": dummy_api_key_1},
    )
    assert response.status_code == status.HTTP_200_OK

    oauth2_location = response.json()[0]["security_scheme_locations"]["oauth2"]
    assert "client_id" not in oauth2_location
    assert "client_secret" not in oauth2_location
    assert "scope" not in oauth2_location


def test_security_scheme_locations_filters_by_app_names(
    test_client: TestClient,
    dummy_api_key_1: str,
    dummy_apps: list[App],
) -> None:
    response = test_client.get(
        f"{config.ROUTER_PREFIX_APPS}/security-scheme-locations",
        headers={"x-api-key": dummy_api_key_1},
    )
    assert response.status_code == status.HTTP_200_OK
    all_names = {item["app_name"] for item in response.json()}
    assert all_names == {app.name for app in dummy_apps}


def test_existing_app_endpoints_unchanged(
    test_client: TestClient,
    dummy_api_key_1: str,
    dummy_app_github: App,
) -> None:
    """GET /{app_name} and GET "" must still redact security scheme details exactly as before."""
    response = test_client.get(
        f"{config.ROUTER_PREFIX_APPS}/{dummy_app_github.name}",
        headers={"x-api-key": dummy_api_key_1},
    )
    assert response.status_code == status.HTTP_200_OK
    app = AppDetails.model_validate(response.json())
    assert app.supported_security_schemes.api_key.model_dump() == {}
    assert app.supported_security_schemes.oauth2.model_dump() == {"scope": app.supported_security_schemes.oauth2.scope}
