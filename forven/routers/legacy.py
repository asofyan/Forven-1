from fastapi import APIRouter, Depends, Request, Response, WebSocket

from forven import api_core as core
from forven.api_domains import legacy as legacy_domain
from forven.api_security import require_operator_access
from forven.control_plane.models import QueueProcessingBody

router = APIRouter(tags=["legacy"], dependencies=[Depends(require_operator_access)])


@router.put("/api/forven/model-policy", deprecated=True)
def put_legacy_model_policy(body: core.ModelPolicyUpdateBody, response: Response):
    legacy_domain.apply_legacy_response_headers(response, "/api/forven/model-policy")
    return legacy_domain.put_legacy_model_policy(body)


@router.patch("/api/forven/agents/{agent_id}", deprecated=True)
def legacy_patch_agent(agent_id: str, body: core.LegacyAgentUpdateBody, response: Response):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/agents/{agent_id}")
    return legacy_domain.legacy_patch_agent(agent_id, body)


@router.put("/api/forven/agents/{agent_id}/documents/{document}", deprecated=True)
def legacy_put_agent_document(
    agent_id: str,
    document: str,
    body: core.LegacyAgentDocumentBody,
    response: Response,
):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/agents/{agent_id}/documents/{document}")
    return legacy_domain.legacy_put_agent_document(agent_id, document, body)


@router.patch("/api/forven/agents/{agent_id}/model", deprecated=True)
def legacy_patch_agent_model(agent_id: str, body: core.LegacyAgentModelBody, response: Response):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/agents/{agent_id}/model")
    return legacy_domain.legacy_patch_agent_model(agent_id, body)


@router.post("/api/forven/agents/{agent_id}/test-discord", deprecated=True)
def legacy_post_agent_test_discord(
    agent_id: str,
    response: Response,
    body: core.AgentDiscordTestBody | None = None,
):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/agents/{agent_id}/test-discord")
    return legacy_domain.legacy_post_agent_test_discord(agent_id, body)


@router.post("/api/forven/agent-tasks/process", deprecated=True)
async def legacy_post_agent_task_queues(body: QueueProcessingBody, response: Response):
    legacy_domain.apply_legacy_response_headers(response, "/api/forven/agent-tasks/process")
    return await legacy_domain.legacy_post_agent_task_queues(body)


@router.post("/api/forven/brain/chat", status_code=202, deprecated=True)
def post_brain_chat_legacy(body: core.BrainChatBody, response: Response):
    legacy_domain.apply_legacy_response_headers(response, "/api/forven/brain/chat")
    return legacy_domain.post_brain_chat_legacy(body)


@router.get("/api/forven/brain/chat/{task_id}", deprecated=True)
def get_brain_chat_result_legacy(task_id: int, response: Response):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/brain/chat/{task_id}")
    return legacy_domain.get_brain_chat_result_legacy(task_id, response)


@router.get("/api/forven/{legacy_path:path}", deprecated=True)
def legacy_forven_get(legacy_path: str, request: Request, response: Response, limit: int = 50):
    legacy_domain.apply_legacy_response_headers(response, f"/api/forven/{legacy_path}")
    return legacy_domain.legacy_forven_get(legacy_path, request, limit=limit)


@router.websocket("/api/forven/ws/live")
@router.websocket("/forven/ws/live")
async def legacy_websocket_endpoint(ws: WebSocket):
    legacy_domain.log.warning(
        "Legacy websocket route used: /api/forven/ws/live (scheduled sunset %s)",
        legacy_domain.LEGACY_API_SUNSET_DATE,
    )
    await legacy_domain.legacy_websocket_endpoint(ws)
