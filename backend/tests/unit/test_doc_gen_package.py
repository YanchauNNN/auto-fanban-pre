from __future__ import annotations

import importlib
import sys


def test_importing_pdf_engine_does_not_eagerly_import_cad_renderer() -> None:
    module_names = [
        name
        for name in list(sys.modules)
        if name == "src.doc_gen"
        or name.startswith("src.doc_gen.")
        or name == "src.cad"
        or name.startswith("src.cad.")
    ]
    removed_modules = {name: sys.modules[name] for name in module_names}
    for name in module_names:
        sys.modules.pop(name, None)

    try:
        module = importlib.import_module("src.doc_gen.pdf_engine")

        assert hasattr(module, "PDFExporter")
        assert "src.cad.dxf_pdf_exporter" not in sys.modules
    finally:
        for name in [
            current_name
            for current_name in list(sys.modules)
            if current_name == "src.doc_gen"
            or current_name.startswith("src.doc_gen.")
            or current_name == "src.cad"
            or current_name.startswith("src.cad.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(removed_modules)
        src_module = sys.modules.get("src")
        if src_module is not None:
            if "src.doc_gen" in sys.modules:
                setattr(src_module, "doc_gen", sys.modules["src.doc_gen"])
            if "src.cad" in sys.modules:
                setattr(src_module, "cad", sys.modules["src.cad"])
        doc_gen_module = sys.modules.get("src.doc_gen")
        if doc_gen_module is not None and "src.doc_gen.pdf_engine" in sys.modules:
            setattr(doc_gen_module, "pdf_engine", sys.modules["src.doc_gen.pdf_engine"])
