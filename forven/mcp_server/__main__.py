"""Entry point so `python -m forven.mcp_server` starts the stdio server.

Usage:
    python -m forven.mcp_server                      # stdio (default)
    python -m forven.mcp_server --transport sse       # SSE transport
    python -m forven.mcp_server --transport http      # Streamable HTTP transport
    python -m forven.mcp_server --transport http --port 8005  # custom port
"""
import argparse
import logging
import sys

def main() -> None:
    parser = argparse.ArgumentParser(description="Forven MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8005, help="Port to bind (default: 8005)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("forven.mcp_server")

    from .server import build_server
    server = build_server()

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        import asyncio
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        from starlette.responses import JSONResponse
        from starlette.middleware.cors import CORSMiddleware

        if args.transport == "sse":
            app = server.sse_app()
        else:  # http
            app = server.streamable_http_app()

        # Add health endpoint
        async def health(request):
            return JSONResponse({"status": "ok", "transport": args.transport, "server": "forven-mcp"})

        app.routes.insert(0, Route("/health", health))

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        import uvicorn
        log.info("Starting Forven MCP server on %s:%d (transport=%s)", args.host, args.port, args.transport)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":
    main()
