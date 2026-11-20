import hashlib

from conftest import admin_login


async def test_suite_reconciles_company_and_preserves_limits_and_key_ownership(env):
    _, client, _, credentials = env
    await admin_login(client, credentials)
    api = "/internal/v1/suite/companies/"
    auth = {"Authorization": "Bearer " + credentials["provisioning_api_key"]}
    key = "ppk_" + "f" * 43
    body = {
        "name": "North",
        "enabled": True,
        "grants": {"pp_chat": hashlib.sha256(key.encode()).hexdigest()},
    }

    async def sync(slug, settings):
        return await client.put(api + slug, headers=auth, json=settings)

    result = await sync("north", body)
    assert result.status_code == 200, result.text
    company = result.json()["id"]
    assert (await sync("north", body)).json()["id"] == company
    assert (
        await client.get("/v1/models", headers={"Authorization": "Bearer " + key})
    ).status_code == 200
    assert (await sync("south", {**body, "name": "South"})).status_code == 409
    grants = (await client.get("/admin/v1/grants")).json()
    grant = next(g for g in grants if g["company_id"] == company)
    settings = {
        k: grant[k]
        for k in (
            "enabled",
            "rpm",
            "concurrency",
            "max_output_tokens",
            "policy",
            "allowed_models",
        )
    }
    settings["rpm"] = 9
    assert (
        await client.put("/admin/v1/grants/" + grant["id"], json=settings)
    ).status_code == 200
    assert (
        await client.put(
            "/admin/v1/grants/" + grant["id"], json={**settings, "enabled": False}
        )
    ).status_code == 409
    assert (await sync("north", {**body, "grants": {}})).status_code == 200
    assert (
        await client.get("/v1/models", headers={"Authorization": "Bearer " + key})
    ).status_code == 403
    assert (await sync("north", {**body, "name": "North Renamed"})).status_code == 200
    restored = next(
        g
        for g in (await client.get("/admin/v1/grants")).json()
        if g["id"] == grant["id"]
    )
    assert restored["rpm"] == 9 and restored["enabled"]
