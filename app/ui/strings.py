"""UI terminology with an optional Defect-flavoured 'egg mode'."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.settings import settings

_PLAIN = {
    "add_files": "添加文件", "add_folder": "添加文件夹", "paste": "粘贴", "clear": "清空",
    "queue_title": "合并队列", "options_title": "目录与页面", "output_title": "输出",
    "export": "导出 PDF", "export_skip": "跳过出错条目并导出",
    "status_ready": "就绪", "status_working": "处理中", "status_converting": "转换中",
    "start_node": "目录页", "start_node_off": "开始", "end_node": "导出",
    "convert_run": "开始转换", "compress_run": "开始压缩", "tasks": "任务",
    "empty_merge": "把文件拖到这里，或点击「添加文件」\n支持 PDF · Word · PPT · Excel · 图片 · 文本",
    "slots_hint": "卡片顺序 = 目录顺序 · 拖动卡片调整 · 右键连线可插入",
}
_EGG = {
    "add_files": "充能", "add_folder": "批量充能", "paste": "粘贴充能", "clear": "清空球槽",
    "queue_title": "充能球槽", "options_title": "聚焦", "output_title": "激发",
    "export": "激发 · 导出 PDF", "export_skip": "跳过故障球并激发",
    "status_ready": "待命", "status_working": "充能中", "status_converting": "充能中",
    "start_node": "目录球", "start_node_off": "起点", "end_node": "激发",
    "convert_run": "开始充能", "compress_run": "开始瘦身", "tasks": "任务",
    "empty_merge": "把文件拖进球槽，或点击「充能」\n支持 PDF · Word · PPT · Excel · 图片 · 文本",
    "slots_hint": "球槽顺序 = 目录顺序 · 拖动充能球调整 · 右键连线可插入",
}


class Strings(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.egg = bool(settings().get("egg_mode", False))

    def t(self, key: str) -> str:
        table = _EGG if self.egg else _PLAIN
        return table.get(key, _PLAIN.get(key, key))

    def set_egg(self, on: bool) -> None:
        if on != self.egg:
            self.egg = on
            settings().set("egg_mode", on)
            self.changed.emit()


_strings: Strings | None = None


def strings() -> Strings:
    global _strings
    if _strings is None:
        _strings = Strings()
    return _strings


def t(key: str) -> str:
    return strings().t(key)
