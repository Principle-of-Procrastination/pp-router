import copy
import secrets
from sqlalchemy import select

from pprouter.catalog import APPLICATIONS, DEFAULT_POLICY, MODELS, MODEL_IDS
from pprouter.models import AdminUser, Application, Company, CompanyApplication, Model
from pprouter.security import access_key, hash_password, new_key


async def initialize(db, password: str | None = None) -> dict:
    credentials = {}
    async with db.session.begin() as session:
        for model in MODELS:
            if not await session.get(Model, model["id"]):
                session.add(Model(**model))
        company = await session.scalar(select(Company).where(Company.code == "pp_admin"))
        if not company:
            company = Company(code="pp_admin", name="pp_admin", external_id="pp_admin")
            session.add(company)
            await session.flush()
        admin = await session.scalar(select(AdminUser).where(AdminUser.username == "pp_admin"))
        if not admin:
            generated = password or secrets.token_urlsafe(20)
            if len(generated) < 12:
                raise ValueError("PP_ADMIN_PASSWORD must contain at least 12 characters")
            session.add(
                AdminUser(username="pp_admin", password_hash=await hash_password(generated))
            )
            credentials["admin"] = {"username": "pp_admin", "password": generated}
        for definition in APPLICATIONS:
            code = definition["code"]
            app = await session.scalar(select(Application).where(Application.code == code))
            if not app:
                app = Application(**definition)
                session.add(app)
                await session.flush()
            grant = await session.scalar(
                select(CompanyApplication).where(
                    CompanyApplication.company_id == company.id,
                    CompanyApplication.application_id == app.id,
                )
            )
            if not grant:
                policy = copy.deepcopy(DEFAULT_POLICY)
                if code in ("pp_cad", "pp_code"):
                    policy["default_model"] = "kimi-k3.1-pro"
                grant = CompanyApplication(
                    company_id=company.id,
                    application_id=app.id,
                    allowed_models=MODEL_IDS,
                    policy=policy,
                )
                session.add(grant)
                await session.flush()
                raw = new_key()
                key = access_key(raw, name=f"pp_admin-{code}-local", grant_id=grant.id)
                session.add(key)
                credentials.setdefault("applications", {})[code] = {
                    "api_key": raw,
                    "company_id": company.id,
                    "application_id": app.id,
                    "grant_id": grant.id,
                }
        # A provisioning credential is created with the first administrator only.
        if "admin" in credentials:
            raw = new_key("provisioning")
            session.add(access_key(raw, name="local-suite-provisioning"))
            credentials["provisioning_api_key"] = raw
    return credentials
