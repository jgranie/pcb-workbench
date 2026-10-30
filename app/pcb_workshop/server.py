"""Loopback review with optional, explicitly triggered local model jobs."""
from http.server import BaseHTTPRequestHandler
import json
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .wevisone_jobs import ModelJobs
from .crops import crop_root
from .image_import import upload, select_layer
from . import __version__
from .trace_settings import validate as validate_trace_settings
from .model_settings import validate as validate_settings
from .solder_detection import propose as propose_solders, validate as validate_solder_settings
from .model_settings import defaults as model_defaults
from .solder_model import start as start_solder_model


def validate_workspace(value, initial):
    if value.get("schema_version") != 1 or value.get("canvas") != initial["canvas"] or value.get("source_rgba_sha256") != initial["source_rgba_sha256"]:
        raise ValueError("Workspace d'une autre image ou format incompatible.")
    scan = value.get("traceScan", {})
    if not isinstance(scan.get("routes"), list) or len(scan["routes"]) > 3000 or len(scan.get("issues", [])) > 2000:
        raise ValueError("Balayage hors limites.")
    if value.get('solderSettings') is not None:validate_solder_settings(value['solderSettings'])
    if value.get('solderModelSettings') is not None:validate_settings('solders',value['solderModelSettings'])
    if value.get('traceSettings') is not None:validate_trace_settings(value['traceSettings'])
    detection=value.get('solderDetection')
    if detection is not None:
        if not isinstance(detection,dict) or not isinstance(detection.get('candidates'),list) or len(detection['candidates'])>3000:
            raise ValueError('Liste de soudures hors limites.')
        ids=set()
        for candidate in detection['candidates']:
            identity=candidate.get('id');coords=candidate.get('coords')
            if not isinstance(identity,str) or len(identity)>80 or identity in ids or not isinstance(coords,list) or len(coords)!=4:
                raise ValueError('Soudure invalide.')
            ids.add(identity);x1,y1,x2,y2=coords
            if not (0<=x1<x2<=initial['canvas']['width'] and 0<=y1<y2<=initial['canvas']['height']):raise ValueError('Soudure hors image.')
    points = 0
    width, height = initial["canvas"]["width"], initial["canvas"]["height"]
    for route in scan["routes"]:
        if len(route.get("points", [])) < 2:
            raise ValueError("Tracé incomplet.")
        for x, y in route["points"]:
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Tracé hors image.")
            points += 1
    if points > 300000 or len(value.get("objects", [])) > 30000 or len(value.get("detectionReviews", {})) > 3000:
        raise ValueError("Trop de données de correction.")


def serve_workspace(args):
    root = Path(args.directory).expanduser().resolve()
    receipt = json.loads((root / "result.json").read_text())
    for name in ("original.png", "mask.png", "alpha.bin", "photo.bin", "candidates.json", "image.json", "config.json", "scan.json"):
        expected = receipt["useful_sha256"].get(name)
        if expected and hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source ou résultat modifié : {name}. Recréer un dossier distinct avant de superposer les tracés.")
    initial = json.loads((root / "workspace.json").read_text())
    web = Path(__file__).resolve().parents[1] / "web"
    jobs = getattr(args, "model_jobs", None) or ModelJobs(root)
    allowed = {"original.png", "mask.png", "board.png", "solder.png", "image.json", "config.json", "candidates.json",
               "external-material-mask.png", "scan.json", "workspace.json", "alpha.bin", "photo.bin", "provenance.json", "result.json", "routing-diagnostics.json"}

    class Handler(BaseHTTPRequestHandler):
        def selected_root(self):
            identity = parse_qs(urlsplit(self.path).query).get("result", [None])[0]
            return jobs.result_root(identity)

        def respond(self, status, data, mime="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == "/api/app":
                    self.respond(200,json.dumps({"version":__version__,"features":["image_import","model_parameters","solder_detection","solder_wevisone"]}).encode());return
                if path.startswith("/api/preprocessing/"):
                    parts = path.split("/")
                    if len(parts) != 5 or parts[4] not in ("original-cropped.png", "crop.json"):
                        raise ValueError("Ressource crop inconnue.")
                    target = crop_root(self.selected_root(), parts[3]) / parts[4]
                    self.respond(200, target.read_bytes(), "image/png" if target.suffix == ".png" else "application/json");return
                if path == "/api/solders":
                    cap=jobs.capabilities();self.respond(200,json.dumps({"defaults":model_defaults("solders"),"models":cap["models"],"available":cap["available"],"simulation":cap["simulation"],"jobs":[j for j in cap["jobs"] if j.get("kind")=="solders"]}).encode());return
                if path.startswith("/api/solders/jobs/"):
                    parts=path.split('/');identity=parts[4];state=jobs.state(identity)
                    if state.get('kind')!='solders':raise ValueError('Calcul soudures inconnu.')
                    if len(parts)==5:self.respond(200,json.dumps(state).encode());return
                    if len(parts)==6 and parts[5]=='detection.json':
                        target=jobs.directory(identity)/'detection.json'
                        if state['status']!='ready' or hashlib.sha256(target.read_bytes()).hexdigest()!=state['result_sha256']:raise ValueError('Résultat incomplet ou modifié.')
                        self.respond(200,target.read_bytes());return
                    raise ValueError('Ressource soudures inconnue.')
                if path == "/api/wevisone":
                    self.respond(200, json.dumps(jobs.capabilities(), ensure_ascii=False).encode());return
                if path == "/api/wevisone/session":
                    self.respond(200, json.dumps(jobs.session_status(), ensure_ascii=False).encode());return
                if path.startswith("/api/wevisone/jobs/"):
                    parts = path.split("/");identity = parts[4]
                    if len(parts) == 5:
                        self.respond(200, json.dumps(jobs.state(identity), ensure_ascii=False).encode());return
                    if len(parts) == 6 and parts[5] in ("alpha.png", "cutout.png", "mask-provenance.json"):
                        target = jobs.directory(identity) / parts[5]
                        if not target.is_file():raise ValueError("Résultat pas encore disponible.")
                        self.respond(200, jobs.alpha_bytes(identity) if parts[5]=="alpha.png" else target.read_bytes(), "image/png" if target.suffix == ".png" else "application/json");return
                    raise ValueError("Ressource de modèle inconnue.")
            except (ValueError, OSError) as error:
                self.respond(404, json.dumps({"error": str(error)}).encode());return
            if path.startswith("/data/") and path[6:] in allowed:
                try:
                    target = self.selected_root() / path[6:]
                except ValueError as error:
                    self.respond(404, json.dumps({"error": str(error)}).encode());return
            else:
                name = path.lstrip("/") or "index.html"
                target = (web / name).resolve()
                if not target.is_relative_to(web) or target.suffix not in (".html", ".mjs", ".css"):
                    self.respond(404, b'{}'); return
            if not target.is_file():
                self.respond(404, b'{}'); return
            mime = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".png": "image/png",
                    ".css": "text/css", ".json": "application/json"}.get(target.suffix, "application/octet-stream")
            self.respond(200, target.read_bytes(), mime)

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in ("/workspace", "/api/workspace/validate", "/api/wevisone/session/release", "/api/wevisone/parameters/validate", "/api/solders/propose", "/api/solders/parameters/validate", "/api/solders/jobs") and not path.startswith(("/api/wevisone/jobs", "/api/images/", "/api/solders/jobs/")):
                self.respond(404, b'{}'); return
            origin = self.headers.get("Origin")
            expected = f"http://127.0.0.1:{args.port}"
            if self.headers.get("Host") not in (f"127.0.0.1:{args.port}", f"localhost:{args.port}") or origin not in (None, expected, f"http://localhost:{args.port}"):
                self.respond(403, b'{"error":"Origine refusee"}'); return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if path == "/api/images/upload":
                    if not 0 < length <= 256*1024*1024:
                        raise ValueError("Fichier limité à 256 Mio.")
                    name = parse_qs(urlsplit(self.path).query).get("name", [""])[0]
                    result = upload(root, name, self.rfile.read(length))
                    self.respond(201, json.dumps(result).encode());return
                if not 0 < length <= 20_000_000:
                    raise ValueError("Sauvegarde trop volumineuse.")
                value = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nombre non fini.")))
                if not isinstance(value, dict):
                    raise ValueError("Un objet JSON est requis.")
                if path == "/api/wevisone/session/release":
                    self.respond(200, json.dumps(jobs.release_model(), ensure_ascii=False).encode());return
                if path.startswith("/api/images/"):
                    parts = path.split("/")
                    if len(parts)!=5 or parts[4]!="select":raise ValueError("Action d'import inconnue.")
                    result=select_layer(root,parts[3],value.get("native_path"))
                    self.respond(201,json.dumps(result).encode());return
                if path == "/api/solders/parameters/validate":
                    self.respond(200,json.dumps(validate_settings("solders",value.get("settings"))).encode());return
                if path == "/api/solders/jobs":
                    self.respond(202,json.dumps(start_solder_model(jobs,value)).encode());return
                if path.startswith('/api/solders/jobs/'):
                    parts=path.split('/')
                    if len(parts)!=6 or parts[5]!='cancel' or jobs.state(parts[4]).get('kind')!='solders':raise ValueError('Action soudures inconnue.')
                    self.respond(202,json.dumps(jobs.cancel(parts[4])).encode());return
                if path == "/api/solders/propose":
                    if jobs.active:raise ValueError("Attendre la fin du calcul WeVisOne.")
                    self.respond(200,json.dumps(propose_solders(self.selected_root(),value),allow_nan=False).encode());return
                if path == "/api/wevisone/parameters/validate":
                    self.respond(200,json.dumps(validate_settings(value.get("kind"),value.get("settings"))).encode());return
                if path == "/api/wevisone/jobs":
                    result = jobs.start(value.get("kind", "board"), value.get("source_result"), value.get("section"), value.get("source_crop"), value.get("settings"))
                    self.respond(202, json.dumps(result).encode());return
                if path.startswith("/api/wevisone/jobs/"):
                    parts = path.split("/")
                    if len(parts) != 6:raise ValueError("Action de modèle inconnue.")
                    if parts[5] == "cancel":result = jobs.cancel(parts[4])
                    elif parts[5] == "apply":result = jobs.apply(parts[4], value.get("source_result"), value.get("previous"))
                    elif parts[5] == "derive":raise ValueError("Utiliser Appliquer ; aucun lancement automatique de détection.")
                    else:raise ValueError("Action de modèle inconnue.")
                    self.respond(202, json.dumps(result).encode());return
                selected = self.selected_root()
                current_initial = json.loads((selected / "workspace.initial.json").read_text()) if (selected / "workspace.initial.json").exists() else initial
                validate_workspace(value, current_initial)
                if value.get("preprocessing"):
                    crop_root(selected, value["preprocessing"]["id"])
                if path == "/api/workspace/validate":
                    self.respond(200, b'{"valid":true}');return
                path = selected / "workspace.json"
                current = json.loads(path.read_text())
                if value.get("_revision", 0) != current.get("_revision", 0):
                    self.respond(409, json.dumps({"error": "Une autre fenêtre a enregistré ; recharger avant de continuer."}).encode()); return
                value["_revision"] = current.get("_revision", 0) + 1
                # Preserve the previous user correction before atomic replacement.
                (selected / "workspace.previous.json").write_bytes(path.read_bytes())
                temporary = selected / "workspace.pending.json"
                temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
                os.replace(temporary, path)
                self.respond(200, json.dumps({"revision": value["_revision"]}).encode())
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.respond(400, json.dumps({"error": str(error)}).encode())

    # A serial server makes the revision read/replace transaction atomic across requests.
    from http.server import HTTPServer
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    args.port = server.server_port
    print(f"Revue isolée : http://127.0.0.1:{args.port}/ — Ctrl-C pour arrêter", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        jobs.close()
        server.server_close()
