"""Local-first data engine foundation.

The public migration surface stays in legacy modules until cutover. New
implementation code lives here behind compatibility shims.
"""

from forven.dataeng.identity import SymbolRef, to_ccxt, to_fs, to_ref
from forven.dataeng.hub import DataHub, get_data_hub
from forven.dataeng.settings import DataEngineSettings, load_data_engine_settings
from forven.dataeng.source import SourceHealth, SourceRegistry, Stream, get_source_registry
from forven.dataeng.stream import StreamManager, get_stream_manager

__all__ = [
    "DataHub",
    "DataEngineSettings",
    "SourceHealth",
    "SourceRegistry",
    "SymbolRef",
    "Stream",
    "StreamManager",
    "get_data_hub",
    "get_source_registry",
    "get_stream_manager",
    "load_data_engine_settings",
    "to_ccxt",
    "to_fs",
    "to_ref",
]
