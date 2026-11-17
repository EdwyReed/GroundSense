"""GroundSense public-data and explicit synthetic-sandbox runtime API.

This module deliberately does not make a scientific result when the science engine is
not installed.  Persistent state is workspace-scoped by an opaque browser session.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import math
import secrets
import shutil
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from time import monotonic
from datetime import UTC, date as Date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import rfc8785
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.exc import IntegrityError
from apps.api.route_planner import register_route_endpoints
from apps.api.route_context import register_route_context_endpoints
from apps.api.terrain_planner import register_terrain_endpoints
from apps.api.terrain_path_planner import register_terrain_path_endpoints
from apps.api.terrain_profile import register_terrain_profile_endpoints

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "packages" / "domain" / "seed.json"
RESOURCE_NAMES = {"assets", "segments", "observations", "inspections", "protocols", "models", "envelopes", "constraints", "tickets", "subscriptions"}
READ_ONLY_SEED = {"sources", "notifications"}
MAX_JSON = 1_000_000
MAX_IMAGE = 20 * 1024 * 1024
ROLES = {"dispatcher", "engineer", "field", "admin"}
METADATA_KINDS = {"models", "envelopes"}
METADATA_TEXT_FIELDS = {"name", "description", "status", "scope", "card_ref", "source_ref", "reason"}
METADATA_FLAGS = {"synthetic", "calibrated", "model_approval", "production_eligible"}
METADATA_STATUSES = {"draft", "research", "blocked", "withdrawn"}


class Base(DeclarativeBase):
    pass


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    csrf: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="engineer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    logical_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[str] = mapped_column(Text)
    tombstoned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "logical_id", name="uq_resource_scope"),)


class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    logical_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(160))
    details: Mapped[str] = mapped_column(Text, default="{}")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    client_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(80))
    run_id: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    request_json: Mapped[str] = mapped_column(Text)
    assessment_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("workspace_id", "client_key", name="uq_analysis_idempotency"),)


class ImportBatch(Base):
    __tablename__ = "imports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    resource: Mapped[str] = mapped_column(String(40))
    fmt: Mapped[str] = mapped_column(String(20))
    digest: Mapped[str] = mapped_column(String(80))
    rows: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="preview")


class Blob(Base):
    __tablename__ = "blobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    mime: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def problem(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def jcs(value: Any) -> bytes:
    return rfc8785.dumps(value)


def strict_json(raw: str | bytes) -> Any:
    def pairs(items):
        result={}
        for k,v in items:
            if k in result: raise ValueError('Повторний ключ JSON')
            result[k]=v
        return result
    def nonfinite(_): raise ValueError('Нескінченні числа JSON заборонено')
    parsed=json.loads(raw,object_pairs_hook=pairs,parse_constant=nonfinite)
    def validate(value,depth=0):
        if depth>40: raise ValueError('Завелика вкладеність JSON')
        if isinstance(value,str): value.encode('utf-8',errors='strict')
        elif isinstance(value,int) and not isinstance(value,bool) and abs(value)>9007199254740991: raise ValueError('Ціле JSON поза безпечним діапазоном')
        elif isinstance(value,float) and not math.isfinite(value): raise ValueError('Нескінченне число')
        elif isinstance(value,dict):
            for k,v in value.items(): validate(k,depth+1);validate(v,depth+1)
        elif isinstance(value,list):
            for v in value: validate(v,depth+1)
    validate(parsed)
    return parsed


def load_seed() -> dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def serialise(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def permissions(role: str) -> list[str]:
    base = ["read", "create_observation", "create_analysis", "export"]
    if role in {"engineer", "admin"}:
        base += ["write_resources", "adjudicate_evidence"]
    if role == "admin":
        base += ["approve_model"]
    return base


def create_app(data_mode: str | None = None) -> FastAPI:
    """Build the original API in public-data mode unless a test asks for seed data."""
    data_mode = "public_data" if data_mode is None else data_mode
    if data_mode not in {"public_data", "synthetic"}:
        raise ValueError("data_mode must be 'public_data' or 'synthetic'")
    database_url = os.getenv("GROUNDSENSE_DATABASE_URL", "sqlite:///groundsense.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    data_dir = Path(os.getenv("GROUNDSENSE_DATA_DIR", ROOT / ".groundsense-data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="GroundSense API", version="0.1.0")
    app.state.factory = factory
    app.state.data_dir = data_dir
    from apps.api.live_data import LiveDataError, LiveWeatherClient
    app.state.live_weather = LiveWeatherClient(data_dir / 'live-weather')
    # Adapter construction is network-free; individual reads happen on request.
    try:
        from apps.api.static_sources import StaticSources
        app.state.static_sources = StaticSources(data_dir / "static-sources")
    except ImportError:
        app.state.static_sources = None
    try:
        from apps.api.remote_sources import RemoteSources
        app.state.remote_sources = RemoteSources(data_dir / "remote-sources")
    except ImportError:
        app.state.remote_sources = None
    app.state.extra_sources = {}
    if data_mode == "public_data":
        for key, module, class_name in (
            ("clms", "clms_sources", "CLMSSources"),
            ("context", "context_sources", "ContextSources"),
            ("sentinel1", "sentinel1_sources", "Sentinel1Sources"),
            ("osm", "osm_sources", "OSMSources"),
            ("hwsd", "hwsd_sources", "HWSDSources"),
        ):
            try:
                adapter = getattr(import_module("apps.api." + module), class_name)
                app.state.extra_sources[key] = adapter(data_dir / module.replace("_", "-"))
            except ImportError:
                continue
    app.state.context_slots = threading.BoundedSemaphore(2)
    live_requests: dict[str, deque] = {}
    live_budget = {'day': utcnow().date(), 'count': 0}
    live_budget_lock = threading.Lock()

    def consume_source_budget(workspace_id: str) -> None:
        with live_budget_lock:
            now = monotonic()
            if live_budget['day'] != utcnow().date():
                live_budget.update(day=utcnow().date(), count=0)
                live_requests.clear()
            recent = live_requests.setdefault(workspace_id, deque())
            while recent and now - recent[0] > 60:
                recent.popleft()
            if len(recent) >= 12 or live_budget['count'] >= 1000:
                raise problem(429, 'Ліміт запитів до відкритих джерел. Спробуйте пізніше.')
            recent.append(now)
            live_budget['count'] += 1

    @app.middleware("http")
    async def response_boundaries(request: Request, call_next):
        length=request.headers.get('content-length')
        if length:
            try:
                if int(length)>MAX_IMAGE+1_000_000: return JSONResponse({'detail':'Запит завеликий.'},status_code=413)
            except ValueError: return JSONResponse({'detail':'Некоректна довжина запиту.'},status_code=400)
        if request.method in {'POST','PATCH','PUT','DELETE'} and request.headers.get('content-type','').split(';')[0]=='application/json':
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>MAX_JSON: return JSONResponse({'detail':'JSON перевищує 1 МіБ.'},status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
            try: strict_json(request._body)
            except (ValueError,UnicodeError,RecursionError): return JSONResponse({'detail':'Неоднозначний або некоректний JSON.'},status_code=422)
        response = await call_next(request)
        if request.url.path.startswith(('/api/', '/__internal/')):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' blob: data: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(HTTPException)
    async def api_error(_: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": secrets.token_urlsafe(8)})

    def db() -> Session:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def session_for(request: Request, database: Session = Depends(db)) -> BrowserSession:
        token = request.cookies.get("__Host-gs_session")
        if not token:
            raise problem(401, "Сесію не знайдено. Відкрийте початкові дані.")
        item = database.get(BrowserSession, token)
        if not item or utcnow()-as_utc(item.created_at)>timedelta(hours=8):
            raise problem(401, "Сесія завершилася. Оновіть сторінку.")
        return item

    def mutate(request: Request, session: BrowserSession = Depends(session_for), csrf: str | None = Header(None, alias="X-CSRF-Token")) -> BrowserSession:
        origin = request.headers.get("origin")
        # The deployment proxy is loopback-only.  Its public origin is configured,
        # rather than accepted from an arbitrary browser supplied header.
        expected = os.getenv("GROUNDSENSE_PUBLIC_ORIGIN", f"{request.url.scheme}://{request.url.netloc}").rstrip("/")
        if csrf != session.csrf or origin != expected:
            raise problem(403, "Запит відхилено: перевірка CSRF або походження не пройдена.")
        return session

    register_route_endpoints(app, session_for, mutate, consume_source_budget)
    register_route_context_endpoints(app, session_for, mutate, consume_source_budget)
    register_terrain_endpoints(app, mutate, consume_source_budget)
    register_terrain_path_endpoints(app, mutate, consume_source_budget)
    register_terrain_profile_endpoints(app, mutate, consume_source_budget)

    def audit(database: Session, session: BrowserSession, action: str, target: str, details: dict[str, Any] | None = None) -> None:
        database.add(Audit(workspace_id=session.workspace_id, actor_role=session.role, action=action, target=target, details=serialise(details or {})))

    def row_data(row: Resource) -> dict[str, Any]:
        value = json.loads(row.data)
        if row.kind in METADATA_KINDS:
            original = value
            value = {k: v for k, v in original.items() if k in METADATA_TEXT_FIELDS and (v is None or isinstance(v, str))}
            if "status" in original and (not isinstance(original["status"], str) or original["status"] not in METADATA_STATUSES):
                value["status"] = "blocked"
            if type(original.get("synthetic")) is bool:
                value["synthetic"] = original["synthetic"]
            if "calibrated" in original:
                value["calibrated"] = False if original["calibrated"] is False else None
            value.update(metadata_only=True, model_approval=False, production_eligible=False)
        value["id"] = row.logical_id
        value["version"] = row.version
        return value

    def get_resource(database: Session, session: BrowserSession, kind: str, ident: str) -> Resource:
        row = database.scalar(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.kind == kind, Resource.logical_id == ident, Resource.tombstoned == 0))
        if not row:
            raise problem(404, "Ресурс не знайдено у вашому робочому просторі.")
        return row

    def require(role_set: set[str], session: BrowserSession) -> None:
        if session.role not in role_set:
            raise problem(403, "Вашій демонстраційній ролі недоступна ця дія.")

    def revision_version(payload: dict[str, Any]) -> int:
        expected = payload.get("expected_version")
        if type(expected) is not int or expected < 1:
            raise problem(422, "Потрібна явна додатна ціла expected_version поточного запису.")
        return expected

    def validate_resource_payload(kind: str, value: dict[str, Any]) -> None:
        if kind == "observations" and "adjudication" in value:
            raise problem(422, "Рішення рецензування змінюється лише через окрему дію з поточною версією.")
        if kind in METADATA_KINDS:
            allowed = METADATA_TEXT_FIELDS | METADATA_FLAGS | {"id", "expected_version"}
            if set(value) - allowed:
                raise problem(422, "Дозволено лише оголошені поля метаданих моделі або транспортної межі.")
            for field in METADATA_TEXT_FIELDS:
                if field in value and value[field] is not None and not isinstance(value[field], str):
                    raise problem(422, "Описові поля метаданих мають бути текстом або null.")
            if "synthetic" in value and value["synthetic"] is not None and type(value["synthetic"]) is not bool:
                raise problem(422, "Ознака synthetic має бути boolean або null.")
            if "status" in value and (not isinstance(value["status"], str) or
                                      value["status"] not in METADATA_STATUSES):
                raise problem(422, "У синтетичному реєстрі неможливо затвердити виробничу модель.")
            for flag in ("calibrated", "model_approval", "production_eligible"):
                if flag in value and value[flag] is not False and value[flag] is not None:
                    raise problem(422, "Загальний редактор не надає калібрування або виробничий допуск.")

    def public_asset(value: dict[str, Any]) -> dict[str, Any]:
        if data_mode != "public_data":
            return value
        geometry = value.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) and geometry.get("type") == "Point" else None
        if not isinstance(value.get("name"), str) or not value["name"].strip() or not isinstance(value.get("source_ref"), str) or not value["source_ref"].strip() or not isinstance(coordinates, list) or len(coordinates) != 2:
            raise problem(422, "Реальному об’єкту потрібні назва, точкова геометрія та походження координат.")
        latitude, longitude = live_coordinates(coordinates[1], coordinates[0])
        return {**value, "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "synthetic": False, "identity_verified": False, "condition": "unknown", "data_origin": "user_supplied"}

    def observation_metadata(database: Session, session: BrowserSession, value: dict[str, Any], original: dict[str, Any] | None = None) -> dict[str, Any]:
        value = dict(value)
        value['entered_at'] = (original or {}).get('entered_at') or utcnow().isoformat()
        evidence = value.get('evidence_id')
        if evidence:
            blob = database.get(Blob, evidence)
            if not blob or blob.workspace_id != session.workspace_id:
                raise problem(422, 'Прикріплений доказ не знайдено у вашому просторі.')
        return value

    def revise_resource(database: Session, session: BrowserSession, row: Resource, expected: int,
                        value: dict[str, Any], action: str, details: dict[str, Any] | None = None,
                        *, tombstone: bool = False) -> dict[str, Any]:
        if row.kind == "assets":
            value = public_asset(value)
        value = {**value, "id": row.logical_id, "version": expected + 1}
        if tombstone:
            value["tombstoned"] = True
        else:
            value.pop("tombstoned", None)
        encoded = serialise(value)
        changed = database.execute(
            update(Resource).where(Resource.id == row.id, Resource.workspace_id == session.workspace_id,
                                   Resource.version == expected, Resource.tombstoned == 0)
            .values(version=expected + 1, data=encoded, tombstoned=int(tombstone))
            .execution_options(synchronize_session=False)
        ).rowcount
        if changed != 1:
            database.rollback()
            raise problem(409, "Версія ресурсу змінилася. Оновіть дані перед повтором.")
        database.add(Revision(workspace_id=session.workspace_id, kind=row.kind,
                              logical_id=row.logical_id, version=expected + 1, data=encoded))
        audit(database, session, action, f"{row.kind}/{row.logical_id}",
              details if details is not None else {"version": expected + 1})
        database.commit()
        return value

    def create_resource(database: Session, session: BrowserSession, kind: str, value: dict[str, Any], *, imported: bool = False) -> dict[str, Any]:
        if kind == "assets":
            value = public_asset(value)
        if kind == 'observations':
            value = observation_metadata(database, session, value)
        ident = str(value.get("id") or f"{kind[:3].upper()}-{uuid.uuid4().hex[:12]}")
        if len(ident) > 100:
            raise problem(422, "Ідентифікатор занадто довгий.")
        value = {k: v for k, v in value.items() if k not in {"version", "workspace_id", "expected_version", "tombstoned"}}
        value["id"] = ident
        row = Resource(workspace_id=session.workspace_id, kind=kind, logical_id=ident, version=1, data=serialise(value))
        database.add(row)
        database.flush()
        database.add(Revision(workspace_id=session.workspace_id, kind=kind, logical_id=ident, version=1, data=row.data))
        audit(database, session, "import" if imported else "create", f"{kind}/{ident}")
        return row_data(row)

    def clone_seed(database: Session, session: BrowserSession) -> None:
        if database.scalar(select(Resource.id).where(Resource.workspace_id == session.workspace_id, Resource.kind.in_(RESOURCE_NAMES | READ_ONLY_SEED)).limit(1)):
            return
        seed = load_seed()
        for kind in RESOURCE_NAMES | READ_ONLY_SEED:
            for item in seed.get(kind, []):
                create_resource(database, session, kind, item)
        database.commit()

    def public_marker(database: Session, workspace_id: str) -> bool:
        return database.scalar(select(Resource.id).where(
            Resource.workspace_id == workspace_id, Resource.kind == "workspace_config",
            Resource.logical_id == "public-data-v1", Resource.tombstoned == 0,
        )) is not None

    def initialise_public_workspace(database: Session, session: BrowserSession) -> None:
        """Move only legacy live records into a fresh public workspace, once."""
        if public_marker(database, session.workspace_id):
            return
        old_workspace = session.workspace_id
        rows = database.scalars(select(Resource).where(
            Resource.workspace_id == old_workspace,
            Resource.kind.in_(("live_assets", "live_weather_snapshots")),
            Resource.tombstoned == 0,
        )).all()
        has_seed = database.scalar(select(Resource.id).where(
            Resource.workspace_id == old_workspace, Resource.kind.in_(RESOURCE_NAMES | READ_ONLY_SEED)
        ).limit(1)) is not None
        if has_seed:
            session.workspace_id = "ws_" + secrets.token_urlsafe(18)
            database.flush()
        for row in rows:
            value = row_data(row)
            value.pop("version", None)
            create_resource(database, session, "assets" if row.kind == "live_assets" else row.kind, value)
        create_resource(database, session, "workspace_config", {
            "id": "public-data-v1", "mode": "public_data", "synthetic": False,
        })
        database.commit()

    def feature_statuses() -> list[dict[str, Any]]:
        rows=json.loads((ROOT/'packages/domain/feature_status.json').read_text(encoding='utf-8'))
        if len(rows)!=70 or len({r['id'] for r in rows})!=70: raise RuntimeError('Некоректна матриця покриття')
        return rows

    def bootstrap_session(response: Response, request: Request, database: Session) -> BrowserSession:
        token = request.cookies.get("__Host-gs_session")
        item = database.get(BrowserSession, token) if token else None
        if item is None or utcnow()-as_utc(item.created_at)>timedelta(hours=8):
            item = BrowserSession(id=secrets.token_urlsafe(48), workspace_id="ws_" + secrets.token_urlsafe(18), csrf=secrets.token_urlsafe(32), role="engineer")
            database.add(item)
            database.commit()
            response.set_cookie("__Host-gs_session", item.id, httponly=True, secure=os.getenv("GROUNDSENSE_SECURE_COOKIE", "1") == "1", samesite="lax", path="/", max_age=8 * 3600)
        return item

    def live_coordinates(latitude: Any, longitude: Any) -> tuple[float, float]:
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (latitude, longitude)):
            raise problem(422, 'Координати мають бути скінченними числами.')
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise problem(422, 'Координати поза допустимими межами WGS84.')
        return float(latitude), float(longitude)

    def live_asset_payload(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {'name', 'latitude', 'longitude', 'source_ref', 'id'}:
            raise problem(422, 'Невідомі поля реального об’єкта.')
        lat, lon = live_coordinates(value.get('latitude'), value.get('longitude'))
        if any(not isinstance(value.get(k), str) or not value[k].strip() for k in ('name', 'source_ref')):
            raise problem(422, 'Потрібні назва й посилання на походження координат.')
        if len(value['name']) > 240 or len(value['source_ref']) > 2000:
            raise problem(422, 'Опис об’єкта задовгий.')
        if 'id' in value and (not isinstance(value['id'], str) or not value['id'] or len(value['id']) > 100):
            raise problem(422, 'Некоректний ідентифікатор об’єкта.')
        return {**value, 'latitude': lat, 'longitude': lon, 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                'synthetic': False, 'data_origin': 'user_supplied', 'identity_verified': False, 'condition': 'unknown'}

    @app.get('/api/v1/live/bootstrap')
    def live_bootstrap(response: Response, request: Request, database: Session = Depends(db)):
        item = bootstrap_session(response, request, database)
        assets = [row_data(r) for r in database.scalars(select(Resource).where(Resource.workspace_id == item.workspace_id, Resource.kind == 'live_assets', Resource.tombstoned == 0)).all()]
        return {'workspace': {'id': item.workspace_id, 'mode': 'public_data', 'synthetic': False, 'private_data_allowed': False},
                'csrf_token': item.csrf, 'user': {'role': item.role}, 'assets': assets, 'today': utcnow().date().isoformat(),
                'sources': [
                    {'id': 'openfreemap', 'name': 'OpenFreeMap / OpenStreetMap', 'product': 'Картографічна основа', 'status': 'on_request', 'url': 'https://openfreemap.org/', 'license': 'OSM ODbL / OpenMapTiles'},
                    {'id': 'open-meteo-icon-global', 'name': 'Open-Meteo / DWD ICON Global', 'product': 'Метеопрогноз і модельні шари ґрунту', 'status': 'on_request', 'url': 'https://open-meteo.com/', 'license': 'CC BY 4.0', 'service_usage': 'non_commercial_prototype'}]}

    @app.get('/api/v1/live/assets/{ident}')
    def live_asset(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        return row_data(get_resource(database, session, 'live_assets', ident))

    @app.post('/api/v1/live/assets', status_code=201)
    def save_live_asset(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if 'write_resources' not in permissions(session.role):
            raise problem(403, 'Роль не дозволяє змінювати реєстр.')
        value = live_asset_payload(payload)
        if 'id' in value and database.scalar(select(Resource.id).where(Resource.workspace_id == session.workspace_id, Resource.kind == 'live_assets', Resource.logical_id == value['id'])):
            raise problem(409, 'Ідентифікатор уже існує.')
        saved = create_resource(database, session, 'live_assets', value)
        database.commit()
        return saved

    @app.post('/api/v1/live/assets/import', status_code=201)
    def import_live_assets(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if 'write_resources' not in permissions(session.role):
            raise problem(403, 'Роль не дозволяє змінювати реєстр.')
        try:
            raw = payload['data']
            if not isinstance(raw, str):
                raise ValueError()
            if payload.get('format') == 'csv':
                reader = csv.DictReader(io.StringIO(raw))
                if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                    raise ValueError()
                rows = []
                for item in reader:
                    rows.append({**item, 'latitude': float(item['latitude']), 'longitude': float(item['longitude'])})
            elif payload.get('format') == 'geojson':
                doc = strict_json(raw)
                if doc.get('type') != 'FeatureCollection':
                    raise ValueError()
                rows = []
                for feature in doc['features']:
                    g = feature['geometry']
                    if feature.get('type') != 'Feature' or g.get('type') != 'Point' or len(g['coordinates']) != 2:
                        raise ValueError()
                    rows.append({**feature['properties'], 'longitude': g['coordinates'][0], 'latitude': g['coordinates'][1]})
            else:
                raise ValueError()
            if not 1 <= len(rows) <= 1000:
                raise ValueError()
            values = [live_asset_payload(item) for item in rows]
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise problem(422, 'Потрібен CSV або GeoJSON з 1–1000 коректних точок, назвами та джерелами координат.')
        ids = [v['id'] for v in values if 'id' in v]
        if len(ids) != len(set(ids)) or (ids and database.scalar(select(Resource.id).where(Resource.workspace_id == session.workspace_id, Resource.kind == 'live_assets', Resource.logical_id.in_(ids)))):
            raise problem(409, 'Повторні ідентифікатори об’єктів.')
        items = [create_resource(database, session, 'live_assets', v, imported=True) for v in values]
        database.commit()
        return {'items': items, 'imported': len(items)}

    @app.get('/api/v1/live/weather')
    def live_weather(latitude: float, longitude: float, assessment_date: str | None = None, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        live_coordinates(latitude, longitude)
        if assessment_date is not None:
            try:
                Date.fromisoformat(assessment_date)
            except ValueError:
                raise problem(422, 'Некоректна дата оцінки.')
        consume_source_budget(session.workspace_id)
        try:
            result = app.state.live_weather.forecast(latitude, longitude, assessment_date)
            digest = result['source']['content_sha256'].removeprefix('sha256:')
            path = app.state.live_weather.snapshot_path(digest)
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or sha(path.read_bytes()) != 'sha256:' + digest:
                raise problem(502, 'Не вдалося перевірити збережений знімок джерела.')
            existing = database.scalar(select(Resource.id).where(Resource.workspace_id == session.workspace_id, Resource.kind == 'live_weather_snapshots', Resource.logical_id == digest))
            if not existing:
                try:
                    create_resource(database, session, 'live_weather_snapshots', {**result['source'], 'id': digest})
                    database.commit()
                except IntegrityError:
                    database.rollback()
                    get_resource(database, session, 'live_weather_snapshots', digest)
            result['snapshot_url'] = '/api/v1/live/weather/snapshots/' + digest
            return result
        except LiveDataError as exc:
            raise problem(exc.status_code, exc.message)
        except OSError:
            raise problem(503, 'Не вдалося прочитати або зберегти знімок джерела.')

    @app.get('/api/v1/live/weather/snapshots/{digest}')
    def live_weather_snapshot(digest: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise problem(404, 'Знімок не знайдено.')
        get_resource(database, session, 'live_weather_snapshots', digest)
        try:
            path = app.state.live_weather.snapshot_path(digest)
            if not path.is_file():
                raise problem(404, 'Знімок джерела недоступний.')
        except LiveDataError as exc:
            raise problem(exc.status_code, exc.message)
        return FileResponse(path, media_type='application/json', filename='open-meteo-' + digest[:12] + '.json')

    @app.get("/api/v1/bootstrap")
    def bootstrap(response: Response, request: Request, database: Session = Depends(db)):
        item = bootstrap_session(response, request, database)
        if data_mode == "synthetic":
            clone_seed(database, item)
            seed = load_seed()
            payload = {kind: [row_data(r) for r in database.scalars(select(Resource).where(Resource.workspace_id == item.workspace_id, Resource.kind == kind, Resource.tombstoned == 0)).all()] for kind in RESOURCE_NAMES | READ_ONLY_SEED}
            payload.update({"workspace": {**seed["workspace"], "id": item.workspace_id}, "context": seed["context"], "user": {"role": item.role, "display_name": "Синтетичний користувач", "permissions": permissions(item.role)}, "csrf_token": item.csrf, "runs": [{"id": x.run_id, "status": x.status} for x in database.scalars(select(Analysis).where(Analysis.workspace_id == item.workspace_id)).all()], "soil": seed["soil"], "map": seed["map"], "features": feature_statuses(), "capabilities": {"oidc": "unconfigured", "sandbox": True, "science": "available" if science_assess() else "unavailable"}})
            return payload
        initialise_public_workspace(database, item)
        payload = {kind: [row_data(r) for r in database.scalars(select(Resource).where(Resource.workspace_id == item.workspace_id, Resource.kind == kind, Resource.tombstoned == 0)).all()] for kind in RESOURCE_NAMES | READ_ONLY_SEED}
        payload.update({
            "workspace": {"id": item.workspace_id, "mode": "public_data", "synthetic": False, "private_data_allowed": False},
            "context": {"assessment_date": utcnow().date().isoformat(), "gross_mass_t": 20, "selected_asset_id": None, "synthetic": False},
            "user": {"role": item.role, "display_name": "Публічний користувач", "permissions": permissions(item.role)},
            "csrf_token": item.csrf, "runs": [{"id": x.run_id, "status": x.status} for x in database.scalars(select(Analysis).where(Analysis.workspace_id == item.workspace_id)).all()],
            "soil": {"composition": None, "support_m": None, "depths": []},
            "map": {"mode": "public_data", "type": "FeatureCollection", "features": []},
            "sources": [{"id": ident, "name": name, "product": product, "version": None, "status": "on_request", "qc": "unknown", "note": "Очікує запиту для обраного об’єкта. Наявність у каталозі не є отриманням даних.", "retrieved_at": None, "observed_at": None, "content_sha256": None} for ident, name, product in [("soilgrids", "ISRIC", "SoilGrids 2.0"), ("copernicus-glo-30", "Copernicus", "GLO-30 DSM"), ("esa-worldcover", "ESA", "WorldCover 2021"), ("sentinel-1-grd", "Sentinel-1", "GRD"), ("sentinel-2-l2a", "Sentinel-2", "L2A"), ("clms-swi-1km-v2", "CLMS", "Soil Water Index Europe 1 km v2"), ("clms-ssm-1km", "CLMS", "Surface Soil Moisture 1 km"), ("era5-land", "Copernicus / ECMWF", "ERA5-Land"), ("open-meteo-icon-global", "Open-Meteo / DWD", "ICON Global"), ("ecmwf-ifs", "ECMWF", "IFS"), ("ecmwf-aifs", "ECMWF", "AIFS"), ("noaa-gfs", "NOAA", "GFS"), ("openstreetmap", "OpenStreetMap", "Картографічна основа через OpenFreeMap"), ("hwsd-v2", "FAO / IIASA", "HWSD v2"), ("esdac-ukraine-soil-map", "JRC", "Історична карта ґрунтів 1977"), ("corine-land-cover", "CLMS", "CORINE Land Cover 2018"), ("clms-tree-cover-density", "CLMS", "Tree Cover Density 2018")]],
            "features": feature_statuses(),
            "capabilities": {"oidc": "unconfigured", "sandbox": False,
                             "science": "research_only" if public_science_assess() else "unavailable",
                             "transport_model": "unavailable", "field_validation": False},
        })
        return payload

    @app.post("/api/v1/demo/role")
    def demo_role(payload: dict[str, Any], response: Response, database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        role = payload.get("role")
        if role not in ROLES:
            raise problem(422, "Невідома демонстраційна роль.")
        session.role = role
        session.id=secrets.token_urlsafe(48)
        session.csrf=secrets.token_urlsafe(32)
        response.set_cookie('__Host-gs_session',session.id,httponly=True,secure=os.getenv('GROUNDSENSE_SECURE_COOKIE','1')=='1',samesite='lax',path='/',max_age=8*3600)
        audit(database, session, "demo_role", "session", {"role": role})
        database.commit()
        return {"role": role, "sandbox_only": True, "permissions": permissions(role)}

    @app.get("/__internal/api/v1/{resource}")
    def list_resources(resource: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        if resource not in RESOURCE_NAMES | READ_ONLY_SEED:
            raise problem(404, "Такий ресурс не підтримується.")
        return {"items": [row_data(r) for r in database.scalars(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.kind == resource, Resource.tombstoned == 0)).all()]}

    @app.get("/__internal/api/v1/{resource}/{ident}")
    def read_resource(resource: str, ident: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        if resource not in RESOURCE_NAMES | READ_ONLY_SEED:
            raise problem(404, "Такий ресурс не підтримується.")
        return row_data(get_resource(database, session, resource, ident))

    @app.post("/__internal/api/v1/{resource}", status_code=201)
    def post_resource(resource: str, payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if resource not in RESOURCE_NAMES:
            raise problem(404, "Створення цього ресурсу недоступне.")
        if resource not in {"observations", "inspections"}:
            require({"engineer", "admin"}, session)
        validate_resource_payload(resource, payload)

        result = create_resource(database, session, resource, payload)
        database.commit()
        return result

    @app.patch("/__internal/api/v1/{resource}/{ident}")
    def patch_resource(resource: str, ident: str, payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if resource not in RESOURCE_NAMES:
            raise problem(404, "Оновлення цього ресурсу недоступне.")
        require({"engineer", "admin"}, session)
        validate_resource_payload(resource, payload)
        row = get_resource(database, session, resource, ident)
        expected = revision_version(payload)
        payload.pop("expected_version")
        if expected != row.version:
            raise problem(409, "Версія ресурсу змінилася. Оновіть дані перед повтором.")
        value = row_data(row)
        value.update({k: v for k, v in payload.items() if k not in {"id", "version", "workspace_id", "tombstoned"}})
        if resource == 'observations':
            value = observation_metadata(database, session, value, row_data(row))
        return revise_resource(database, session, row, expected, value, "revise")

    @app.delete("/__internal/api/v1/{resource}/{ident}")
    def delete_resource(resource: str, ident: str, payload: dict[str, Any] | None = None, database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        require({"admin"}, session)
        if resource not in RESOURCE_NAMES:
            raise problem(404, "Видалення цього ресурсу недоступне.")
        row = get_resource(database, session, resource, ident)
        expected = revision_version(payload or {})
        value = revise_resource(database, session, row, expected, json.loads(row.data), "tombstone",
                                {"version": expected + 1, "tombstoned": True}, tombstone=True)
        return {"id": ident, "version": value["version"], "tombstoned": True}

    @app.post("/api/v1/observations/{ident}/adjudications")
    def adjudicate(ident: str, payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        require({"engineer", "admin"}, session)
        if payload.get("decision") not in {"accepted", "rejected"} or not str(payload.get("reason", "")).strip():
            raise problem(422, "Потрібні рішення accepted/rejected та причина.")
        row = get_resource(database, session, "observations", ident)
        expected = revision_version(payload)
        if expected != row.version:
            raise problem(409, "Версія спостереження змінилася.")
        value = row_data(row); value["adjudication"] = {"decision": payload["decision"], "reason": payload["reason"], "at": utcnow().isoformat()}
        return revise_resource(database, session, row, expected, value, "adjudicate", value["adjudication"])

    @app.get("/api/v1/audit")
    def get_audit(database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        rows = database.scalars(select(Audit).where(Audit.workspace_id == session.workspace_id).order_by(Audit.id.desc())).all()
        return {"items": [{"action": r.action, "target": r.target, "role": r.actor_role, "at": r.at.isoformat(), "details": json.loads(r.details)} for r in rows]}

    def real_asset(database: Session, session: BrowserSession, ident: str) -> dict[str, Any]:
        for kind in ("assets", "live_assets"):
            row = database.scalar(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.kind == kind, Resource.logical_id == ident, Resource.tombstoned == 0))
            if row:
                return row_data(row)
        raise problem(404, "Ресурс не знайдено у вашому робочому просторі.")

    def real_forecast(asset: dict[str, Any], assessment_date: str, gross_mass_t: float) -> dict[str, Any]:
        geometry = asset.get("geometry") or {}
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise problem(422, "Реальному об’єкту потрібна точкова геометрія.")
        try:
            weather = app.state.live_weather.forecast(coordinates[1], coordinates[0], assessment_date)
        except LiveDataError as exc:
            raise problem(exc.status_code, exc.message)
        assess_public_weather = public_science_assess()
        if not assess_public_weather:
            raise problem(503, "Дослідницький модуль недоступний; розрахунок не підмінено прогнозом.")
        research = assess_public_weather(weather)
        source = weather.get("source", {})
        rows = []
        for value in weather.get("series", []):
            rows.append({"time": value.get("time"), "moisture_p50": value.get("moisture_p50", value.get("soil_moisture_0_to_1cm")), "moisture_p10": None, "moisture_p90": None, "precipitation_mm": value.get("precipitation_mm", value.get("precipitation")), "temperature_c": value.get("temperature_c", value.get("temperature_2m"))})
        # Retain exactly the model inputs used, not a later mutable registry read.
        # This is a research scenario, not an observed road profile. The source raw
        # digest and normalized window allow replay without another provider call.
        snapshot = {"asset": asset, "weather": weather,
                    "research_model_version": research["model_version"],
                    "scenario_parameters": [{"id": item["id"], "parameters": item.get("parameters", {})}
                                            for item in research.get("scenarios", [])]}
        return {"asset_id": asset["id"], "assessment_date": assessment_date, "gross_mass_t": gross_mass_t,
                "mode": "research_water_balance", "synthetic": False, "model_version": research["model_version"],
                "computed_at": utcnow().isoformat(), "forecast_issue_time": source.get("issue_time", weather.get("forecast_issue_time")),
                "condition": research["condition"] if research["status"] == "research_only" else "unknown",
                "research": research, "input_snapshot": snapshot,
                "mobility": {"kind": "unavailable", "reason_codes": ["MODEL_NOT_VALIDATED", "ROAD_STRUCTURE_UNKNOWN", "VEHICLE_ENVELOPE_UNSUPPORTED"]},
                "recovery": {"kind": "unavailable", "reason_codes": ["ROAD_RECOVERY_NOT_ASSESSED"]},
                "series": rows, "source_supports": [source],
                "warnings": ["Водний баланс — дослідницькі сценарії з явними припущеннями, не вимірювання дороги.",
                             "Повна маса без осей, шин та конструкції під’їзду не визначає допуск; вона не змінює водний баланс.",
                             "Сценарне підсихання не є часом відкриття дороги або підтвердженням проїзду."]}

    @app.get("/api/v1/asset-context")
    def asset_context(asset_id: str, assessment_date: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        try:
            Date.fromisoformat(assessment_date)
        except ValueError:
            raise problem(422, "Некоректна дата оцінки.")
        asset = real_asset(database, session, asset_id)
        coordinates = asset.get("geometry", {}).get("coordinates", [])
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise problem(422, "Реальному об’єкту потрібна точкова геометрія.")
        latitude, longitude = live_coordinates(coordinates[1], coordinates[0])
        consume_source_budget(session.workspace_id)
        if not app.state.context_slots.acquire(blocking=False):
            raise problem(429, "Джерела вже обробляють запити. Спробуйте трохи пізніше.")
        fallback_ids = {
            "static": ("soilgrids", "copernicus-glo-30", "esa-worldcover"),
            "remote": ("era5-land", "sentinel-1-grd", "sentinel-2-l2a", "ecmwf-ifs", "ecmwf-aifs", "noaa-gfs"),
            "clms": ("clms-swi-1km-v2", "clms-ssm-1km"),
            "context": ("hwsd-v2", "esdac-ukraine-soil-map", "corine-land-cover", "clms-tree-cover-density"),
            "sentinel1": ("sentinel-1-grd",), "osm": ("openstreetmap",),
            "hwsd": ("hwsd-v2",),
        }
        def read_adapter(key, adapter):
            if adapter is None:
                return {}
            try:
                value = adapter.read(latitude, longitude) if key == "static" else adapter.read(latitude, longitude, assessment_date)
                if not isinstance(value, dict):
                    raise ValueError("invalid adapter response")
                return value
            except Exception as exc:
                # Provider-local failure boundary: do not expose raw exceptions,
                # which may contain signed asset URLs or credential fragments.
                return {"sources": [{"id": ident, "name": ident, "product": ident, "version": None, "status": "unavailable", "qc": "unavailable", "note": f"Джерело недоступне ({type(exc).__name__}); інші джерела не підмінюються.", "retrieved_at": None, "observed_at": None, "content_sha256": None, "data": {}} for ident in fallback_ids.get(key, ())]}
        try:
            adapters = {"static": app.state.static_sources, "remote": app.state.remote_sources, **app.state.extra_sources}
            # At most two context requests, each with at most seven independent
            # provider reads. No background executor or unbounded task queue.
            with ThreadPoolExecutor(max_workers=7) as pool:
                futures = {key: pool.submit(read_adapter, key, adapter) for key, adapter in adapters.items()}
                pieces = {key: future.result() for key, future in futures.items()}
        finally:
            app.state.context_slots.release()
        static, remote = pieces.get("static", {}), pieces.get("remote", {})
        source_rows = {}
        for piece in pieces.values():
            for source in [*piece.get("sources", []), *([piece["source"]] if piece.get("source") else [])]:
                if isinstance(source, dict) and source.get("id"):
                    previous = source_rows.get(source["id"])
                    if source["id"] == "sentinel-1-grd" and previous and previous.get("content_sha256") and source.get("status") in {"unavailable", "auth_required"}:
                        source_rows[source["id"]] = {**previous, "status": "partial", "qc": "partial", "note": (previous.get("note") or "") + " · " + (source.get("note") or ""), "data": {**(previous.get("data") or {}), "processed_read_status": source.get("status")}}
                    else:
                        source_rows[source["id"]] = source
        satellites = remote.get("satellites") or {}
        if not isinstance(satellites, dict):
            satellites = {}
        sentinel1 = pieces.get("sentinel1", {})
        if sentinel1.get("satellite"):
            satellites["sentinel_1"] = sentinel1["satellite"]
        unavailable = {"status": "unavailable", "qc": "unavailable", "note": "Адаптер джерела не налаштований.", "retrieved_at": None, "observed_at": None, "content_sha256": None}
        return {"asset_id": asset_id, "assessment_date": assessment_date,
                "soil": static.get("soil", {"composition": None, "support_m": None, "depths": []}),
                "terrain": static.get("terrain", {}), "land_cover": static.get("land_cover", {}),
                "satellites": satellites, "history": remote.get("history", []),
                "soil_moisture": pieces.get("clms", {}).get("soil_moisture", {}),
                "historical_context": {**pieces.get("context", {}).get("context", {}), **pieces.get("hwsd", {}).get("context", {})},
                "osm": {"ways": pieces.get("osm", {}).get("ways", [])},
                "sources": list(source_rows.values()) or [{"id": "static-sources", "name": "Static sources", **unavailable}, {"id": "remote-sources", "name": "Remote sources", **unavailable}],
                "synthetic": False}

    def public_science_assess():
        try:
            from packages.science.public_assessment import assess_public_weather
            return assess_public_weather
        except (ImportError, ModuleNotFoundError):
            return None

    def science_assess():
        try:
            from packages.science.engine import assess  # type: ignore
            return assess
        except (ImportError, ModuleNotFoundError):
            return None

    def execute_job(job_id: str) -> None:
        """Single-process cooperative worker; cancellation is checked before publish."""
        database = factory()
        try:
            job = database.get(Analysis, job_id)
            if not job or job.status != "queued":
                return
            assess = science_assess() if data_mode == "synthetic" else None
            if data_mode == "synthetic" and not assess:
                job.status = "failed"
                database.commit()
                return
            job.status = "running"
            database.commit()
            request_data = json.loads(job.request_json)
            # Re-read status after the science call. A cancelled job must never
            # publish, even if the computation completed while cancellation raced.
            if data_mode == "synthetic":
                snapshot=request_data.get('_snapshot')
                if not snapshot:
                    job.status = "failed"; database.commit(); return
                assessment = assess(assessment_date=request_data["assessment_date"], gross_mass_t=request_data["gross_mass_t"], asset=snapshot['asset'], seed=snapshot['seed'])
            else:
                assessment = real_forecast(real_asset(database, BrowserSession(workspace_id=job.workspace_id, id="", csrf="", role="engineer"), request_data["asset_id"]), request_data["assessment_date"], request_data["gross_mass_t"])
                snapshot = assessment["input_snapshot"]
            database.refresh(job)
            if job.status == "cancelled":
                return
            assessment_bytes = jcs(assessment)
            manifest = {"contract":"GroundSense-prototype/v1","run_id":job.run_id,"request":{k:v for k,v in request_data.items() if not k.startswith('_')},"input_snapshot_digest":sha(jcs(snapshot)),"assessment_digest":sha(assessment_bytes),"published_at":utcnow().isoformat(),"synthetic":data_mode == "synthetic"}
            manifest_bytes = jcs(manifest)
            # Conditional publication and cancellation contend on the same SQL row.
            database.execute(update(Analysis).where(Analysis.id==job.id,Analysis.status=='running').values(assessment_json=serialise(assessment),manifest_json=manifest_bytes.decode('utf-8'),manifest_digest=sha(manifest_bytes),status='published'))
            database.commit()
        except Exception:
            database.rollback()
            failed = database.get(Analysis, job_id)
            if failed and failed.status != "cancelled":
                failed.status = "failed"; database.commit()
        finally:
            database.close()

    @app.get("/api/v1/forecast")
    def forecast(asset_id: str, assessment_date: str, gross_mass_t: float, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        try:
            Date.fromisoformat(assessment_date)
            if not math.isfinite(gross_mass_t) or gross_mass_t <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise problem(422, "Потрібні коректна дата оцінки та скінченна додатна маса.")
        if data_mode == "synthetic":
            assess = science_assess()
            if not assess:
                raise problem(503, "Науковий модуль недоступний; прогноз не створено.")
            asset = row_data(get_resource(database, session, "assets", asset_id))
            return assess(assessment_date=assessment_date, gross_mass_t=gross_mass_t, asset=asset, seed=load_seed())
        asset = real_asset(database, session, asset_id)
        consume_source_budget(session.workspace_id)
        return real_forecast(asset, assessment_date, gross_mass_t)

    @app.post("/api/v1/analyses", status_code=202)
    def analyses(payload: dict[str, Any], idempotency_key: str | None = Header(None, alias="Idempotency-Key"), database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if not idempotency_key or len(idempotency_key) > 200:
            raise problem(422, "Потрібен коректний заголовок Idempotency-Key.")
        try:
            mass = float(payload["gross_mass_t"]); date = str(payload["assessment_date"])
            Date.fromisoformat(date)
            if isinstance(payload['gross_mass_t'],bool) or not math.isfinite(mass) or mass <= 0: raise ValueError
        except (KeyError, TypeError, ValueError):
            raise problem(422, "Потрібні дата оцінки та додатна повна маса.")
        asset_id=str(payload.get('asset_id') or 'GS-014')
        asset = row_data(get_resource(database,session,'assets',asset_id)) if data_mode == "synthetic" else real_asset(database, session, asset_id)
        canonical = {"assessment_date":date,"gross_mass_t":mass,"asset_id":asset_id,"contract":"prototype/v1"}; fingerprint=sha(jcs(canonical))
        if data_mode == "synthetic":
            seed=load_seed(); today=datetime.now(ZoneInfo(seed['workspace']['timezone'])).date()
            target=Date.fromisoformat(date)
            mode='reconstruction' if target<today else ('forecast' if target<=today+timedelta(days=int(seed['demo_forcing'].get('availability_days',10))) else 'climatology')
            request_record={**canonical,'_mode':mode,'_snapshot':{'asset':asset,'seed':seed}}
        else:
            mode = "research_water_balance"
            request_record = {**canonical, "_mode": mode}
        old = database.scalar(select(Analysis).where(Analysis.workspace_id == session.workspace_id, Analysis.client_key == idempotency_key))
        if old:
            if old.fingerprint != fingerprint: raise problem(409, "Цей ключ ідемпотентності вже використано з іншими даними.")
            return JSONResponse(status_code=200, content={"id":old.id,"run_id":old.run_id,"status":old.status,"mode":json.loads(old.request_json).get('_mode','unknown'),"reused":True,**canonical})
        if data_mode == "public_data":
            consume_source_budget(session.workspace_id)
        item = Analysis(id="job_" + uuid.uuid4().hex, workspace_id=session.workspace_id, client_key=idempotency_key, fingerprint=fingerprint, run_id="run_" + uuid.uuid4().hex, status="queued", request_json=serialise(request_record))
        database.add(item); audit(database, session, "create_analysis", item.id, canonical); database.commit()
        # Small delay preserves a usable cooperative-cancel window. The worker uses
        # a new DB session and does not synthesize an assessment if science is absent.
        threading.Timer(0.2, execute_job, args=(item.id,)).start()
        return {"id":item.id,"run_id":item.run_id,"status":item.status,"mode":mode,"reused":False,**canonical}

    @app.get("/api/v1/jobs/{ident}")
    def get_job(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        job = database.get(Analysis, ident)
        if not job or job.workspace_id != session.workspace_id: raise problem(404, "Завдання не знайдено.")
        return {"id": job.id, "run_id": job.run_id, "status": job.status, "stage": job.status}

    @app.post("/api/v1/jobs/{ident}/cancel", status_code=202)
    def cancel(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        job = database.get(Analysis, ident)
        if not job or job.workspace_id != session.workspace_id: raise problem(404, "Завдання не знайдено.")
        if job.status in {"published", "failed"}: raise problem(409, "Це завдання вже не можна скасувати.")
        changed=database.execute(update(Analysis).where(Analysis.id==job.id,Analysis.status.in_(['queued','running','cancelled'])).values(status='cancelled')).rowcount
        if not changed: database.rollback(); raise problem(409,'Завдання вже завершено.')
        audit(database,session,'cancel_analysis',ident); database.commit()
        return {"id": job.id, "status": job.status}

    @app.get("/api/v1/results/{run_id}")
    def result(run_id: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        job = database.scalar(select(Analysis).where(Analysis.workspace_id == session.workspace_id, Analysis.run_id == run_id))
        if not job or job.status != "published" or not job.assessment_json: raise problem(404, "Опублікований результат не знайдено.")
        eligibility = "withdrawn" if job.withdrawn_reason else "current"
        return {"served_at": utcnow().isoformat(), "eligibility": eligibility, "freshness": "current", "completeness": "partial", "manifest_digest": job.manifest_digest, "assessment": json.loads(job.assessment_json), "withdrawal_reason": job.withdrawn_reason}

    @app.get("/api/v1/results/{run_id}/manifest")
    def manifest(run_id: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        job = database.scalar(select(Analysis).where(Analysis.workspace_id == session.workspace_id, Analysis.run_id == run_id))
        if not job or job.status!='published' or not job.manifest_json: raise problem(404, "Маніфест не знайдено.")
        return {"manifest": json.loads(job.manifest_json), "digest": job.manifest_digest}

    @app.post("/api/v1/results/{run_id}/withdraw")
    def withdraw(run_id: str, payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        require({"engineer", "admin"}, session)
        job = database.scalar(select(Analysis).where(Analysis.workspace_id == session.workspace_id, Analysis.run_id == run_id))
        if not job or job.status != "published": raise problem(404, "Опублікований результат не знайдено.")
        reason = str(payload.get("reason", "")).strip()
        if not reason: raise problem(422, "Потрібна причина відкликання.")
        job.withdrawn_reason = reason; audit(database, session, "withdraw_result", run_id, {"reason": reason}); database.commit()
        return {"run_id": run_id, "withdrawn": True}

    def parse_import(fmt: str, raw: str) -> list[dict[str, Any]]:
        if len(raw.encode()) > MAX_JSON: raise problem(413, "Імпорт перевищує дозволений розмір.")
        try:
            if fmt == "csv": return list(csv.DictReader(io.StringIO(raw)))
            parsed = strict_json(raw)
            if fmt == "geojson":
                if parsed.get("type") != "FeatureCollection": raise ValueError
                return [{**f.get("properties", {}), "geometry": f.get("geometry")} for f in parsed.get("features", [])]
            if fmt == "json": return parsed if isinstance(parsed, list) else [parsed]
        except (ValueError, json.JSONDecodeError, AttributeError):
            raise problem(422, "Неможливо прочитати імпортований формат.")
        raise problem(422, "Підтримуються лише CSV, GeoJSON або JSON.")

    @app.post("/api/v1/imports", status_code=201)
    def imports(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        resource, fmt, raw = payload.get("resource"), payload.get("format"), payload.get("data")
        if resource not in RESOURCE_NAMES or fmt not in {"csv", "geojson", "json"} or not isinstance(raw, str): raise problem(422, "Некоректний опис імпорту.")
        require({'engineer','admin'},session)
        rows = parse_import(fmt, raw); errors = []
        if len(rows)>5000 or any(not isinstance(row,dict) for row in rows):
            raise problem(422,'Імпорт має містити не більше 5000 об’єктів.')
        if resource == "assets":
            for n, row in enumerate(rows, 1):
                try:
                    if fmt == "csv": row["geometry"] = {"type": "Point", "coordinates": [float(row.pop("longitude")), float(row.pop("latitude"))]}
                    if not row.get("id") or not row.get("name") or not row.get("type"): raise ValueError
                    geom=row.get('geometry')
                    if not isinstance(geom,dict) or geom.get('type')!='Point': raise ValueError
                    coords=geom.get('coordinates')
                    if not isinstance(coords,list) or len(coords)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in coords): raise ValueError
                    if not -180<=coords[0]<=180 or not -90<=coords[1]<=90: raise ValueError
                    row['synthetic']=True
                    row.setdefault('condition','unknown')
                    row.setdefault('source_ref','user-import/unreviewed')
                except (ValueError, TypeError, KeyError): errors.append({"row": n, "message": "Для об’єкта потрібні id, name, type та коректна геометрія."})
        for n, row in enumerate(rows, 1):
            try:
                validate_resource_payload(resource, row)
            except HTTPException as exc:
                errors.append({"row": n, "message": exc.detail})
        item = ImportBatch(id="imp_" + uuid.uuid4().hex, workspace_id=session.workspace_id, resource=resource, fmt=fmt, digest=sha(raw.encode()), rows=serialise(rows), status="invalid" if errors else "preview")
        database.add(item); audit(database, session, "preview_import", item.id, {"errors": len(errors)}); database.commit()
        return {"id": item.id, "status": "preview", "rows": len(rows), "errors": errors}

    @app.post("/api/v1/imports/{ident}/commit")
    def commit_import(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        item = database.get(ImportBatch, ident)
        if not item or item.workspace_id != session.workspace_id: raise problem(404, "Імпорт не знайдено.")
        require({'engineer','admin'},session)
        if item.status == 'invalid': raise problem(409,'Імпорт містить помилки. Виправте файл і створіть новий перегляд.')
        if item.status == "committed": return {"id": item.id, "status": "committed", "deduped": True}
        rows = json.loads(item.rows)
        for value in rows:
            validate_resource_payload(item.resource, value)
            existing = database.scalar(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.kind == item.resource, Resource.logical_id == str(value.get("id"))))
            if not existing: create_resource(database, session, item.resource, value, imported=True)
        item.status = "committed"; audit(database, session, "commit_import", ident, {"digest": item.digest}); database.commit()
        return {"id": item.id, "status": "committed", "deduped": False}

    @app.post("/api/v1/uploads", status_code=201)
    async def upload(file: UploadFile = File(...), database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        raw = await file.read(MAX_IMAGE + 1)
        if len(raw) > MAX_IMAGE: raise problem(413, "Файл перевищує 20 МіБ.")
        try:
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>40_000_000: raise problem(422,'Зображення має забагато пікселів.')
            image.verify()
            from PIL import ImageOps
            image=ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
        except (UnidentifiedImageError, OSError): raise problem(422, "Дозволені лише коректні растрові зображення.")
        if image.width * image.height > 40_000_000: raise problem(422, "Зображення має забагато пікселів.")
        target = data_dir / "uploads"; target.mkdir(exist_ok=True)
        ident = "upl_" + uuid.uuid4().hex; path = target / f"{ident}.jpg"; image.save(path, "JPEG", quality=90, optimize=True)
        blob = Blob(id=ident, workspace_id=session.workspace_id, path=str(path), digest=sha(path.read_bytes()), size=path.stat().st_size, mime="image/jpeg")
        database.add(blob); audit(database, session, "upload", ident); database.commit()
        return {"id": ident, "sha256": blob.digest, "size": blob.size, "mime": blob.mime, "status": "stored"}

    @app.get("/api/v1/uploads/{ident}")
    def read_upload(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        blob = database.get(Blob, ident)
        if not blob or blob.workspace_id != session.workspace_id or not Path(blob.path).is_file(): raise problem(404, "Файл не знайдено.")
        return FileResponse(blob.path, media_type=blob.mime, headers={"Cache-Control": "private, no-cache"})

    def safe_csv(value: Any) -> str:
        if isinstance(value,(int,float)):
            return str(value)
        text = '' if value is None else str(value)
        return "'" + text if text.lstrip(' \t\r\n')[:1] in {'=','+','-','@'} else text

    @app.post("/api/v1/exports", status_code=201)
    def exports(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        fmt, scope = payload.get("format"), payload.get("scope", "assets")
        if fmt not in {"csv", "geojson", "pdf"} or scope not in RESOURCE_NAMES | READ_ONLY_SEED: raise problem(422, "Непідтримуваний формат або область експорту.")
        rows = [row_data(r) for r in database.scalars(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.kind == scope, Resource.tombstoned == 0)).all()]
        ident = "exp_" + uuid.uuid4().hex; out = data_dir / "exports"; out.mkdir(exist_ok=True)
        if fmt == "csv":
            if scope == 'assets':
                rows = [{**row,**({'longitude':row['geometry']['coordinates'][0],'latitude':row['geometry']['coordinates'][1]} if isinstance(row.get('geometry'),dict) and row['geometry'].get('type')=='Point' else {})} for row in rows]
            path = out / f"{ident}.csv"; fields = sorted({k for row in rows for k in row if k != "geometry"}) or ["id"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows([{k: safe_csv(v) for k, v in row.items() if k in fields} for row in rows])
            mime = "text/csv"
        elif fmt == "geojson":
            path = out / f"{ident}.geojson"; path.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {k:v for k,v in r.items() if k != "geometry"}, "geometry": r.get("geometry")} for r in rows]}, ensure_ascii=False), encoding="utf-8"); mime = "application/geo+json"
        else:
            path = out / f"{ident}.pdf"
            font_path=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
            if not font_path.is_file(): raise problem(503,'Український шрифт звіту недоступний; PDF не створено.')
            if 'GS-Ukrainian' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('GS-Ukrainian',str(font_path)))
            c=canvas.Canvas(str(path));c.setTitle('GroundSense — демонстраційний реєстр');c.setFont('GS-Ukrainian',10)
            y=800
            title = 'GroundSense — синтетичний звіт' if data_mode == 'synthetic' else 'GroundSense — реєстр відкритих даних'
            description = 'Вигадані об’єкти. Прохідність не підтверджено.' if data_mode == 'synthetic' else 'Записи робочого простору. Прохідність не підтверджено.'
            lines=[title,description,f'Сформовано: {utcnow().isoformat()}',f'Область: {scope}; записів: {len(rows)}','Реєстровий звіт не є опублікованою оцінкою прохідності.', 'Строк дії посилання: одна година. Завантажені байти не відкликаються.','']
            for row in rows:
                lines.append(str(row.get('id',''))+' · '+str(row.get('name') or row.get('procedure') or row.get('note') or '')[:72])
                lines.append('Версія: '+str(row.get('version','—'))+'; стан: '+str(row.get('condition') or row.get('status') or 'невідомо'))
            for line in lines:
                if y<55: c.showPage();c.setFont('GS-Ukrainian',10);y=800
                c.drawString(35,y,line); y-=18
            c.save(); mime='application/pdf' 
        expiry = utcnow() + timedelta(hours=1); blob = Blob(id=ident, workspace_id=session.workspace_id, path=str(path), digest=sha(path.read_bytes()), size=path.stat().st_size, mime=mime, expires_at=expiry)
        database.add(blob); audit(database, session, "export", ident, {"format": fmt, "scope": scope}); database.commit()
        return {"id": ident, "download_url": f"/api/v1/exports/{ident}/download", "sha256": blob.digest, "expires_at": expiry.isoformat()}

    @app.get("/api/v1/exports/{ident}/download")
    def download_export(ident: str, database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        blob = database.get(Blob, ident)
        if not blob or blob.workspace_id != session.workspace_id or not blob.expires_at or as_utc(blob.expires_at) < utcnow(): raise problem(404, "Експорт недоступний або строк дії минув.")
        return FileResponse(blob.path, media_type=blob.mime, filename=Path(blob.path).name, headers={"Cache-Control": "private, no-cache"})

    @app.get("/api/v1/offline-package")
    def offline(database: Session = Depends(db), session: BrowserSession = Depends(session_for)):
        rows = [{"kind": r.kind, "data": row_data(r)} for r in database.scalars(select(Resource).where(Resource.workspace_id == session.workspace_id, Resource.tombstoned == 0)).all()]
        package = {"workspace": session.workspace_id, "created_at": utcnow().isoformat(), "expires_at": (utcnow() + timedelta(hours=24)).isoformat(), "freshness": "offline", "resources": rows}
        package["digest"] = sha(jcs(package)); return package

    @app.post("/api/v1/offline-package/restore")
    def restore_offline(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        if payload.get('freshness')!='offline': raise problem(422,'Потрібен офлайн-пакет із явним статусом застарілості.')
        if payload.get('workspace')!=session.workspace_id: raise problem(404,'Пакет іншого простору недоступний.')
        content={k:v for k,v in payload.items() if k!='digest'}
        try:
            if not secrets.compare_digest(str(payload.get('digest','')),sha(jcs(content))): raise ValueError
            expired=datetime.fromisoformat(str(payload['expires_at']).replace('Z','+00:00'))<utcnow()
        except (ValueError,TypeError,KeyError): raise problem(409,'Контрольна сума або строк дії пакета некоректні.')
        audit(database,session,'validate_offline','offline-package',{'expired':expired});database.commit()
        return {'status':'validated','freshness':'offline','expired':expired,'readonly':True,'model_approval':False,'warning':'Перевірено контрольну суму. Дані не відновлюються в поточний реєстр і не підтверджують поточний стан.'}

    @app.post("/api/v1/sources/{ident}/sync")
    def sync_source(ident: str, session: BrowserSession = Depends(mutate)):
        raise problem(409, "Адаптер джерела не налаштований; синхронізацію не виконано.")

    @app.post("/api/v1/models/{ident}/approve")
    def approve_model(ident: str, session: BrowserSession = Depends(mutate)):
        require({"admin"}, session); raise problem(409, "Синтетичні дані не можуть затвердити виробничу модель.")

    @app.post("/api/v1/validation/evaluate")
    def validation(payload: dict[str,Any],database: Session=Depends(db),session: BrowserSession=Depends(mutate)):
        require({'engineer','admin'},session)
        rows,config=payload.get('rows'),payload.get('config')
        if not isinstance(rows,list) or len(rows)>5000 or any(not isinstance(row,dict) for row in rows) or not isinstance(config,dict):
            raise problem(422,'Потрібні масив rows (до 5000) та об’єкт config.')
        from packages.science.engine import evaluate_validation
        try: evaluated=evaluate_validation(rows,config)
        except (ValueError,TypeError,OverflowError) as exc: raise problem(422,'Некоректні дані валідації: '+str(exc))
        report={**evaluated,'id':'val_'+uuid.uuid4().hex,'model_approval':False,'evidence_verified':False,'computed_at':utcnow().isoformat(),'note':'Діагностика наданого набору не затверджує модель або виробничий домен.'}
        audit(database,session,'validation_evaluate',report['id'],{'status':report['status'],'rows':len(rows)})
        database.commit()
        return report

    @app.post('/api/v1/science/research')
    def research(payload:dict[str,Any],database:Session=Depends(db),session:BrowserSession=Depends(mutate)):
        require({'engineer','admin'},session)
        from packages.science.engine import research_run
        try: report=research_run(payload.get('params',{}),payload.get('initial',{}),payload.get('forcing',[]),payload.get('thermal_screen',{}))
        except (ValueError,TypeError,OverflowError) as exc: raise problem(422,'Некоректний дослідницький набір: '+str(exc))
        report.update({'model_approval':False,'production_eligible':False,'synthetic':True})
        audit(database,session,'science_research','warm-soil-6h/v1',{'status':report['status']})
        database.commit()
        return report

    @app.post("/api/v1/data/validate")
    def validate_data_preview(payload: dict[str, Any], database: Session = Depends(db), session: BrowserSession = Depends(mutate)):
        """Normalize a supplied fixture only; this does not ingest or assimilate it."""
        product = payload.get("product")
        source_payload = payload.get("payload")
        if not isinstance(source_payload, dict):
            raise problem(422, "Потрібен об’єкт payload для перевірки даних.")
        try:
            from packages.ingestion.adapters import satellite_evidence, soilgrids_profile, terrain_features
            if product == "soilgrids":
                normalized = soilgrids_profile(source_payload)
            elif product == "dem":
                normalized = terrain_features(source_payload)
            elif product in {"sentinel-1", "sentinel-2", "clms-swi"}:
                normalized = satellite_evidence({**source_payload, "product": product})
            else:
                raise ValueError("Невідомий продукт для перевірки")
        except ValueError as exc:
            raise problem(422, str(exc))
        audit(database, session, "validate_data_preview", f"data/{product}", {"transform": normalized.get("transform_version")})
        database.commit()
        return {"status": "preview", "normalized": normalized, "synthetic": True, "note": "Це локальна перевірка; живе надходження та асиміляцію не виконано."}

    @app.get("/api/v1/health")
    def health():
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text('SELECT 1'))
        return {"status":"ok","storage":{"database":engine.dialect.name,"artifacts":"private_local_filesystem"},"version":"0.2.0-prototype","auth_mode":"anonymous_isolated_sandbox","production_ready":False}

    # Register generic CRUD last so fixed routes (audit, analyses, uploads, etc.)
    # always win route resolution.
    app.add_api_route("/api/v1/{resource}", list_resources, methods=["GET"])
    app.add_api_route("/api/v1/{resource}/{ident}", read_resource, methods=["GET"])
    app.add_api_route("/api/v1/{resource}", post_resource, methods=["POST"], status_code=201)
    app.add_api_route("/api/v1/{resource}/{ident}", patch_resource, methods=["PATCH"])
    app.add_api_route("/api/v1/{resource}/{ident}", delete_resource, methods=["DELETE"])

    # Static assets are served only from the compiled web directory, never the
    # repository/runtime. Unknown API paths must remain JSON404, not SPA200.
    from fastapi.staticfiles import StaticFiles
    dist = ROOT / 'apps' / 'web' / 'dist'
    if dist.is_dir():
        app.mount('/assets', StaticFiles(directory=str(dist / 'assets')), name='web-assets')

    @app.get('/{web_path:path}', include_in_schema=False)
    def serve_ui(web_path: str):
        if web_path.startswith(('api/', '__internal/')):
            raise problem(404, 'Маршрут API не знайдено.')
        target = (dist / web_path).resolve()
        if target.is_relative_to(dist.resolve()) and target.is_file():
            return FileResponse(target)
        index = dist / 'index.html'
        if not index.is_file():
            raise problem(503, 'Інтерфейс ще не зібрано.')
        return FileResponse(index, media_type='text/html', headers={'Cache-Control':'no-cache'})

    return app


app = create_app()
