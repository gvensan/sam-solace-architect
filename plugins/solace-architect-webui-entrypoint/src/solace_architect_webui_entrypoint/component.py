"""SAM Gateway Component for the Solace Architect WebUI entrypoint.

Implements the BaseGatewayComponent contract:
- ``_extract_initial_claims``      — auth claims for incoming external events
- ``_start_listener`` / ``_stop_listener`` — lifecycle (HTTP server on/off)
- ``_translate_external_input``    — HTTP request body → A2A parts
- ``_send_update_to_external``     — streaming A2A status/artifact → browser SSE
- ``_send_final_response_to_external`` — final A2A Task → browser SSE
- ``_send_error_to_external``      — JSONRPCError → browser SSE

The HTTP server uses aiohttp for native async support + Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from aiohttp import web
from solace_agent_mesh.gateway.base.component import BaseGatewayComponent
from a2a.types import (
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    JSONRPCError,
    Part as A2APart,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
)

from solace_architect_webui_entrypoint.auth import (
    AuthState, add_auth_routes, ensure_initialized, install_middleware,
)
from solace_architect_webui_entrypoint.auth.middleware import SESSION_COOKIE
from solace_architect_webui_entrypoint.auth.sessions import validate_session
from solace_architect_webui_entrypoint.auth.db import user_to_claims
from solace_architect_webui_entrypoint.routes.api import API_ROUTES

log = logging.getLogger(__name__)


# Module-level discovery metadata — solace-ai-connector's Flow machinery reads
# this when instantiating the component class. Matches the cli-entrypoint pattern.
info = {
    "class_name": "SolaceArchitectWebuiComponent",
    "description": (
        "HTTP-SSE entrypoint component for Solace Architect. Serves the dashboard, "
        "intake form, audience-pack reports, and REST API; bridges browser/REST "
        "traffic to the SAOrchestratorAgent over A2A."
    ),
    "config_parameters": [],
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {"type": "object", "properties": {}},
}


def _webui_static_dir() -> Path:
    """Path to the bundled static dashboard + intake assets."""
    return Path(__file__).parent / "webui"


class SolaceArchitectWebuiComponent(BaseGatewayComponent):
    """WebUI entrypoint — bridges browser/REST traffic to SAM agents over A2A."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        log.info("%s Initializing Solace Architect WebUI entrypoint…", self.log_identifier)

        # Register the audience-pack renderer with blueprint_tools so the
        # /api/engagements/<eid>/exports/render endpoint can produce HTML
        # in-process. Without this, render_audience_pack() returns
        # ToolResult(ok=False, error="no renderer registered…"), the
        # endpoint returns null, and the WebUI's __renderPack click
        # handler crashes with "Cannot read properties of null (reading
        # 'paths')". The SABlueprintAgent process registers its own
        # renderer at agent boot — this registration covers the WebUI's
        # in-process direct-dispatch path (Audience Reports buttons).
        try:
            from solace_architect_core.tools.blueprint_tools import register_renderer
            from solace_architect_blueprint.report_generator import render_pack
            register_renderer(render_pack)
            log.info("%s Audience-pack renderer registered (solace-architect-blueprint plugin)",
                     self.log_identifier)
        except Exception as e:
            log.warning(
                "%s Could not register audience-pack renderer (%s) — Audience Reports buttons "
                "will surface a 'no renderer registered' error until the blueprint plugin is "
                "installed and importable.",
                self.log_identifier, e,
            )

        ac = self.get_config("adapter_config") or {}
        self._port: int = int(ac.get("port", 8080))
        self._host: str = ac.get("host", "0.0.0.0")
        self._show_status_updates: bool = bool(ac.get("show_status_updates", True))

        # Anchor SA's storage to SAM's artifact_service.base_path when SA_STORAGE_ROOT
        # isn't explicitly set. Without this, solace-architect-core falls back to a
        # cwd-relative "./sa-artifacts" and SAM's artifact service falls back to
        # "/tmp/sa-artifacts" — two different places for what should be the same
        # data. Setting the env var here (process-wide) means any SA agent plugin
        # running in the same SAM process inherits the same root.
        artifact_cfg = self.get_config("artifact_service") or {}
        artifact_base = artifact_cfg.get("base_path") or ""
        if artifact_base and not os.environ.get("SA_STORAGE_ROOT"):
            os.environ["SA_STORAGE_ROOT"] = str(artifact_base)
            log.info("%s SA_STORAGE_ROOT defaulted to artifact_service.base_path=%s",
                     self.log_identifier, artifact_base)

        # Auth state — local SQLite user DB.
        # DB path is configurable via WEBUI_USERS_DB env var; defaults under
        # SA_STORAGE_ROOT/__system__/users.db.
        storage_root = Path(os.environ.get("SA_STORAGE_ROOT", "/tmp/sa-artifacts"))
        default_db = storage_root / "__system__" / "users.db"
        db_path = Path(os.environ.get("WEBUI_USERS_DB", str(default_db)))

        require_auth = (os.environ.get("WEBUI_REQUIRE_AUTH", "true").lower() != "false")
        enable_signup = (os.environ.get("WEBUI_ENABLE_SIGNUP", "true").lower() != "false")

        # Session TTL (seconds). Drives both the DB-side expires_at AND the
        # browser cookie's max_age (both flow from state.session_ttl_seconds
        # in routes.py login/signup handlers). Default 7 days; override with
        # WEBUI_SESSION_TTL_HOURS for finer control (env is parsed as float
        # so half-hour values work too). Lower for shared kiosks; higher for
        # multi-day engagements where re-auth interruption is painful.
        try:
            ttl_hours = float(os.environ.get("WEBUI_SESSION_TTL_HOURS", "168"))  # 168h = 7d
        except (TypeError, ValueError):
            ttl_hours = 168.0
            log.warning("%s Invalid WEBUI_SESSION_TTL_HOURS — falling back to 168 (7d)",
                        self.log_identifier)
        ttl_hours = max(1.0, ttl_hours)   # floor at 1h so we never lock users out instantly
        session_ttl_seconds = int(ttl_hours * 3600)

        self._auth_state: AuthState = ensure_initialized(
            db_path,
            require_auth=require_auth,
            enable_signup=enable_signup,
            csrf_secret=os.environ.get("WEBUI_CSRF_SECRET"),
            session_ttl_seconds=session_ttl_seconds,
        )
        log.info(
            "%s Auth: db=%s, require_auth=%s, enable_signup=%s, session_ttl=%.1fh",
            self.log_identifier, db_path, require_auth, enable_signup, ttl_hours,
        )

        # Per-session SSE queues. Key: session_id (== A2A request_context["session_id"]).
        # Created lazily on the HTTP loop thread; cross-thread access uses run_coroutine_threadsafe.
        self._sse_queues: Dict[str, asyncio.Queue] = {}

        # Per-session replay buffer — last 100 events, indexed by monotonic id.
        # Required for SSE Last-Event-Id reconnection: when the browser drops
        # and reconnects (proxy timeout, tab throttling, network blip), it
        # sends Last-Event-Id and we replay every event newer than that id.
        # Without this, the only recovery is the heavy "RESULT NOT RECEIVED"
        # card — a 5-second disconnect costs the user a full state reload.
        from collections import deque as _deque
        self._sse_replay: Dict[str, "_deque"] = {}
        self._sse_next_id: Dict[str, int] = {}

        # aiohttp web objects (set in _start_listener's worker thread)
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._http_loop: Optional[asyncio.AbstractEventLoop] = None   # the HTTP thread's loop
        self._http_thread: Optional[threading.Thread] = None
        self._http_ready = threading.Event()                          # signals listener up

    # ---------- SAM-required lifecycle hooks ----------

    async def _extract_initial_claims(
        self, external_event_data: Any,
    ) -> Optional[Dict[str, Any]]:
        """Return claims for the browser user.

        Reads from the validated session token in the cookie. If WEBUI_REQUIRE_AUTH
        is false (dev bypass), returns anonymous.
        """
        if not self._auth_state.require_auth:
            return {"id": "anonymous", "name": "anonymous", "email": None,
                    "groups": [], "source": "webui", "is_admin": False}

        session_token = external_event_data.get("session_token") if isinstance(external_event_data, dict) else None
        if not session_token:
            # Anonymous fallback — agent will see anonymous user.
            return {"id": "anonymous", "name": "anonymous", "email": None,
                    "groups": [], "source": "webui", "is_admin": False}

        user_row = validate_session(self._auth_state, session_token)
        if not user_row:
            return {"id": "anonymous", "name": "anonymous", "email": None,
                    "groups": [], "source": "webui", "is_admin": False}
        return user_to_claims(user_row)

    def _start_listener(self) -> None:
        """Start the aiohttp HTTP server in its own thread with its own event loop.

        SAM runs its asyncio loop in a dedicated thread already (per the
        SamComponentBase logs). We can't share that loop directly without coordinated
        startup — so the HTTP server gets its own thread + loop and cross-thread
        events flow via asyncio.run_coroutine_threadsafe (see _enqueue_sse).
        """
        log.info("%s Starting WebUI HTTP listener on %s:%d",
                 self.log_identifier, self._host, self._port)

        def _run_http_server() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._http_loop = loop

                self._app = web.Application()

                # Static-asset no-cache during dev iteration. Static handlers
                # don't set Cache-Control by default, so browsers heuristic-cache
                # the JS/CSS aggressively and edits don't show up without a hard
                # reload. Sending no-cache on /assets/* + the index/intake HTML
                # avoids that. Once we ship fingerprinted assets we can drop this.
                @web.middleware
                async def _no_cache_static(request, handler):
                    response = await handler(request)
                    path = request.path
                    if (path.startswith("/assets/")
                            or path in {"/", "/settings"}
                            or path.startswith("/intake")):
                        response.headers.setdefault("Cache-Control", "no-cache, must-revalidate")
                    return response

                self._app.middlewares.append(_no_cache_static)

                # Auth: middleware FIRST (applies to every request), then auth routes.
                install_middleware(self._app, self._auth_state)
                add_auth_routes(self._app, self._auth_state)

                static_dir = _webui_static_dir()
                # Static assets — the dashboard SPA shell handles routing client-side
                # for /, /projects/{id}/{view}, /intake/new, /intake/edit/{id}, etc.
                self._app.router.add_get("/", self._serve_index)
                self._app.router.add_get("/projects/{tail:.*}", self._serve_index)
                self._app.router.add_get("/settings", self._serve_index)
                self._app.router.add_get("/intake", self._serve_intake_form)
                self._app.router.add_get("/intake/{tail:.*}", self._serve_intake_form)
                self._app.router.add_static("/assets/", static_dir / "assets", show_index=False)
                # SSE chat stream + chat POST + agent discovery
                self._app.router.add_get("/api/chat/stream/{session_id}", self._sse_chat_stream)
                # Long-poll fallback for environments where SSE doesn't work
                # (corporate proxies that strip long-lived HTTP, browsers/
                # extensions that block EventSource). Client switches to this
                # after 3 consecutive SSE failures. Returns events from the
                # replay buffer with id > since query param.
                self._app.router.add_get("/api/chat/poll/{session_id}", self._chat_poll)
                self._app.router.add_post("/api/chat/message", self._chat_message)
                self._app.router.add_get("/api/agents", self._agents_list)
                # Health probes (unauthenticated)
                self._app.router.add_get("/health",  self._health)
                self._app.router.add_get("/ready",   self._ready)
                # Serve rendered export files (audience-pack HTML, package
                # ZIP, etc.) as raw bytes with correct Content-Type. The
                # render endpoints return ABSOLUTE filesystem paths from
                # safe_artifact_path; without this route, clicking a pack
                # button navigates to that path and the browser hits a 404
                # ("localhost:9080/Users/.../exports/blueprint.html"). This
                # route resolves the file under the user-scoped engagement
                # namespace and serves it via web.FileResponse so the
                # browser renders it directly. MUST be registered before
                # API_ROUTES so `/exports/raw/<file>` doesn't get
                # shadowed by the catch-all API adapter.
                self._app.router.add_get(
                    "/api/engagements/{engagement_id}/exports/raw/{filename:.+}",
                    self._serve_export_file,
                )
                # Declarative JSON API routes
                for method, path, handler in API_ROUTES:
                    self._app.router.add_route(method, path, self._adapt_api_handler(handler))

                self._runner = web.AppRunner(self._app)
                loop.run_until_complete(self._runner.setup())
                self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
                loop.run_until_complete(self._site.start())

                # Build a clickable URL for the operator. When bound to 0.0.0.0
                # or :: (all interfaces), point the user at localhost — that's
                # what they'll actually type into a browser.
                _browser_host = (
                    "localhost"
                    if self._host in ("0.0.0.0", "::", "")
                    else self._host
                )
                _browser_url = f"http://{_browser_host}:{self._port}"
                _banner = "─" * (len(_browser_url) + 20)
                log.info("%s %s", self.log_identifier, _banner)
                log.info("%s  WebUI ready → %s", self.log_identifier, _browser_url)
                log.info("%s %s", self.log_identifier, _banner)
                self._http_ready.set()

                loop.run_forever()    # serve requests until _stop_listener triggers loop.stop
            except Exception:
                log.exception("%s HTTP server failed to start", self.log_identifier)
                self._http_ready.set()    # unblock waiters even on failure

        self._http_thread = threading.Thread(
            target=_run_http_server, name="sa-webui-http", daemon=True,
        )
        self._http_thread.start()

        # Block briefly so SAM doesn't proceed before the listener is bound (or failed).
        if not self._http_ready.wait(timeout=15):
            log.error("%s HTTP listener didn't signal readiness within 15s",
                      self.log_identifier)

    def _stop_listener(self) -> None:
        """Stop the HTTP server cleanly from SAM's main thread."""
        log.info("%s Stopping WebUI HTTP listener…", self.log_identifier)
        if not self._http_loop:
            return

        async def _shutdown() -> None:
            if self._site:
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()

        future = asyncio.run_coroutine_threadsafe(_shutdown(), self._http_loop)
        try:
            future.result(timeout=5)
        except Exception:
            log.exception("%s Error during HTTP listener shutdown", self.log_identifier)
        finally:
            self._http_loop.call_soon_threadsafe(self._http_loop.stop)
            if self._http_thread:
                self._http_thread.join(timeout=5)

    async def _translate_external_input(
        self, external_event: Any,
    ) -> Tuple[str, List[A2APart], Dict[str, Any]]:
        """Convert a browser POST body → (target_agent, A2A parts, request_context).

        external_event is the dict produced by the chat POST handler — it includes
        the user's text, the active engagement_id, and the SSE session_id.
        """
        text = (external_event.get("text") or "").strip()
        # Inject the active engagement_id (and user_id when authenticated) into
        # the agent's input so its tools (read_artifact, record_open_item, …)
        # can scope to the same user namespace the WebUI writes under.
        # request_context carries these for callback routing only — they don't
        # reach the agent prompt.
        eid = external_event.get("engagement_id")
        uid = external_event.get("user_id")
        header_bits = []
        if eid:
            header_bits.append(f"engagement_id={eid}")
        if uid and uid != "anonymous":
            header_bits.append(f"user_id={uid}")
        if header_bits:
            header = f"[Active engagement: {', '.join(header_bits)}]"
            text = f"{header}\n\n{text}" if text else header
        parts: List[A2APart] = []
        if text:
            parts.append(TextPart(text=text))

        # Files attached to the chat message (e.g., YAML intake upload)
        for f in external_event.get("files") or []:
            if "bytes" in f:
                parts.append(FilePart(file=FileWithBytes(name=f["name"],
                                                        mime_type=f.get("mime_type", "application/octet-stream"),
                                                        bytes=f["bytes"])))
            elif "uri" in f:
                parts.append(FilePart(file=FileWithUri(name=f["name"],
                                                      mime_type=f.get("mime_type", ""),
                                                      uri=f["uri"])))

        # Structured data attached (e.g., AskUserQuestion answer)
        if external_event.get("data") is not None:
            parts.append(DataPart(data=external_event["data"]))

        target_agent = external_event.get("agent") or self.get_config("default_agent_name")
        # Pass the chat session_id as both `session_id` (our SSE-queue key)
        # and `a2a_session_id` (the key SAM's gateway base reads when
        # priming the ADK session_service — see solace_agent_mesh.gateway.
        # base.component:422). Without `a2a_session_id` SAM generates a
        # fresh `gdk-session-<uuid4>` per task and warns; the side effect
        # is that ADK never reuses prior session state across user turns,
        # so per-engagement context (and the telemetry patch's cached
        # engagement_id) has to be rebuilt every turn from message history.
        # Our chat session_id is stable per (project, browser) — exactly
        # the granularity ADK wants.
        chat_sid = external_event["session_id"]
        request_context = {
            "session_id": chat_sid,
            "a2a_session_id": chat_sid,
            "engagement_id": external_event.get("engagement_id"),
            "external_event_id": str(uuid.uuid4()),
        }
        return target_agent, parts, request_context

    async def _send_update_to_external(
        self,
        external_request_context: Dict[str, Any],
        event_data: Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent],
        is_final_chunk_of_update: bool,
    ) -> None:
        """Push a status/artifact update into the session's SSE queue."""
        if not self._show_status_updates and isinstance(event_data, TaskStatusUpdateEvent):
            return
        await self._enqueue_sse(external_request_context, {
            "type": event_data.__class__.__name__,
            "data": _serialize_event(event_data),
            "final": is_final_chunk_of_update,
        })

    async def _send_final_response_to_external(
        self, external_request_context: Dict[str, Any], task_data: Task,
    ) -> None:
        """Push the final Task into the session's SSE queue."""
        await self._enqueue_sse(external_request_context, {
            "type": "FinalResponse",
            "data": _serialize_event(task_data),
        })

    async def _send_error_to_external(
        self, external_request_context: Dict[str, Any], error_data: JSONRPCError,
    ) -> None:
        # Stamp every error with a short correlation id, log it alongside the
        # full error detail server-side, and surface the id in the SSE payload.
        # The frontend renders "Error ID: <id>" in the error bubble so the user
        # can quote it; you (the operator) grep sam.log for the id to find the
        # full failure context. Without this, error bubbles are opaque and
        # support is "send me your console + logs and we'll see."
        error_id = uuid.uuid4().hex[:10]
        log.error(
            "%s [error_id=%s] external error: code=%s msg=%r data=%r ctx=%r",
            self.log_identifier, error_id,
            error_data.code, error_data.message,
            getattr(error_data, "data", None),
            {k: external_request_context.get(k) for k in ("session_id", "user_id", "engagement_id")},
        )
        # Mark any in-flight step BLOCKED so the dashboard surfaces a clear
        # failure state instead of leaving the engagement frozen in
        # NEEDS_CONTEXT / IN_PROGRESS forever. Without this, an LLM 503 mid-
        # turn leaves Progress showing "Continue in chat →" with no way for
        # the user to know the agent is dead.
        engagement_id = external_request_context.get("engagement_id")
        user_id = external_request_context.get("user_id")
        if engagement_id:
            try:
                from solace_architect_core.tools import lifecycle_tools
                from solace_architect_core._user_context import scoped_user as _scoped_user
                with _scoped_user(user_id):
                    status_res = await lifecycle_tools.get_engagement_status(engagement_id)
                    steps = ((status_res.data or {}).get("steps") or {})
                    active_states = {"NEEDS_CONTEXT", "IN_PROGRESS"}
                    for step_id, info in list(steps.items()):
                        if (info or {}).get("status") in active_states:
                            await lifecycle_tools.set_step_status(
                                engagement_id, step=step_id, status="BLOCKED",
                                agent="<gateway>",
                                note=f"agent task failed (error_id={error_id}); Restart {step_id} or check logs",
                            )
            except Exception:    # noqa: BLE001 — never let status-write failure mask the error
                log.exception("%s [error_id=%s] failed to mark engagement steps BLOCKED",
                              self.log_identifier, error_id)
        await self._enqueue_sse(external_request_context, {
            "type": "Error",
            "data": {"code": error_data.code, "message": error_data.message,
                     "data": getattr(error_data, "data", None),
                     "error_id": error_id},
        })

    # ---------- HTTP handlers ----------

    async def _serve_index(self, request: web.Request) -> web.Response:
        """Serve the dashboard SPA shell. Same file for /, /projects/{...}, etc."""
        return web.FileResponse(_webui_static_dir() / "index.html",
                                headers={"Cache-Control": "no-store"})

    async def _serve_intake_form(self, request: web.Request) -> web.Response:
        """Serve the intake form for /intake/new and /intake/edit/{id}."""
        return web.FileResponse(_webui_static_dir() / "intake" / "index.html",
                                headers={"Cache-Control": "no-store"})

    async def _serve_export_file(self, request: web.Request) -> web.Response:
        """Serve a rendered export artifact (HTML/PDF/ZIP) as raw bytes.

        Resolves filenames under the active user's engagement namespace via
        ``safe_artifact_path``. Returns 404 for missing files and 400 for
        any name that escapes the engagement's storage root.
        """
        from solace_architect_core._storage import safe_artifact_path
        from solace_architect_core._user_context import scoped_user as _scoped_user
        engagement_id = request.match_info.get("engagement_id", "")
        filename = request.match_info.get("filename", "")
        if not engagement_id or not filename:
            return web.json_response({"error": "engagement_id and filename required"},
                                     status=400)
        # Pull user_id from the request session (auth middleware sets it).
        # Anonymous mode just uses the unscoped path layout.
        user_id = None
        try:
            sess = getattr(request, "session", None) or {}
            user_id = sess.get("user_id")
        except Exception:
            pass
        try:
            with _scoped_user(user_id):
                path = safe_artifact_path(engagement_id, f"exports/{filename}")
        except (ValueError, OSError) as e:
            return web.json_response({"error": f"invalid filename: {e}"}, status=400)
        if not path.exists() or not path.is_file():
            return web.json_response(
                {"error": f"exports/{filename} not found — run the renderer first"},
                status=404,
            )
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    def _adapt_api_handler(self, handler):
        """Wrap a coroutine ``handler(**kwargs)`` as an aiohttp route handler."""
        async def adapted(request: web.Request) -> web.Response:
            # Gather kwargs from path + query + JSON body
            kwargs: Dict[str, Any] = dict(request.match_info)
            kwargs.update(dict(request.query))
            if request.can_read_body and request.content_length:
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        kwargs.update(body)
                except (json.JSONDecodeError, ValueError):
                    pass
            try:
                result = await handler(**kwargs)
            except TypeError as e:
                return web.json_response({"error": f"bad parameters: {e}"}, status=400,
                                         headers={"Cache-Control": "no-store"})
            return web.json_response(result, headers={"Cache-Control": "no-store"},
                                     dumps=_safe_json_dumps)
        return adapted

    async def _chat_message(self, request: web.Request) -> web.Response:
        """User posts a chat message → translate + dispatch via SAM A2A."""
        body = await request.json()
        session_id = body.get("session_id") or str(uuid.uuid4())
        body["session_id"] = session_id

        # Inject the auth session token so _extract_initial_claims can resolve the user.
        body["session_token"] = request.cookies.get(SESSION_COOKIE)

        # Lazy-create the SSE queue for this session.
        self._sse_queues.setdefault(session_id, asyncio.Queue())

        # Resolve identity + translate browser body → (target_agent, A2A parts, ctx).
        try:
            user_identity = await self._extract_initial_claims(body)
            # Forward user_id into translate so agent tools can scope storage
            # to the same user namespace the WebUI wrote intake.json under.
            if user_identity and user_identity.get("id"):
                body["user_id"] = user_identity["id"]
            target_agent, parts, request_context = await self._translate_external_input(body)
        except Exception as e:
            log.exception("%s Chat translate failed", self.log_identifier)
            return web.json_response({"error": f"translate failed: {e}"}, status=400,
                                     headers={"Cache-Control": "no-store"})

        if not target_agent:
            return web.json_response(
                {"error": "no target agent — set 'agent' in body or 'default_agent_name' in config"},
                status=400, headers={"Cache-Control": "no-store"},
            )

        # Server-side gate for blocking open-items on phase-kickoff messages.
        # The frontend disables the Start-Blueprint / Start-Event-Portal CTAs
        # while blocking items exist, but a direct POST (CI, scripted client,
        # or DOM-disable bypass) could otherwise dispatch a step that
        # Validation explicitly blocked. We refuse with 412 if the message
        # starts with "Phase: <step>" and any open-item lists that step in
        # affecting_step with severity=blocking. Plain chat replies (no
        # Phase prefix) are not gated — they're conversation, not dispatch.
        engagement_id = (request_context or {}).get("engagement_id")
        text = (body.get("text") or "").lstrip()
        import re as _re
        phase_match = _re.match(r"^Phase:\s*([a-z0-9\-]+)", text, _re.IGNORECASE)
        if phase_match and engagement_id:
            target_step = phase_match.group(1).strip().lower()
            try:
                from solace_architect_core.tools import decision_tools
                from solace_architect_core._user_context import scoped_user as _scoped_user
                with _scoped_user(user_identity.get("id") if user_identity else None):
                    items_res = await decision_tools.read_open_items(
                        engagement_id, status="open", severity="blocking",
                    )
                blockers = [
                    i for i in (items_res.data or [])
                    if (i or {}).get("affecting_step") == target_step
                ]
                if blockers:
                    return web.json_response(
                        {
                            "error": "blocking open-items prevent this step",
                            "step": target_step,
                            "blockers": [
                                {"id": b.get("id"), "description": b.get("description")}
                                for b in blockers[:10]
                            ],
                            "hint": (
                                f"Resolve the listed open-items (see Open Items view) "
                                f"before dispatching {target_step}."
                            ),
                        },
                        status=412,
                        headers={"Cache-Control": "no-store"},
                    )
            except Exception:
                # Don't let a guard-side error mask a real dispatch — log and
                # fall through. The frontend gate is the primary defense.
                log.exception("%s blocking-item gate check failed", self.log_identifier)

        # Submit through BaseGatewayComponent's dispatch path. SAM publishes to
        # the agent over A2A; responses arrive on the gateway response/status
        # topics and route back into _send_*_to_external → SSE queue (we bridge
        # back from SAM's loop via run_coroutine_threadsafe in _enqueue_sse).
        # NOTE: submit_a2a_task expects to run on SAM's asyncio loop, not the
        # HTTP loop this handler is on. We cross loops with run_coroutine_threadsafe.
        try:
            sam_loop = self.get_async_loop()
            coro = self.submit_a2a_task(
                target_agent_name=target_agent,
                a2a_parts=parts,
                external_request_context=request_context,
                user_identity=user_identity,
                is_streaming=True,
            )
            if sam_loop is None or sam_loop is asyncio.get_event_loop():
                task_id = await coro
            else:
                fut = asyncio.run_coroutine_threadsafe(coro, sam_loop)
                task_id = await asyncio.wrap_future(fut)
        except Exception as e:
            log.exception("%s Chat dispatch failed", self.log_identifier)
            return web.json_response({"error": f"dispatch failed: {e}"}, status=502,
                                     headers={"Cache-Control": "no-store"})

        return web.json_response(
            {"session_id": session_id, "task_id": task_id, "accepted": True},
            headers={"Cache-Control": "no-store"},
        )

    async def _health(self, request: web.Request) -> web.Response:
        """Liveness probe — always 200 once the HTTP server is up."""
        return web.json_response({"status": "ok"}, headers={"Cache-Control": "no-store"})

    async def _ready(self, request: web.Request) -> web.Response:
        """Readiness probe — 200 only when the gateway has finished initializing."""
        ready = bool(self._http_ready and self._http_ready.is_set())
        agents = 0
        try:
            agents = len(self.agent_registry.get_agent_names() or [])
        except Exception:
            pass
        return web.json_response(
            {"status": "ready" if ready else "not_ready", "discovered_agents": agents},
            status=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    async def _agents_list(self, request: web.Request) -> web.Response:
        """List agents currently discovered on the SAM mesh (for the chat picker)."""
        default_name = self.get_config("default_agent_name") or ""
        try:
            names = list(self.agent_registry.get_agent_names() or [])
        except Exception:
            names = []
        if default_name and default_name not in names:
            names.append(default_name)
        names = sorted(set(names))
        return web.json_response(
            {"agents": [{"name": n, "default": n == default_name} for n in names],
             "default": default_name},
            headers={"Cache-Control": "no-store"},
        )

    async def _sse_chat_stream(self, request: web.Request) -> web.StreamResponse:
        """SSE stream of agent events for a single session.

        Robustness:
          - Every event carries an ``id:`` so the browser's EventSource records
            it and sends ``Last-Event-Id`` on reconnect.
          - On reconnect we replay every buffered event with id strictly greater
            than the supplied ``Last-Event-Id``, then resume live streaming.
            Buffer is bounded to the last 100 events per session (deque maxlen),
            which covers the typical 5-30s drop comfortably.
          - A ``retry: 5000`` directive tells the browser to retry every 5s
            on disconnect (default is 3s — slightly slower is friendlier on
            flaky links and on the server's accept queue).
          - A background heartbeat task writes ``: keepalive\\n\\n`` every 15s.
            Idle TCP connections get reaped by proxies / load balancers /
            corporate firewalls around the 30-60s mark; the heartbeat both
            keeps the socket warm AND lets the client distinguish "agent is
            quiet" from "connection is dead" (no heartbeat for >30s → dead).
        """
        from collections import deque
        session_id = request.match_info["session_id"]
        queue = self._sse_queues.setdefault(session_id, asyncio.Queue())
        replay = self._sse_replay.setdefault(session_id, deque(maxlen=100))

        resp = web.StreamResponse(status=200, headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            # Disable proxy buffering — some reverse proxies (nginx) buffer
            # response bodies by default, which silently breaks SSE.
            "X-Accel-Buffering": "no",
        })
        await resp.prepare(request)

        # Tell the browser to retry every 5s on disconnect, and emit a
        # zero-id comment so the connection is "live" the moment we start.
        await resp.write(b"retry: 5000\n\n")

        # Replay any events the client missed since its last connection.
        last_event_id_hdr = request.headers.get("Last-Event-Id", "").strip()
        try:
            last_seen = int(last_event_id_hdr) if last_event_id_hdr else 0
        except ValueError:
            last_seen = 0
        if last_seen > 0:
            for ev_id, event in list(replay):
                if ev_id > last_seen:
                    await resp.write(
                        f"id: {ev_id}\ndata: {_safe_json_dumps(event)}\n\n".encode("utf-8")
                    )

        # Heartbeat — keeps idle connections from being timed-out by
        # intermediaries AND lets the client detect "stream died" reliably.
        heartbeat_task = asyncio.create_task(self._sse_heartbeat(resp))

        try:
            while True:
                event = await queue.get()
                if event is None:                   # poison pill = client disconnect
                    break
                ev_id = self._sse_next_id.get(session_id, 0) + 1
                self._sse_next_id[session_id] = ev_id
                replay.append((ev_id, event))
                payload = _safe_json_dumps(event)
                await resp.write(
                    f"id: {ev_id}\ndata: {payload}\n\n".encode("utf-8")
                )
                if event.get("final") or event.get("type") in ("FinalResponse", "Error"):
                    await resp.write(b"event: complete\ndata: {}\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            heartbeat_task.cancel()
        return resp

    async def _chat_poll(self, request: web.Request) -> web.Response:
        """Long-poll fallback for environments where SSE is blocked.

        Returns events newer than ``?since=<event_id>`` from the same per-
        session replay buffer the SSE handler uses. Client switches to this
        endpoint after 3 consecutive EventSource failures, polling every
        2s. Replays the missed tail in a single response (cap 100 events
        via the deque maxlen).

        Response shape:
            {"events": [{id, payload}, ...], "next_since": <last_id>}

        Empty array is a normal "no new events yet" response; the client
        keeps polling on a fixed cadence.
        """
        session_id = request.match_info["session_id"]
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            since = 0
        replay = self._sse_replay.get(session_id)
        events = []
        if replay:
            for ev_id, payload in list(replay):
                if ev_id > since:
                    events.append({"id": ev_id, "payload": payload})
        next_since = events[-1]["id"] if events else since
        return web.json_response(
            {"events": events, "next_since": next_since},
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    async def _sse_heartbeat(resp: web.StreamResponse) -> None:
        """Emit a named ``heartbeat`` event every 15s.

        Two purposes:
          1. Keeps idle TCP connections from being timed-out by reverse proxies,
             load balancers, and corporate firewalls (typical idle reap: 30-60s).
          2. Lets the browser-side stale detector distinguish "agent is quiet but
             alive" from "stream is dead". The client's onmessage handler does
             not see SSE comment lines (``: keepalive``), so we must use a named
             event whose ``data:`` payload the browser surfaces to JavaScript.
             The frontend attaches a ``"heartbeat"`` listener that bumps the
             last-event timestamp, gating the 30s force-reconnect logic on
             actual liveness rather than agent activity.
        """
        try:
            while True:
                await asyncio.sleep(15)
                try:
                    await resp.write(b"event: heartbeat\ndata: {}\n\n")
                except (ConnectionResetError, RuntimeError):
                    # Connection closed by client or runtime; stop heartbeating.
                    return
        except asyncio.CancelledError:
            return

    # ---------- helpers ----------

    async def _enqueue_sse(self, ctx: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """Bridge an SSE event from SAM's loop thread to the HTTP loop thread."""
        session_id = ctx.get("session_id")
        if not session_id:
            log.warning("%s SSE event without session_id; dropping", self.log_identifier)
            return
        if not self._http_loop:
            log.warning("%s SSE event before HTTP loop ready; dropping", self.log_identifier)
            return

        async def _put_on_http_loop() -> None:
            q = self._sse_queues.setdefault(session_id, asyncio.Queue())
            await q.put(payload)

        # Schedule the put on the HTTP loop's thread; don't block SAM's loop on completion.
        asyncio.run_coroutine_threadsafe(_put_on_http_loop(), self._http_loop)


def _serialize_event(obj: Any) -> Any:
    """Convert A2A pydantic-ish objects to plain dicts for JSON serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if hasattr(obj, "dict"):
        return obj.dict(exclude_none=True)
    return obj


def _safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
