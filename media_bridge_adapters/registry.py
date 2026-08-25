"""In-memory adapter discovery isolated from Core, Control Plane, and Gateway internals."""

from __future__ import annotations

from media_bridge_adapters.compatibility import manifests
from media_bridge_adapters.contracts import AdapterManifest


class AdapterRegistry:
    def __init__(self, entries: tuple[AdapterManifest, ...] = ()) -> None:
        self._entries: dict[str, AdapterManifest] = {}
        for entry in entries:
            self.register(entry)

    def register(self, manifest: AdapterManifest) -> None:
        if manifest.adapter_id in self._entries:
            raise ValueError(f"Adapter '{manifest.adapter_id}' is already registered")
        self._entries[manifest.adapter_id] = manifest.model_copy(deep=True)

    def unregister(self, adapter_id: str) -> AdapterManifest:
        try:
            return self._entries.pop(adapter_id)
        except KeyError:
            raise KeyError(f"Adapter '{adapter_id}' is missing") from None

    def get(self, adapter_id: str) -> AdapterManifest:
        try:
            return self._entries[adapter_id].model_copy(deep=True)
        except KeyError:
            raise KeyError(f"Adapter '{adapter_id}' is missing") from None

    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))


def default_registry() -> AdapterRegistry:
    return AdapterRegistry(manifests())
