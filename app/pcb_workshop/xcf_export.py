"""Executed only inside a fresh GIMP 3 batch process."""
import hashlib
import json
import os
from pathlib import Path
from gi.repository import Gimp, Gio


def run():
    request = json.loads(Path(os.environ["PCB_XCF_REQUEST"]).read_text())
    source, target = Path(request["source"]), Path(request["output"])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
    if image is None:
        raise RuntimeError("GIMP n'a pas pu ouvrir le XCF.")
    inventory, matches = [], []

    def walk(layers, ancestors=(), prefix=()):
        for index, layer in enumerate(layers):
            path = prefix + (index,)
            inventory.append({"native_path": list(path), "name": layer.get_name(),
                              "size": [layer.get_width(), layer.get_height()],
                              "offsets": list(layer.get_offsets()), "visible": layer.get_visible(),
                              "opacity": layer.get_opacity(), "mode": str(layer.get_mode()),
                              "is_group": layer.is_group(), "has_mask": layer.get_mask() is not None})
            if (list(path) == request["native_path"] if request.get("native_path") is not None else layer.get_name() == request.get("layer")):
                matches.append((layer, ancestors))
            if layer.is_group():
                walk(layer.get_children(), ancestors + (layer,), path)

    walk(image.get_layers())
    if request.get("inventory"):
        target.with_suffix(".json").write_text(json.dumps({"layers": inventory, "canvas": [image.get_width(), image.get_height()], "xcf_sha256": before}, ensure_ascii=False, indent=2))
        image.delete()
        return
    if len(matches) != 1:
        raise RuntimeError(f"Calque {request['layer']!r} : {len(matches)} correspondances ; nom unique requis.")
    selected, ancestors = matches[0]
    if selected.is_group():
        raise RuntimeError("Le nom désigne un groupe ; choisir un calque photo unique.")

    def isolate(layers):
        for layer in layers:
            layer.set_visible(layer == selected or layer in ancestors)
            if layer.is_group():
                isolate(layer.get_children())

    # This image is a newly loaded in-memory copy; it is never saved as XCF.
    isolate(image.get_layers())
    proc = Gimp.get_pdb().lookup_procedure("file-png-export")
    config = proc.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("image", image)
    config.set_property("file", Gio.File.new_for_path(str(target)))
    config.set_property("compression", 6)
    result = proc.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS:
        raise RuntimeError("Échec de l'export PNG par GIMP.")
    metadata = {"xcf_sha256": before, "layer_name": request["layer"],
                "canvas": [image.get_width(), image.get_height()], "layers": inventory,
                "method": "GIMP native isolated layer render on XCF canvas",
                "gimp_version": Gimp.version(), "xcf_saved": False,
                "source_unchanged": before == hashlib.sha256(source.read_bytes()).hexdigest(),
                "pre_xcf_transforms": "unknown; layer name and offsets do not establish camera provenance"}
    image.delete()
    if not metadata["source_unchanged"]:
        raise RuntimeError("L'empreinte du XCF a changé pendant la lecture.")
    target.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


run()
