"""Exact external-build compatibility matrix for optional adapters."""

from __future__ import annotations

from media_bridge_adapters.contracts import AdapterManifest, CompatibilityResult

_MANIFESTS = (
    AdapterManifest(
        adapter_id="opencodex",
        adapter_version="0.1.0",
        product_contract="media-bridge-pre-upstream/v1",
        supported_external_versions=("2.28.0",),
        external_base_commit="5840591322117f3ee9568b35b135a6d4339f7711",
        extension_commit="fbd539bc1a68a4a9ce85823096daa537a67ec742",
        required_gateway_scopes=("responses:prepare",),
    ),
    AdapterManifest(
        adapter_id="omniroute",
        adapter_version="0.1.0",
        product_contract="media-bridge-pre-upstream/v1",
        supported_external_versions=("3.8.50",),
        external_base_commit="f95b03d70929a6a850d4b986a7bbad6740dd02e0",
        extension_commit="eaa5ba08579f93db2d3e5b0046792ce8f70fb208",
        required_gateway_scopes=("responses:prepare",),
    ),
)


def manifests() -> tuple[AdapterManifest, ...]:
    return tuple(manifest.model_copy(deep=True) for manifest in _MANIFESTS)


def inspect_compatibility(
    *,
    adapter_id: str,
    external_version: str,
    external_base_commit: str,
    extension_commit: str,
) -> CompatibilityResult:
    manifest = next((item for item in _MANIFESTS if item.adapter_id == adapter_id), None)
    if manifest is None:
        return CompatibilityResult(
            adapter_id=adapter_id,
            external_version=external_version,
            compatible=False,
            reason="unknown_adapter",
            manifest=None,
        )
    compatible = (
        external_version in manifest.supported_external_versions
        and external_base_commit == manifest.external_base_commit
        and extension_commit == manifest.extension_commit
    )
    return CompatibilityResult(
        adapter_id=adapter_id,
        external_version=external_version,
        compatible=compatible,
        reason=None if compatible else "unsupported_external_build",
        manifest=manifest.model_copy(deep=True),
    )
