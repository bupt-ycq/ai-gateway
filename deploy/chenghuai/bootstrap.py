#!/usr/bin/env python3
"""Initialize a separately deployed New API instance with Chenghuai branding.

Uses the v1.0.0-rc.23 setup, JWT login, option and profile HTTP contracts.
Credentials remain in memory. Existing users, channels, pricing and balances
are never imported or reset. Run against your own deployment only.
"""

import argparse
import base64
import getpass
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


BRAND_KEYS = frozenset({
    "SystemName", "Footer", "Logo", "DefaultCollapseSidebar",
    "HeaderNavModules", "SidebarModulesAdmin",
    "HomePageContent", "About", "general_setting.quota_display_type",
})


class BootstrapError(Exception):
    """A safe, operator-facing initialization failure."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Do not forward deployment credentials to redirected destinations."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BootstrapError("Unexpected HTTP redirect; use the final deployment URL.")


def validate_origin(value):
    """Require an explicit HTTP origin and encrypted remote connections."""
    if any(ord(char) < 33 or char.isspace() or char in "<>\"'`\\{}?#"
           for char in value):
        raise BootstrapError("Invalid characters in deployment URL.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise BootstrapError("Invalid URL authority or port.") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or port == 0):
        raise BootstrapError("Use a full http(s) origin without credentials or a path.")
    hostname = parsed.hostname
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise BootstrapError("Invalid deployment hostname.") from exc
        labels = hostname.removesuffix(".").split(".")
        if (len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels)):
            raise BootstrapError("Invalid deployment hostname.")
        loopback = hostname == "localhost"
    else:
        # Scoped IPv6 addresses are not suitable for a shareable site origin.
        if "%" in hostname:
            raise BootstrapError("Scoped IPv6 deployment URLs are unsupported.")
        loopback = address.is_loopback
        hostname = f"[{address.compressed}]" if address.version == 6 else str(address)
    if parsed.scheme == "http" and not loopback:
        raise BootstrapError("Remote deployment URLs must use HTTPS.")
    authority = hostname if port is None else f"{hostname}:{port}"
    return f"{parsed.scheme}://{authority}"


def load_brand(brand_file, origin):
    """Build appearance options using the packaged local artwork and pages."""
    origin = validate_origin(origin)
    with brand_file.open(encoding="utf-8") as handle:
        brand = json.load(handle)
    if not isinstance(brand, dict):
        raise BootstrapError("Brand file must be a JSON object.")
    assets = brand_file.parent / "assets"
    logo = base64.b64encode((assets / "logo.png").read_bytes()).decode("ascii")
    illustration = base64.b64encode((assets / "chenghuai.jpg").read_bytes()).decode("ascii")
    brand["Logo"] = "data:image/png;base64," + logo
    for key, name in (("HomePageContent", "home.html"), ("About", "about.html")):
        content = (assets / name).read_text(encoding="utf-8")
        content = content.replace("{{GATEWAY_ORIGIN}}", html.escape(origin, quote=True))
        content = content.replace("{{GATEWAY_HOST}}", html.escape(
            urllib.parse.urlsplit(origin).netloc, quote=True))
        content = content.replace("{{CHENGHUAI_IMAGE_DATA_URI}}", "data:image/jpeg;base64," + illustration)
        if re.search(r"\{\{[A-Z_]+\}\}", content):
            raise BootstrapError(f"Unresolved template marker in {name}.")
        brand[key] = content
    return brand


class Gateway:
    """Minimal authenticated client; no payload or credential logging."""

    def __init__(self, base_url):
        self.base_url = validate_origin(base_url)
        self.token = None
        self.opener = urllib.request.build_opener(NoRedirects())

    def request(self, method, path, payload=None):
        headers = {"Accept": "application/json", "Accept-Language": "zh-CN"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise BootstrapError(f"{method} {path}: HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BootstrapError(f"{method} {path}: deployment is unreachable.") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise BootstrapError(f"{method} {path}: expected a JSON API response.") from exc
        if not isinstance(result, dict) or result.get("success") is not True:
            # Do not print arbitrary server responses: they may contain secrets.
            raise BootstrapError(f"{method} {path}: API rejected the request; inspect the deployment logs.")
        return result.get("data")


def bootstrap(gateway, username, password, brand, site_url=None):
    """Apply only selected appearance options and the administrator's language."""
    options = dict(brand)
    if not options or set(options) - BRAND_KEYS:
        raise BootstrapError("Brand file must contain only supported appearance option keys.")
    if not all(isinstance(value, str) for value in options.values()):
        raise BootstrapError("Every brand option value must be a string.")
    if site_url:
        options["ServerAddress"] = validate_origin(site_url)
    if not username or len(username.encode("utf-8")) > 12:
        raise BootstrapError("Administrator username must be 1–12 UTF-8 bytes.")
    if not password:
        raise BootstrapError("Administrator password is required.")

    setup = gateway.request("GET", "/api/setup")
    if not isinstance(setup, dict) or not isinstance(setup.get("status"), bool):
        raise BootstrapError("Unexpected setup response; check the New API version.")
    if not setup["status"]:
        if setup.get("root_init"):
            raise BootstrapError("An administrator already exists but setup is incomplete. Finish setup in the web UI, then rerun.")
        if len(password.encode("utf-8")) < 8:
            raise BootstrapError("A new administrator password must be at least 8 bytes.")
        gateway.request("POST", "/api/setup", {
            "username": username,
            "password": password,
            "confirmPassword": password,
            "SelfUseModeEnabled": False,
            "DemoSiteEnabled": False,
        })
        print("Created the local administrator and completed initial setup.")

    login = gateway.request("POST", "/api/user/login", {
        "username": username, "password": password,
    })
    if not isinstance(login, dict):
        raise BootstrapError("Unexpected login response; check the New API version.")
    if login.get("require_2fa"):
        raise BootstrapError("This administrator requires 2FA. Apply brand.json through the authenticated web settings instead.")
    if not isinstance(login.get("access_token"), str) or not login["access_token"]:
        raise BootstrapError("Login did not return a JWT access token.")
    gateway.token = login["access_token"]
    try:
        current_user = gateway.request("GET", "/api/user/self")
        if not isinstance(current_user, dict) or current_user.get("role", 0) < 100:
            raise BootstrapError("The supplied account must be the root administrator.")
        rows = gateway.request("GET", "/api/option/")
        if not isinstance(rows, list):
            raise BootstrapError("Unexpected options response.")
        current_options = {row["key"]: row["value"] for row in rows}
        changed = 0
        for key, value in options.items():
            if current_options.get(key) == value:
                continue
            gateway.request("PUT", "/api/option/", {"key": key, "value": value})
            print(f"Applied {key}.")
            changed += 1

        settings = current_user.get("setting") or {}
        if isinstance(settings, str):
            settings = json.loads(settings)
        if settings.get("language") != "zhCN":
            gateway.request("PUT", "/api/user/self", {"language": "zhCN"})
            print("Set the administrator interface language to Simplified Chinese.")
        verified = gateway.request("GET", "/api/option/")
        verified_options = {row["key"]: row["value"] for row in verified}
        if any(verified_options.get(key) != value for key, value in options.items()):
            raise BootstrapError("Appearance verification failed; rerun to finish applying settings.")
        print(f"Brand settings verified ({changed} changed). Existing business data preserved.")
    finally:
        try:
            gateway.request("POST", "/api/user/auth/logout", {})
        except BootstrapError:
            print("Warning: could not revoke the temporary login session; revoke it in Profile → Sessions.", file=sys.stderr)
        gateway.token = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000",
                        help="Your deployment origin (default: local port 3000)")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--brand-file", type=Path,
                        default=Path(__file__).with_name("brand.json"))
    parser.add_argument("--site-url", "--public-url", dest="site_url",
                        help="Your public origin for homepage examples and ServerAddress")
    args = parser.parse_args()
    try:
        gateway = Gateway(args.base_url)
        origin = validate_origin(args.site_url) if args.site_url else gateway.base_url
        brand = load_brand(args.brand_file, origin)
        password = os.environ.pop("CHENGHUAI_ADMIN_PASSWORD", None)
        if password is None:
            password = getpass.getpass("Administrator password (new deployment: choose a new password): ")
        bootstrap(gateway, args.username, password, brand, args.site_url)
    except (BootstrapError, OSError, ValueError, EOFError) as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
