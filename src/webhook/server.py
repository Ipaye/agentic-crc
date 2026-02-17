"""
FastAPI webhook server for receiving GitHub events.
"""
from __future__ import annotations

import hashlib
import hmac
from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.webhook.handlers import WebhookEventHandler

logger = get_logger("webhook.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    setup_logging()
    logger.info("webhook_server_starting")
    yield
    logger.info("webhook_server_stopping")


app = FastAPI(
    title="Agentic Code Review Webhook Server",
    description="Receives GitHub webhook events for automated code review",
    version="1.0.0",
    lifespan=lifespan
)

# Event handler instance
event_handler = WebhookEventHandler()


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify the GitHub webhook signature.

    Args:
        payload: The raw request body
        signature: The X-Hub-Signature-256 header value
        secret: The webhook secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not secret:
        return False

    expected_signature = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "healthy", "service": "agentic-code-review"}


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "ready": True
    }


@app.post("/webhook")
async def webhook_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None)
):
    """
    Main webhook endpoint for GitHub events.
    """
    settings = get_settings()

    # Read raw body for signature verification
    body = await request.body()

    # Verify signature if secret is configured
    if settings.github.webhook_secret:
        if not verify_signature(body, x_hub_signature_256, settings.github.webhook_secret):
            logger.warning(
                "invalid_webhook_signature",
                delivery_id=x_github_delivery
            )
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("failed_to_parse_webhook_payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    logger.info(
        "webhook_received",
        event=x_github_event,
        delivery_id=x_github_delivery,
        action=payload.get("action")
    )

    # Handle the event in background
    if x_github_event == "pull_request":
        action = payload.get("action")
        if action in ["opened", "synchronize", "reopened"]:
            # Process PR review in background
            background_tasks.add_task(
                event_handler.handle_pull_request_event,
                payload,
                x_github_delivery
            )
            return JSONResponse(
                content={"status": "processing", "delivery_id": x_github_delivery},
                status_code=202
            )

    elif x_github_event == "pull_request_review_comment":
        # Handle comment events (for potential re-review requests)
        background_tasks.add_task(
            event_handler.handle_review_comment_event,
            payload,
            x_github_delivery
        )
        return JSONResponse(
            content={"status": "processing", "delivery_id": x_github_delivery},
            status_code=202
        )

    elif x_github_event == "ping":
        # GitHub sends this when webhook is first set up
        logger.info("webhook_ping_received", zen=payload.get("zen"))
        return {"status": "pong", "zen": payload.get("zen")}

    # Event not handled
    return {"status": "ignored", "event": x_github_event}


@app.post("/review")
async def trigger_review(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Manually trigger a review for a pull request.

    Body should contain:
    {
        "repo": "owner/repo",
        "pr_number": 123
    }
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    repo = payload.get("repo")
    pr_number = payload.get("pr_number")

    if not repo or not pr_number:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: repo, pr_number"
        )

    logger.info(
        "manual_review_triggered",
        repo=repo,
        pr_number=pr_number
    )

    background_tasks.add_task(
        event_handler.trigger_manual_review,
        repo,
        pr_number
    )

    return JSONResponse(
        content={"status": "processing", "repo": repo, "pr_number": pr_number},
        status_code=202
    )


def run_server():
    """Run the webhook server."""
    settings = get_settings()

    uvicorn.run(
        "src.webhook.server:app",
        host=settings.webhook.host,
        port=settings.webhook.port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
