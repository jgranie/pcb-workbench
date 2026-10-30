"""Persistent one-request model jobs and separate CPU derivations."""
import datetime
import importlib.util
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from PIL import Image
import numpy as np
from .material_mask import epoxy_keep, replace_section, legacy_epoxy_keep
from .crops import crop_root, apply_crop
from .model_settings import defaults, validate

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ModelJobs:
    def __init__(self, root, *, shared_runtime=None, controller=None, runtime=None):
        self.root = Path(root).resolve()
        configured = shared_runtime or os.environ.get("PCB_WEVISONE_RUNTIME")
        self.shared = Path(configured).resolve() if configured else HERE.parents[1] / "wevisone-vl"
        self.controller = Path(controller or HERE / "wevisone_controller.py").resolve()
        configured_python = os.environ.get("PCB_WEVISONE_PYTHON")
        if not runtime and not configured_python and (self.shared / "guarded_engine.py").is_file():
            # Read the existing explicit configuration without importing torch or a model.
            for statement in ast.parse((self.shared / "guarded_engine.py").read_text()).body:
                if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PYTHON" for t in statement.targets):
                    try:
                        configured_python = ast.literal_eval(statement.value)
                    except ValueError:
                        pass
        self.runtime = Path(runtime or configured_python or "missing-local-wevisone-python")
        self.simulation = controller is not None
        self.lock = threading.RLock()
        self.process = None
        self.active = None
        self.resident = None
        self.folder = self.root / "model-jobs"
        self.folder.mkdir(exist_ok=True)
        for file in self.folder.glob("*/state.json"):
            state = json.loads(file.read_text())
            if state["status"] in ("running", "cancelling", "deriving"):
                state.update(status="interrupted", message="Serveur relancé ; résultat interrompu conservé, aucune reprise automatique.")
                self._save(file.parent, state)

    def _save(self, job, state):
        temporary = job / "state.pending.json"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, job / "state.json")

    def model_profiles(self):
        path=self.shared / "model_profiles.py"
        if path.is_file():
            spec=importlib.util.spec_from_file_location("pcb_local_model_profiles",path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            return [module.profile(size) for size in ("2B","4B")]
        return [{"size":"2B","available":self.simulation},{"size":"4B","available":False}]

    def capabilities(self):
        available = self.runtime.is_file() and (self.shared / "worker.py").is_file() and (self.shared / "guarded_engine.py").is_file()
        states = sorted([json.loads(p.read_text()) for p in self.folder.glob("*/state.json")], key=lambda s: s.get("created_at", ""))
        return {"available": available, "simulation": self.simulation, "session": self.session_status(),
                "message": "WeVisOne local configuré" if available else "Environnement WeVisOne absent : configurer PCB_WEVISONE_RUNTIME et le NVMe existant.",
                "models": self.model_profiles(), "model": "WeVisOne-VL · MPS · BF16", "task": "Détourage du PCB entier",
                "limits": "1 requête · vision 0,5 Mpx · 512 jetons · 300 s · RSS 12 Gio · arrêt si swap +2 Gio ou mémoire libre <15 %",
                "parameter_defaults": {kind: defaults(kind) for kind in ("board","epoxy")}, "jobs": states[-20:]}

    def session_status(self):
        return self.resident.status() if self.resident else {"running": False, "loaded": False, "model_size": None}

    def model_environment(self, size):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if not self.simulation:
            if self.resident is None:
                sys.path.insert(0, str(self.shared))
                try:
                    spec = importlib.util.spec_from_file_location("pcb_resident_session", self.shared / "resident_session.py")
                    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                    self.resident = module.ResidentSession(self.runtime, self.shared)
                finally:
                    sys.path.remove(str(self.shared))
            env.update(self.resident.environment(size))
        return env

    def release_model(self):
        with self.lock:
            if self.active:
                self.cancel(self.active)
            elif self.resident:
                self.resident.close()
            return self.session_status()

    def directory(self, identity):
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Identifiant de calcul invalide.")
        job = self.folder / identity
        if not (job / "state.json").is_file():
            raise ValueError("Calcul inconnu.")
        return job

    def state(self, identity):
        with self.lock:
            job = self.directory(identity)
            state = json.loads((job / "state.json").read_text())
            if state.get("kind")=="solders" and state["status"]=="running":
                manifest=job/"manifest.json"
                if manifest.exists():
                    m=json.loads(manifest.read_text());state["completed_tiles"]=len(m.get("completed",[]));state["phase"]=f"Section {m.get('current_tile') or '…'} · {state['completed_tiles']}/{state['total_tiles']}"
                return state
            if state["status"] == "running":
                for log in job.glob("engine/runs/*/worker.log"):
                    tail = log.read_text(errors="replace")[-12000:]
                    state["phase"] = ("Segmentation de la surface verte" if state.get("kind") == "epoxy" else "Segmentation du PCB") if '"stage": "loaded"' in tail else "Chargement du modèle"
            return state

    def start(self, kind="board", source_result=None, section=None, source_crop=None, settings=None):
        with self.lock:
            if self.active:
                raise ValueError("Un calcul est déjà en cours ; attendre ou l'arrêter.")
            if not self.capabilities()["available"]:
                raise ValueError(self.capabilities()["message"])
            if kind not in ("board", "epoxy"):
                raise ValueError("Type de prétraitement inconnu.")
            settings = validate(kind, settings)
            if not any(p["size"]==settings["model_size"] and p["available"] for p in self.model_profiles()):
                raise ValueError("Modèle "+settings["model_size"]+" absent ou non vérifié ; aucun repli automatique.")
            selected = self.result_root(source_result)
            crop = crop_root(selected, source_crop) if source_crop else None
            if kind == "epoxy" and not source_result and not crop:
                raise ValueError("Ouvrir d'abord un travail issu du détourage PCB revu.")
            if kind == "epoxy" and not crop:
                if (selected.parent / "import.json").exists():
                    raise ValueError("Appliquer d'abord le contour du PCB.")
                parent = self.state(source_result)
                if parent.get("kind", "board") not in ("board", "epoxy"):
                    raise ValueError("Le second passage doit partir d'un travail revu.")
            if section is not None and (kind != "epoxy" or type(section) is not int or not 0 <= section < 24):
                raise ValueError("Section invalide : choisir une des 24 sections.")
            identity = uuid.uuid4().hex
            job = self.folder / identity;job.mkdir()
            source = selected / "original.png"
            expected = json.loads((selected / "result.json").read_text())["useful_sha256"]["original.png"]
            if sha(source) != expected:
                raise ValueError("L'Original a changé ; calcul refusé.")
            shutil.copyfile(source, job / "input.png")
            request = {"settings": settings, "source_crop": source_crop, "kind": kind, "source_result": source_result, "source_sha256": expected, "shared_runtime": str(self.shared), "task": "segmentation",
                       "query": settings["query"], "decode_matting": True, "vision_max_pixels": settings["vision_max_pixels"], "max_new_tokens": settings["max_new_tokens"]}
            if kind == "epoxy":
                if section is not None:
                    with Image.open(source) as photo:
                        width, height = photo.size
                    row, col = divmod(section, 4)
                    core = [round(col*width/4), round(row*height/6), round((col+1)*width/4), round((row+1)*height/6)]
                    request["core"] = core
                    request["crop"] = [max(0,core[0]-64),max(0,core[1]-64),min(width,core[2]+64),min(height,core[3]+64)]
                    request["section"] = section
                receipt = json.loads((selected / "result.json").read_text())
                board_source = crop / "board.png" if crop else selected / "board.png"
                if crop:
                    receipt = {"useful_sha256": {"board.png": sha(board_source)}}
                if sha(board_source) != receipt["useful_sha256"]["board.png"]:
                    raise ValueError("Le contour PCB a changé.")
                shutil.copyfile(board_source, job / "board.png")
                if crop:
                    shutil.copyfile(crop / "keep.png", job / "previous-material.png")
                    request["previous_material_sha256"] = sha(job / "previous-material.png")
                elif "external-material-mask.png" in receipt["useful_sha256"]:
                    previous = selected / "external-material-mask.png"
                    if sha(previous) != receipt["useful_sha256"]["external-material-mask.png"]:
                        raise ValueError("Le masque de matière précédent a changé.")
                    shutil.copyfile(previous, job / "previous-material.png")
                    request["previous_material_sha256"] = sha(previous)
                board_evidence = {"source_sha256": expected, "alpha_sha256": sha(job / "board.png"),
                                  "upstream": json.loads((selected / "provenance.json").read_text()).get("background_mask"),
                                  "origin": "reviewed_parent_board", "source_result": source_result}
                (job / "board-provenance.json").write_text(json.dumps(board_evidence, indent=2))
            (job / "request.json").write_text(json.dumps(request, indent=2) + "\n")
            state = {"model_size": settings["model_size"], "section": section, "kind": kind, "source_result": source_result, "id": identity, "status": "running", "phase": "Préparation et contrôle mémoire",
                     "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "source_sha256": expected, "simulation": self.simulation, "review_required": True}
            self._save(job, state);self.active = identity
            log = (job / "controller.log").open("w")
            try:
                env = self.model_environment(settings["model_size"])
                self.process = subprocess.Popen([str(self.runtime), str(self.controller), str(job)],
                                                stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            except (OSError, ValueError) as error:
                state.update(status="failed", message=str(error));self._save(job, state);self.active = None;raise ValueError(str(error))
            finally:
                log.close()
            threading.Thread(target=self._watch, args=(identity, self.process), daemon=True).start()
            return state

    def _watch(self, identity, process):
        try:
            limit=1230 if self.state(identity).get("kind")=="solders" else 330
            code = process.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            with self.lock:
                state = self.state(identity);state.update(status="cancelling", stop_reason=f"Plafond global de {limit} s atteint ; aucune relance automatique.")
                self._save(self.directory(identity), state)
            os.killpg(process.pid, signal.SIGTERM);self._kill_after_grace(process);code = process.wait()
        with self.lock:
            job = self.directory(identity);state = json.loads((job / "state.json").read_text())
            if code and self.resident:
                self.resident.close()
            if state.get("kind")=="solders":
                from .solder_model import finish
                finish(self,job,state,code);self._save(job,state);self.active=None;self.process=None;return
            cancelled = state["status"] == "cancelling"
            if not cancelled and code == 0:
                try:
                    evidence = json.loads((job / "mask-provenance.json").read_text())
                    with Image.open(job / "alpha.png") as mask, Image.open(job / "input.png") as image:
                        valid = mask.mode == "L" and mask.size == image.size and (mask.getextrema() not in ((0, 0), (255, 255)) or state.get("kind")=="epoxy" and mask.getextrema()==(0,0))
                    if not valid or evidence["source_sha256"] != state["source_sha256"] or evidence["alpha_sha256"] != sha(job / "alpha.png") or not evidence["generation"].get("response_complete"):
                        raise ValueError("Résultat du modèle incohérent ; masque refusé.")
                    if state.get("kind") == "epoxy":
                        request = json.loads((job / "request.json").read_text())
                        selected = self.result_root(request["source_result"])
                        board_evidence = json.loads((job / "board-provenance.json").read_text())
                        crop = crop_root(selected, request["source_crop"]) if request.get("source_crop") else None
                        board_source = crop / "board.png" if crop else selected / "board.png"
                        if sha(job / "board.png") != board_evidence["alpha_sha256"] or sha(board_source) != board_evidence["alpha_sha256"]:
                            raise ValueError("Le contour PCB a changé pendant le calcul.")
                        shutil.copyfile(job / "alpha.png", job / "raw-epoxy.png")
                        keep, colour = epoxy_keep(np.array(Image.open(job / "input.png").convert("RGB")),
                                                  np.array(Image.open(job / "board.png")) >= 128,
                                                  np.array(Image.open(job / "raw-epoxy.png")), settings=request.get("settings"), allow_empty=True)
                        previous_sha = request.get("previous_material_sha256")
                        if previous_sha:
                            if sha(job / "previous-material.png") != previous_sha:
                                raise ValueError("Le masque de matière précédent a changé.")
                            previous = np.array(Image.open(job / "previous-material.png")) >= 128
                            keep = replace_section(previous, keep >= 128, np.array(Image.open(job / "board.png")) >= 128, request.get("core")).astype(np.uint8)*255
                            if not keep.any():
                                raise ValueError("Le retrait ne conserve aucune matière.")
                        evidence.update(composition="replace_section_v1", core=request.get("core"), previous_material_sha256=previous_sha, source_result=request["source_result"],
                                        raw_epoxy_sha256=sha(job / "raw-epoxy.png"), colour_confirmation=colour,
                                        parent_board=board_evidence, mask_semantics="255=retain;0=exclude")
                        Image.fromarray(keep).save(job / "alpha.png")
                        evidence["alpha_sha256"] = sha(job / "alpha.png")
                        cutout = Image.open(job / "input.png").convert("RGBA");cutout.putalpha(Image.fromarray(keep));cutout.save(job / "cutout.png")
                        (job / "mask-provenance.json").write_text(json.dumps(evidence, indent=2))
                    state.update(status="ready", phase="Masque époxy proposé" if state.get("kind") == "epoxy" else "Détourage terminé", message="", provenance=evidence)
                except (OSError, ValueError, KeyError) as error:
                    state.update(status="failed", message=str(error))
            else:
                error = (job / "controller-error.txt").read_text() if (job / "controller-error.txt").exists() else f"Processus terminé avec le code {code} ; consulter controller.log."
                state.update(status="cancelled" if cancelled else "failed", phase="Arrêté" if cancelled else "Échec", message=state.get("stop_reason", "Calcul arrêté ; aucun masque appliqué.") if cancelled else error)
            self._save(job, state);self.active = None;self.process = None

    def cancel(self, identity):
        with self.lock:
            state = self.state(identity)
            if self.active != identity or state["status"] not in ("running", "deriving"):
                raise ValueError("Ce calcul n'est plus en cours.")
            state.update(status="cancelling", message="Arrêt demandé…")
            self._save(self.directory(identity), state)
            process = self.process
            if self.resident:
                self.resident.close()
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                threading.Thread(target=self._kill_after_grace, args=(process,), daemon=True).start()
            return state

    @staticmethod
    def _kill_after_grace(process):
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)

    def alpha_bytes(self, identity):
        """Display old proposals with the same replacement semantics as Apply."""
        import io
        job=self.directory(identity);state=self.state(identity)
        evidence=json.loads((job / "mask-provenance.json").read_text())
        if state.get("kind")=="epoxy" and evidence.get("composition")!="replace_section_v1":
            keep,core,request=legacy_epoxy_keep(job)
            board=np.array(Image.open(job / "board.png"))>=128
            previous=board
            if request.get("previous_material_sha256"):
                if sha(job / "previous-material.png")!=request["previous_material_sha256"]:
                    raise ValueError("Crop source modifié.")
                previous=np.array(Image.open(job / "previous-material.png"))>=128
            mask=replace_section(previous,keep,board,core).astype(np.uint8)*255
            buffer=io.BytesIO();Image.fromarray(mask).save(buffer,format="PNG");return buffer.getvalue()
        return (job / "alpha.png").read_bytes()

    def apply(self, identity, source_result=None, previous=None):
        with self.lock:
            if self.active:
                raise ValueError("Attendre la fin du calcul avant d'appliquer.")
            return apply_crop(self.result_root(source_result), self.directory(identity), self.state(identity), previous)

    def derive(self, identity, reviewed):
        with self.lock:
            job = self.directory(identity);state = self.state(identity)
            if self.active or state["status"] != "ready" or reviewed is not True:
                raise ValueError("Un masque terminé et une revue explicite sont requis.")
            if sha(self.root / "original.png") != state["source_sha256"] or sha(job / "alpha.png") != state["provenance"]["alpha_sha256"]:
                raise ValueError("L'Original ou le masque a changé ; nouveau travail refusé.")
            if state.get("kind") == "epoxy":
                board_evidence = json.loads((job / "board-provenance.json").read_text())
                if sha(job / "board.png") != board_evidence["alpha_sha256"]:
                    raise ValueError("Le contour PCB a changé.")
            output = self.root / "derived" / identity
            if output.exists():
                raise ValueError("Ce travail existe déjà ; il ne sera pas écrasé.")
            state.update(status="deriving", phase="Calcul CPU dans un nouveau travail")
            self._save(job, state);self.active = identity
            log = (job / "derive.log").open("w")
            python = HERE.parent / ".venv/bin/python"
            config = json.loads((self.root / "config.json").read_text())
            # Input is already in its canonical frame; never crop or mirror it twice.
            config.update(crop=None, mirror_x=False, rotate_quarters=0)
            (job / "derived-config.json").write_text(json.dumps(config, indent=2) + "\n")
            command = [str(python), "-m", "pcb_workshop", "run", "--input", str(self.root / "original.png"),
                       "--output", str(output), "--config", str(job / "derived-config.json"),
                       "--board-mask", str(job / "alpha.png"), "--board-mask-provenance", str(job / "mask-provenance.json")]
            if state.get("kind") == "epoxy":
                board_evidence = json.loads((job / "board-provenance.json").read_text())
                if sha(job / "board.png") != board_evidence["alpha_sha256"]:
                    raise ValueError("Le contour PCB a changé.")
                # Preserve the board independently: material exclusion never recalibrates thresholds.
                position = command.index("--board-mask")
                command[position:] = ["--board-mask", str(job / "board.png"),
                                     "--board-mask-provenance", str(job / "board-provenance.json"),
                                     "--material-mask", str(job / "alpha.png"),
                                     "--material-mask-provenance", str(job / "mask-provenance.json")]
            env = {**os.environ, "PYTHONPATH": str(HERE.parent), "PYTHONDONTWRITEBYTECODE": "1"}
            try:
                self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            except OSError as error:
                state.update(status="failed", message=str(error));self._save(job, state);self.active = None;raise ValueError(str(error))
            finally:
                log.close()
            threading.Thread(target=self._watch_derivative, args=(identity, self.process, output), daemon=True).start()
            return state

    def _watch_derivative(self, identity, process, output):
        code = process.wait()
        with self.lock:
            job = self.directory(identity);state = self.state(identity)
            if state["status"] == "cancelling":
                state.update(status="cancelled", message="Calcul CPU arrêté ; travail partiel conservé.")
            elif code == 0 and (output / "result.json").exists():
                state.update(status="derived", phase="Nouveau travail disponible", message="Nouveau travail créé ; le travail précédent reste conservé.", url="/?result=" + identity)
            else:
                state.update(status="failed", message="Calcul CPU échoué ; journal et résultat partiel conservés.")
            self._save(job, state);self.active = None;self.process = None

    def result_root(self, identity):
        if not identity:
            return self.root
        if isinstance(identity,str) and len(identity)==32 and all(c in "0123456789abcdef" for c in identity):
            imported = self.root / "imports" / identity / "workspace"
            if (imported / "result.json").is_file():
                return imported
        if self.state(identity)["status"] != "derived":
            raise ValueError("Le nouveau travail n'est pas disponible.")
        return self.root / "derived" / identity

    def close(self):
        with self.lock:
            if self.active and self.process and self.process.poll() is None:
                self.cancel(self.active)
                process = self.process
            else:
                process = None
        if process:
            self._kill_after_grace(process)
        if self.resident:
            self.resident.close()
