"""The web app's page, scripts, styles, icons and map configuration."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse


def install(app, *, current, maps_key):
    """Registers the web app routes."""

    assets = Path(__file__).resolve().parent.parent / "static"

    @app.get("/")
    def index(request: Request):
        """Serves the web app page, adding this request's CSP nonce to its scripts when Google
        Maps is enabled.
        """
        if maps_key:
            html = (assets / "index.html").read_text()
            html = html.replace("<script ", f'<script nonce="{request.state.maps_nonce}" ')
            html = html.replace(
                "</head>", f'<style nonce="{request.state.maps_nonce}"></style></head>'
            )
            return HTMLResponse(html)
        return FileResponse(assets / "index.html")

    @app.get("/api/maps")
    def map_configuration(account=Depends(current)):
        """Returns the map provider for the browser and the Google key if configured."""
        return {"provider": "google" if maps_key else "openstreetmap", "api_key": maps_key}

    @app.get("/app.js")
    def javascript():
        """Serves the main web app script."""
        return FileResponse(assets / "app.js", media_type="text/javascript")

    @app.get("/theme.js")
    def theme_script():
        """Serves the script that applies the light theme before the page draws."""
        return FileResponse(assets / "theme.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet():
        """Serves the web app stylesheet."""
        return FileResponse(assets / "style.css", media_type="text/css")

    @app.get("/client.js")
    def client_bundle():
        """Serves the encrypted household client bundle."""
        return FileResponse(assets / "client.js", media_type="text/javascript")

    @app.get("/leaflet.css")
    def map_style():
        """Serves the Leaflet stylesheet."""
        return FileResponse(assets / "leaflet.css", media_type="text/css")

    @app.get("/app-icon.png")
    def app_icon():
        """Serves the app icon."""
        return FileResponse(assets / "app-icon.png", media_type="image/png")

    @app.get("/nara-hem-wordmark.png")
    def wordmark():
        """Serves the header wordmark."""
        return FileResponse(assets / "nara-hem-wordmark.png", media_type="image/png")

    @app.get("/nara-hem-wordmark-dark.png")
    def wordmark_dark():
        """Serves the header wordmark with dark letters, for the light theme."""
        return FileResponse(assets / "nara-hem-wordmark-dark.png", media_type="image/png")

    @app.get("/images/{name}")
    def map_asset(name: str):
        """Serves a Leaflet marker image. Only known file names are allowed."""
        if name not in (
            "marker-icon.png",
            "marker-icon-2x.png",
            "marker-shadow.png",
            "layers.png",
            "layers-2x.png",
        ):
            raise HTTPException(404)
        return FileResponse(assets / "images" / name)
