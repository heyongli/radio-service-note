"""tools/ai_ocr_eval/dml_helper.py — DirectML 钩子 (re-add)
purpose: 强制 rapidocr 走 DirectML EP
format: Python 3 + onnxruntime-directml
version: 0.2.0 (2026-09-15)
consumers: ai_refdes_ocr.py (Windows 原生)"""

"""DirectML 加速钩子 (Windows 原生 Python 使用).

rapidocr 3.9.2 的 use_dml=true 参数因内部 bug 实际无效(引擎仍建 CPU session)。
本模块 monkey-patch ProviderConfig.get_ep_list, 强制 DmlExecutionProvider 优先。

用法(Linux 端无需, Windows 端 --dml 时调用):
    from dml_helper import enable_dml
    enable_dml()
    然后按需评估引擎。
"""
import logging

log = logging.getLogger("dml")


def _force_dml():
    try:
        import rapidocr.inference_engine.onnxruntime.provider_config as pc_mod
        from rapidocr.inference_engine.onnxruntime.provider_config import ProviderConfig
    except Exception as e:  # noqa: BLE001
        log.warning("no rapidocr provider_config: %s", e)
        return False

    if getattr(ProviderConfig, "_dml_patched", False):
        return True

    _orig = ProviderConfig.get_ep_list

    def get_ep_list_dml_first(self):
        base = _orig(self)
        dml_cfg = self.dml_ep_cfg()
        out = [("DmlExecutionProvider", dml_cfg)]
        for p in base:
            name = p[0] if isinstance(p, tuple) else p
            if name != "DmlExecutionProvider":
                out.append(p)
        return out

    ProviderConfig.get_ep_list = get_ep_list_dml_first
    ProviderConfig._dml_patched = True
    log.info("DirectML forced: DmlExecutionProvider 置于 EP 首位")
    return True


def enable_dml():
    """确保之后创建的 rapidocr v5/v6 引擎走 DirectML."""
    return _force_dml()