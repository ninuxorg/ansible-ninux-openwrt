#!/usr/bin/env python3
"""Mock delle API OpenWISP Firmware Upgrader usate da roles/ninux_build_openwrt.

Non e' un OpenWISP: implementa solo gli endpoint che il ruolo chiama davvero,
tiene lo stato in memoria e lo espone su /__state__ perche' il verify di
Molecule possa controllarlo.

Serve a testare senza toccare il controller vero:
  - la stringa di versione della build (limite 32 caratteri di OpenWISP);
  - la SOSTITUZIONE della build quando si ricompila la stessa versione;
  - la RETENTION (tenere solo le ultime N versioni OpenWrt): e' la parte
    pericolosa, un bug qui cancella lo storico dei firmware dal controller;
  - il contenuto di cio' che viene caricato: il finto firmware contiene il
    .config assemblato, quindi si sa quali pacchetti sarebbero finiti
    nell'immagine.

Riproduce anche il 400 su immagine duplicata (stesso 'type' sulla stessa
build), che e' il motivo per cui il ruolo deve sostituire le build.

Uso:
  mock_openwisp.py --port 8099 --org <uuid> --target <device> [--seed v1,v2]
"""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API = "/api/v1/firmware-upgrader"

# Il finto firmware contiene il .config: cercando questi simboli si sa cosa
# sarebbe finito nell'immagine caricata.
MARKERS = {
    "uspot": "CONFIG_PACKAGE_uspot=y",
    "zerotier": "CONFIG_PACKAGE_zerotier=y",
    "wireguard": "CONFIG_PACKAGE_wireguard-tools=y",
    "vxlan": "CONFIG_PACKAGE_kmod-vxlan=y",
    "autoip": "CONFIG_PACKAGE_avahi-autoipd=y",
}

STATE = {"categories": [], "builds": [], "images": [], "deleted_builds": []}
_counter = {"id": 0}


def _new_id():
    _counter["id"] += 1
    return _counter["id"]


def _find(items, key, value):
    return next((i for i in items if str(i[key]) == str(value)), None)


def _build_version(item_id):
    build = _find(STATE["builds"], "id", item_id)
    return build["version"] if build else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if (self.headers.get("Authorization") or "").startswith("Bearer "):
            return True
        self._reply(401, {"detail": "Authentication credentials were not provided."})
        return False

    # ---- GET ----------------------------------------------------------
    def do_GET(self):  # noqa: N802 (nome imposto da BaseHTTPRequestHandler)
        if self.path.startswith("/__state__"):
            self._reply(200, STATE)
            return
        if not self._authorized():
            return

        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""

        if path == f"{API}/category/":
            results = STATE["categories"]
            self._reply(200, {"count": len(results), "results": results})
            return

        if path == f"{API}/build/":
            category = dict(
                p.split("=", 1) for p in query.split("&") if "=" in p
            ).get("category")
            results = [
                b
                for b in STATE["builds"]
                if category is None or str(b["category"]) == str(category)
            ]
            self._reply(200, {"count": len(results), "results": results})
            return

        if re.fullmatch(rf"{API}/build/\d+/upgrade/", path):
            self._reply(200, [])
            return

        self._reply(404, {"detail": "Not found."})

    # ---- POST ---------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if not self._authorized():
            return

        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if path == f"{API}/category/":
            payload = json.loads(raw or b"{}")
            category = {
                "id": _new_id(),
                "name": payload["name"],
                "organization": payload["organization"],
            }
            STATE["categories"].append(category)
            self._reply(201, category)
            return

        if path == f"{API}/build/":
            payload = json.loads(raw or b"{}")
            build = {
                "id": _new_id(),
                "category": payload["category"],
                "version": payload["version"],
                "changelog": payload.get("changelog", ""),
                # microsecondi crescenti: la retention ordina per 'created'
                "created": datetime.now(timezone.utc).isoformat(),
            }
            STATE["builds"].append(build)
            self._reply(201, build)
            return

        match = re.fullmatch(rf"{API}/build/(\d+)/image/", path)
        if match:
            build_id = int(match.group(1))
            if not _find(STATE["builds"], "id", build_id):
                self._reply(404, {"detail": "Not found."})
                return

            body = raw.decode("latin-1")
            type_match = re.search(r'name="type"\r?\n\r?\n(.*?)\r?\n--', body, re.S)
            image_type = type_match.group(1).strip() if type_match else ""

            # OpenWISP rifiuta con 400 un'immagine dello stesso 'type' gia'
            # presente sulla build: senza sostituzione resterebbe online il
            # firmware VECCHIO. Il messaggio replica quello vero di DRF: il
            # ruolo distingue il duplicato dagli altri 400 cercando 'unique'.
            duplicate = any(
                i["build"] == build_id and i["type"] == image_type
                for i in STATE["images"]
            )
            if duplicate:
                self._reply(
                    400,
                    {"non_field_errors": [
                        "The fields build, type must make a unique set."
                    ]},
                )
                return

            image = {
                "id": _new_id(),
                "build": build_id,
                "build_version": _build_version(build_id),
                "type": image_type,
                "size": length,
                "markers": {k: (v in body) for k, v in MARKERS.items()},
            }
            STATE["images"].append(image)
            self._reply(201, {"id": image["id"], "type": image_type})
            return

        self._reply(404, {"detail": "Not found."})

    # ---- DELETE -------------------------------------------------------
    def do_DELETE(self):  # noqa: N802
        if not self._authorized():
            return

        match = re.fullmatch(rf"{API}/build/(\d+)/", self.path.split("?")[0])
        if not match:
            self._reply(404, {"detail": "Not found."})
            return

        build_id = int(match.group(1))
        build = _find(STATE["builds"], "id", build_id)
        if not build:
            self._reply(404, {"detail": "Not found."})
            return

        STATE["builds"].remove(build)
        STATE["images"] = [i for i in STATE["images"] if i["build"] != build_id]
        STATE["deleted_builds"].append({"id": build_id, "version": build["version"]})
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


def seed(org_id, target, versions):
    """Popola il controller finto come se ci fossero gia' delle compilazioni."""
    category = {
        "id": _new_id(),
        "name": f"Ninux Basilicata - {target}",
        "organization": org_id,
    }
    STATE["categories"].append(category)

    base = datetime.now(timezone.utc) - timedelta(days=365)
    for index, version in enumerate(versions):
        for suffix in ("VPN-NO", "US-VPN-WG"):
            STATE["builds"].append(
                {
                    "id": _new_id(),
                    "category": category["id"],
                    "version": f"{version}-{target[:12]}-{suffix}",
                    "changelog": "build preesistente (seed del test)",
                    "created": (base + timedelta(days=index)).isoformat(),
                }
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--org", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--seed", default="")
    args = parser.parse_args()

    if args.seed:
        seed(args.org, args.target, args.seed.split(","))

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
