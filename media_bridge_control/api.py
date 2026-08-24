"""HTTPS-only Admin API skeleton with server-side session enforcement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from media_bridge_control.audit import AuditEventWriter, OperationalEventWriter
from media_bridge_control.bootstrap import (
    AuthenticationError,
    BootstrapError,
    ControlPlaneError,
    ControlPlaneService,
    Principal,
)
from media_bridge_control.configuration import ConfigurationError, ConfigurationService
from media_bridge_control.connections import ConnectionService, ConnectionServiceError
from media_bridge_control.credentials import CredentialError, CredentialService
from media_bridge_control.gateway_client import (
    GatewayClient,
    GatewayClientError,
    HttpGatewayClient,
)
from media_bridge_control.schemas import (
    BootstrapRequest,
    ConnectionCreate,
    ConnectionUpdate,
    CredentialCreate,
    LoginRequest,
    ModelCapabilityCreate,
    ModelCapabilityUpdate,
    PolicyCreate,
    PolicyUpdate,
    ProviderCreate,
    ProviderUpdate,
    PublishSnapshotRequest,
    RecoveryRequest,
    TestLabPreviewRequest,
    TestLabRunRequest,
    UserCreate,
    UserUpdate,
)
from media_bridge_control.secrets import GatewaySecretResolver, SecretResolutionError
from media_bridge_control.snapshots import SnapshotPublisher, SnapshotPublishError
from media_bridge_control.test_lab import (
    AdminActionRateLimiter,
    TestLabError,
    TestLabService,
)

Handler = Callable[[Request], Awaitable[Response]]


def _error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status_code)


async def _json(
    request: Request,
    schema: type[Any],
    *,
    max_bytes: int = 64 * 1024,
) -> Any:
    if request.headers.get("content-type", "").partition(";")[0].lower() != "application/json":
        raise ControlPlaneError("unsupported_content_type")
    body = await request.body()
    if len(body) > max_bytes:
        raise ControlPlaneError("request_too_large")
    try:
        return schema.model_validate_json(body)
    except (ValidationError, ValueError) as error:
        raise ControlPlaneError("invalid_request") from error


def build_control_app(
    *,
    service: ControlPlaneService,
    allowed_origin: str,
    allowed_host: str,
    snapshot_publisher: SnapshotPublisher | None = None,
    gateway_client: GatewayClient | None = None,
    secret_resolver: GatewaySecretResolver | None = None,
    action_rate_limiter: AdminActionRateLimiter | None = None,
) -> Starlette:
    configuration = ConfigurationService(service.database)
    credentials = CredentialService(
        database=service.database,
        security=service.security,
        now=service.now,
    )
    audit = AuditEventWriter(service.database)
    events = OperationalEventWriter(service.database)
    connections = ConnectionService(service.database)
    gateway = gateway_client or HttpGatewayClient()
    resolver = secret_resolver or GatewaySecretResolver()
    test_lab = TestLabService(
        connections=connections,
        gateway_client=gateway,
        secret_resolver=resolver,
    )
    action_limiter = action_rate_limiter or AdminActionRateLimiter()

    def secure_request(request: Request) -> Response | None:
        host = request.headers.get("host", "").partition(":")[0].lower()
        if request.url.scheme != "https":
            return _error("https_required", 400)
        if host != allowed_host.lower() or request.headers.get("origin") != allowed_origin:
            return _error("origin_rejected", 403)
        return None

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def bootstrap(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        raw_token = request.headers.get("x-bootstrap-token", "")
        try:
            body = await _json(request, BootstrapRequest)
            result = await run_in_threadpool(
                service.complete_bootstrap,
                token=raw_token,
                username=body.username,
                password=body.password,
            )
        except (BootstrapError, ControlPlaneError) as error:
            status = 409 if error.code == "already_initialized" else 400
            return _error(error.code, status)
        return JSONResponse(
            {
                "user_id": result.user_id,
                "role": result.role,
                "recovery_codes": result.recovery_codes,
            },
            status_code=201,
        )

    async def login(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        try:
            body = await _json(request, LoginRequest)
            client_host = request.client.host if request.client is not None else "unknown"
            result = await run_in_threadpool(
                service.login,
                username=body.username,
                password=body.password,
                client_key=client_host,
            )
        except AuthenticationError as error:
            status = 429 if error.code == "login_rate_limited" else 401
            return _error(error.code, status)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        response = JSONResponse(
            {
                "username": result.username,
                "role": result.role,
                "csrf_token": result.csrf_token,
            }
        )
        response.set_cookie(
            "mb_admin_session",
            result.session_token,
            max_age=int(service.SESSION_TTL.total_seconds()),
            path="/admin/v1",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    async def me(request: Request) -> Response:
        raw = request.cookies.get("mb_admin_session", "")
        try:
            principal = await run_in_threadpool(service.authenticate, raw)
        except AuthenticationError:
            return _error("unauthorized", 401)
        return JSONResponse({"username": principal.username, "role": principal.role})

    async def recover(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        try:
            body = await _json(request, RecoveryRequest)
            client_host = request.client.host if request.client is not None else "unknown"
            await run_in_threadpool(
                service.recover_password,
                username=body.username,
                recovery_code=body.recovery_code,
                new_password=body.new_password,
                client_key=client_host,
            )
        except AuthenticationError as error:
            status = 429 if error.code == "recovery_rate_limited" else 400
            return _error(error.code, status)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        return Response(status_code=204)

    async def logout(request: Request) -> Response:
        if rejected := secure_request(request):
            return rejected
        raw = request.cookies.get("mb_admin_session", "")
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf:
            return _error("csrf_rejected", 403)
        try:
            await run_in_threadpool(
                service.logout,
                session_token=raw,
                csrf_token=csrf,
            )
        except AuthenticationError as error:
            status = 403 if error.code == "csrf_rejected" else 401
            return _error(error.code, status)
        response = Response(status_code=204)
        response.delete_cookie("mb_admin_session", path="/admin/v1")
        return response

    async def authorize(
        request: Request,
        *,
        roles: frozenset[str],
        require_csrf: bool = False,
    ) -> tuple[Principal | None, Response | None]:
        if require_csrf and (rejected := secure_request(request)):
            return None, rejected
        raw = request.cookies.get("mb_admin_session", "")
        csrf = request.headers.get("x-csrf-token", "")
        try:
            if require_csrf:
                if not csrf:
                    return None, _error("csrf_rejected", 403)
                principal = await run_in_threadpool(
                    service.authenticate_with_csrf,
                    session_token=raw,
                    csrf_token=csrf,
                )
            else:
                principal = await run_in_threadpool(service.authenticate, raw)
        except AuthenticationError as error:
            status = 403 if error.code == "csrf_rejected" else 401
            return None, _error(error.code, status)
        if principal.role not in roles:
            return None, _error("forbidden", 403)
        return principal, None

    async def users(request: Request) -> Response:
        writable = request.method == "POST"
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(configuration.list_users))
        if principal is None:
            return _error("unauthorized", 401)
        try:
            body = await _json(request, UserCreate)
            created = await run_in_threadpool(
                service.create_user,
                username=body.username,
                password=body.password,
                role=body.role,
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="user.created",
                target_type="user",
                target_id=created.user_id,
                details={"role": created.role, "status": "created"},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        return JSONResponse(
            {
                "user_id": created.user_id,
                "username": created.username,
                "role": created.role,
            },
            status_code=201,
        )

    async def user_item(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        try:
            body = await _json(request, UserUpdate)
            updated = await run_in_threadpool(
                service.update_user,
                user_id=str(request.path_params["item_id"]),
                password=body.password,
                role=body.role,
                is_active=body.is_active,
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="user.updated",
                target_type="user",
                target_id=updated.user_id,
                details={"role": updated.role, "status": "updated"},
            )
        except ControlPlaneError as error:
            status = 409 if error.code == "last_admin_required" else 400
            if error.code == "user_not_found":
                status = 404
            return _error(error.code, status)
        return JSONResponse(
            {
                "user_id": updated.user_id,
                "username": updated.username,
                "role": updated.role,
            }
        )

    async def providers(request: Request) -> Response:
        writable = request.method == "POST"
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}) if writable else frozenset(
                {"admin", "operator", "viewer"}
            ),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(configuration.list_providers))
        try:
            body = await _json(request, ProviderCreate)
            result = await run_in_threadpool(configuration.create_provider, body)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            return _error(error.code, 409)
        return JSONResponse(result, status_code=201)

    async def provider_item(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        provider_id = request.path_params["item_id"]
        try:
            if request.method == "PATCH":
                body = await _json(request, ProviderUpdate)
                if "secret_ref" in body.model_fields_set and principal.role != "admin":
                    return _error("forbidden", 403)
                result = await run_in_threadpool(
                    configuration.update_provider,
                    provider_id,
                    body,
                )
                return JSONResponse(result)
            await run_in_threadpool(configuration.delete_provider, provider_id)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            status = 404 if error.code == "configuration_not_found" else 409
            return _error(error.code, status)
        return Response(status_code=204)

    async def models(request: Request) -> Response:
        writable = request.method == "POST"
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}) if writable else frozenset(
                {"admin", "operator", "viewer"}
            ),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(configuration.list_models))
        try:
            body = await _json(request, ModelCapabilityCreate)
            result = await run_in_threadpool(configuration.create_model, body)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            return _error(error.code, 409)
        return JSONResponse(result, status_code=201)

    async def model_item(request: Request) -> Response:
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        model_id = request.path_params["item_id"]
        try:
            if request.method == "PATCH":
                body = await _json(request, ModelCapabilityUpdate)
                result = await run_in_threadpool(
                    configuration.update_model,
                    model_id,
                    body,
                )
                return JSONResponse(result)
            await run_in_threadpool(configuration.delete_model, model_id)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            status = 404 if error.code == "configuration_not_found" else 409
            return _error(error.code, status)
        return Response(status_code=204)

    async def policies(request: Request) -> Response:
        writable = request.method == "POST"
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}) if writable else frozenset(
                {"admin", "operator", "viewer"}
            ),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(configuration.list_policies))
        try:
            body = await _json(request, PolicyCreate)
            result = await run_in_threadpool(configuration.create_policy, body)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            return _error(error.code, 409)
        return JSONResponse(result, status_code=201)

    async def policy_item(request: Request) -> Response:
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        policy_id = request.path_params["item_id"]
        try:
            if request.method == "PATCH":
                body = await _json(request, PolicyUpdate)
                result = await run_in_threadpool(
                    configuration.update_policy,
                    policy_id,
                    body,
                )
                return JSONResponse(result)
            await run_in_threadpool(configuration.delete_policy, policy_id)
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            status = 404 if error.code == "configuration_not_found" else 409
            return _error(error.code, status)
        return Response(status_code=204)

    async def credential_collection(request: Request) -> Response:
        writable = request.method == "POST"
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(credentials.list))
        if principal is None:
            return _error("unauthorized", 401)
        try:
            body = await _json(request, CredentialCreate)
            issued = await run_in_threadpool(
                credentials.issue,
                name=body.name,
                scopes=body.scopes,
                expires_at=body.expires_at,
                created_by=principal.user_id,
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="credential.issued",
                target_type="credential",
                target_id=issued.selector,
                details={
                    "name": issued.name,
                    "scope_count": len(issued.scopes),
                    "status": "issued",
                },
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except CredentialError as error:
            return _error(error.code, 400)
        return JSONResponse(
            {
                "credential": issued.credential,
                "selector": issued.selector,
                "name": issued.name,
                "scopes": issued.scopes,
                "expires_at": issued.expires_at.isoformat() if issued.expires_at else None,
            },
            status_code=201,
        )

    async def credential_item(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        selector = request.path_params["selector"]
        try:
            await run_in_threadpool(credentials.revoke, selector)
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="credential.revoked",
                target_type="credential",
                target_id=selector,
                details={"status": "revoked"},
            )
        except CredentialError as error:
            status = 404 if error.code == "credential_not_found" else 400
            return _error(error.code, status)
        return Response(status_code=204)

    async def connection_collection(request: Request) -> Response:
        writable = request.method == "POST"
        principal, rejected = await authorize(
            request,
            roles=(
                frozenset({"admin"})
                if writable
                else frozenset({"admin", "operator", "viewer"})
            ),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if not writable:
            return JSONResponse(await run_in_threadpool(connections.list))
        if principal is None:
            return _error("unauthorized", 401)
        try:
            body = await _json(request, ConnectionCreate)
            created = await run_in_threadpool(
                connections.create,
                body,
                created_by=principal.user_id,
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="connection.created",
                target_type="connection",
                target_id=created["id"],
                details={"name": created["name"], "status": "created"},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConnectionServiceError as error:
            status = 409 if error.code == "connection_conflict" else 400
            return _error(error.code, status)
        return JSONResponse(created, status_code=201)

    async def connection_item(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        connection_id = str(request.path_params["item_id"])
        try:
            if request.method == "PATCH":
                body = await _json(request, ConnectionUpdate)
                updated = await run_in_threadpool(
                    connections.update,
                    connection_id,
                    body,
                )
                await run_in_threadpool(
                    audit.write,
                    actor_id=principal.user_id,
                    action="connection.updated",
                    target_type="connection",
                    target_id=connection_id,
                    details={"status": "updated"},
                )
                return JSONResponse(updated)
            await run_in_threadpool(
                connections.revoke,
                connection_id,
                revoked_at=service.now(),
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="connection.revoked",
                target_type="connection",
                target_id=connection_id,
                details={"status": "revoked"},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConnectionServiceError as error:
            status = 404 if error.code == "connection_not_found" else 409
            return _error(error.code, status)
        return Response(status_code=204)

    async def connection_test(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        if not action_limiter.allow(f"{principal.user_id}:connection-test"):
            return _error("rate_limited", 429)
        if await request.body() not in {b"", b"{}"}:
            return _error("invalid_request", 400)
        connection_id = str(request.path_params["item_id"])
        credential = ""
        try:
            runtime_connection = await run_in_threadpool(
                connections.runtime,
                connection_id,
            )
            if not runtime_connection.enabled or runtime_connection.revoked:
                raise ConnectionServiceError("connection_unavailable")
            credential = resolver.resolve(
                connections.secret_reference(runtime_connection)
            )
            await gateway.status(
                base_url=runtime_connection.gateway_url,
                credential=credential,
            )
            result = await run_in_threadpool(
                connections.record_test_result,
                connection_id,
                succeeded=True,
                error_code=None,
                tested_at=service.now(),
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="connection.tested",
                target_type="connection",
                target_id=connection_id,
                details={"status": "ready"},
            )
            return JSONResponse(result)
        except (GatewayClientError, SecretResolutionError) as error:
            await run_in_threadpool(
                connections.record_test_result,
                connection_id,
                succeeded=False,
                error_code=error.code,
                tested_at=service.now(),
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="connection.test_failed",
                target_type="connection",
                target_id=connection_id,
                details={"reason_code": error.code, "status": "failed"},
            )
            return _error(error.code, 502)
        except ConnectionServiceError as error:
            status = 404 if error.code == "connection_not_found" else 409
            return _error(error.code, status)
        finally:
            credential = ""

    async def test_lab_preview(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        if not action_limiter.allow(f"{principal.user_id}:preview"):
            return _error("rate_limited", 429)
        target_id: str | None = None
        try:
            body = await _json(request, TestLabPreviewRequest, max_bytes=3 * 1024 * 1024)
            target_id = str(body.connection_id)
            result = await test_lab.preview(body)
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="test_lab.previewed",
                target_type="connection",
                target_id=str(body.connection_id),
                details={"status": str(result.get("action", "completed"))},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except TestLabError as error:
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="test_lab.preview_failed",
                target_type="connection",
                target_id=target_id,
                details={"reason_code": error.code, "status": "failed"},
            )
            status = 404 if error.code == "connection_not_found" else 502
            if error.code in {"invalid_media_base64", "media_size_invalid"}:
                status = 400
            return _error(error.code, status)
        return JSONResponse(result)

    async def test_lab_run(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        if not action_limiter.allow(f"{principal.user_id}:run"):
            return _error("rate_limited", 429)
        target_id: str | None = None
        try:
            body = await _json(request, TestLabRunRequest, max_bytes=3 * 1024 * 1024)
            target_id = str(body.connection_id)
            result = await test_lab.run(body)
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="test_lab.executed",
                target_type="connection",
                target_id=str(body.connection_id),
                details={"status": "completed"},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except TestLabError as error:
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="test_lab.execute_failed",
                target_type="connection",
                target_id=target_id,
                details={"reason_code": error.code, "status": "failed"},
            )
            status = 404 if error.code == "connection_not_found" else 502
            if error.code in {"invalid_media_base64", "media_size_invalid"}:
                status = 400
            return _error(error.code, status)
        return JSONResponse(result)

    async def snapshots(request: Request) -> Response:
        writable = request.method == "POST"
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=writable,
        )
        if rejected is not None:
            return rejected
        if snapshot_publisher is None:
            return _error("snapshot_unavailable", 503)
        if not writable:
            return JSONResponse(await run_in_threadpool(snapshot_publisher.list))
        if principal is None:
            return _error("unauthorized", 401)
        try:
            request_body = await _json(request, PublishSnapshotRequest)
            body = await run_in_threadpool(
                configuration.get_draft_body,
                request_body.draft_id,
            )
            published = await run_in_threadpool(
                snapshot_publisher.publish,
                body,
                source_draft_id=request_body.draft_id,
                created_by=UUID(principal.user_id),
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="snapshot.published",
                target_type="snapshot",
                target_id=str(published.snapshot_id),
                details={"version": published.version, "status": "published"},
            )
        except ControlPlaneError as error:
            return _error(error.code, 400)
        except ConfigurationError as error:
            status = 404 if error.code == "draft_not_found" else 409
            return _error(error.code, status)
        except SnapshotPublishError:
            return _error("snapshot_publish_failed", 500)
        return JSONResponse(published.model_dump(mode="json"), status_code=201)

    async def snapshot_rollback(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if snapshot_publisher is None:
            return _error("snapshot_unavailable", 503)
        if principal is None:
            return _error("unauthorized", 401)
        try:
            version = int(request.path_params["version"])
            published = await run_in_threadpool(
                snapshot_publisher.rollback,
                version,
                created_by=UUID(principal.user_id),
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="snapshot.rolled_back",
                target_type="snapshot",
                target_id=str(published.snapshot_id),
                details={"before_id": str(version), "version": published.version},
            )
        except (ValueError, SnapshotPublishError):
            return _error("snapshot_rollback_failed", 400)
        return JSONResponse(published.model_dump(mode="json"), status_code=201)

    async def validate_draft(request: Request) -> Response:
        principal, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator"}),
            require_csrf=True,
        )
        if rejected is not None:
            return rejected
        if principal is None:
            return _error("unauthorized", 401)
        try:
            if await request.body() not in {b"", b"{}"}:
                return _error("invalid_request", 400)
            draft = await run_in_threadpool(
                configuration.create_validated_draft,
                created_by=principal.user_id,
            )
            await run_in_threadpool(
                audit.write,
                actor_id=principal.user_id,
                action="draft.validated",
                target_type="draft",
                target_id=draft["draft_id"],
                details={"version": draft["revision"], "status": "validated"},
            )
        except ConfigurationError as error:
            return _error(error.code, 409)
        return JSONResponse(draft, status_code=201)

    async def audit_events(request: Request) -> Response:
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator", "viewer"}),
        )
        if rejected is not None:
            return rejected
        return JSONResponse(await run_in_threadpool(audit.list))

    async def operational_events(request: Request) -> Response:
        _, rejected = await authorize(
            request,
            roles=frozenset({"admin", "operator", "viewer"}),
        )
        if rejected is not None:
            return rejected
        return JSONResponse(await run_in_threadpool(events.list))

    return Starlette(
        routes=[
            Route("/admin/v1/health", health, methods=["GET"]),
            Route("/admin/v1/bootstrap", bootstrap, methods=["POST"]),
            Route("/admin/v1/auth/login", login, methods=["POST"]),
            Route("/admin/v1/auth/recover", recover, methods=["POST"]),
            Route("/admin/v1/auth/logout", logout, methods=["POST"]),
            Route("/admin/v1/me", me, methods=["GET"]),
            Route("/admin/v1/users", users, methods=["GET", "POST"]),
            Route(
                "/admin/v1/users/{item_id:uuid}",
                user_item,
                methods=["PATCH"],
            ),
            Route("/admin/v1/providers", providers, methods=["GET", "POST"]),
            Route(
                "/admin/v1/providers/{item_id:uuid}",
                provider_item,
                methods=["PATCH", "DELETE"],
            ),
            Route("/admin/v1/models", models, methods=["GET", "POST"]),
            Route(
                "/admin/v1/models/{item_id:uuid}",
                model_item,
                methods=["PATCH", "DELETE"],
            ),
            Route("/admin/v1/policies", policies, methods=["GET", "POST"]),
            Route(
                "/admin/v1/policies/{item_id:uuid}",
                policy_item,
                methods=["PATCH", "DELETE"],
            ),
            Route(
                "/admin/v1/credentials",
                credential_collection,
                methods=["GET", "POST"],
            ),
            Route(
                "/admin/v1/credentials/{selector:str}",
                credential_item,
                methods=["DELETE"],
            ),
            Route(
                "/admin/v1/connections",
                connection_collection,
                methods=["GET", "POST"],
            ),
            Route(
                "/admin/v1/connections/{item_id:uuid}",
                connection_item,
                methods=["PATCH", "DELETE"],
            ),
            Route(
                "/admin/v1/connections/{item_id:uuid}/test",
                connection_test,
                methods=["POST"],
            ),
            Route(
                "/admin/v1/test-lab/preview",
                test_lab_preview,
                methods=["POST"],
            ),
            Route(
                "/admin/v1/test-lab/run",
                test_lab_run,
                methods=["POST"],
            ),
            Route("/admin/v1/snapshots", snapshots, methods=["GET", "POST"]),
            Route("/admin/v1/drafts/validate", validate_draft, methods=["POST"]),
            Route(
                "/admin/v1/snapshots/{version:int}/rollback",
                snapshot_rollback,
                methods=["POST"],
            ),
            Route("/admin/v1/audit", audit_events, methods=["GET"]),
            Route("/admin/v1/events", operational_events, methods=["GET"]),
        ]
    )
