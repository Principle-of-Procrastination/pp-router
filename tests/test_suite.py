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


async def test_cad_grant_meters_only_its_company_and_environment(env):
    _, client, _, credentials = env
    await admin_login(client, credentials)
    control = {"Authorization": "Bearer " + credentials["provisioning_api_key"]}
    companies = {}
    for slug in ("benhu", "neighbor"):
        key = "ppk_" + hashlib.sha256(slug.encode()).hexdigest()
        result = await client.put(
            "/internal/v1/suite/companies/" + slug,
            headers=control,
            json={
                "name": slug,
                "enabled": True,
                "grants": {"pp_cad": hashlib.sha256(key.encode()).hexdigest()},
            },
        )
        assert result.status_code == 200
        companies[slug] = (result.json()["id"], key)
    grants = (await client.get("/admin/v1/grants")).json()
    cad = next(g["application_id"] for g in grants if g["company_id"] == companies["benhu"][0])
    call = await client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + companies["benhu"][1],
            "X-Trace-Id": "cad-task-1",
            "X-Tenant-Id": "neighbor",
        },
        json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "fixture"}]},
    )
    assert call.status_code == 200 and call.headers["x-request-id"]
    for company, expected in [("benhu", 30), ("neighbor", None)]:
        report = await client.get(
            "/admin/v1/reports/monthly",
            params={
                "company_id": companies[company][0],
                "application_id": cad,
                "environment": "production",
            },
        )
        assert report.json()["summary"]["total_tokens"] == expected
