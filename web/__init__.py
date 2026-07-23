"""Browser front-end for product-image-batch.

A thin FastAPI web layer over the same ``core`` engine used by the CLI and the
desktop GUI. The backend holds the API keys (server-side) and proxies image
generation; the browser only talks to this backend, never directly to the
providers. See ``docs/WEB_DEPLOY.md`` for hosting on Cloudflare + a Python host.
"""
