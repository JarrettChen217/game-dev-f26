"""Explicit detached projection for replay of the historical public contracts."""
from copy import deepcopy

VERSIONS = {3: 'single', 4: 'duel', 5: 'single', 6: 'duel'}


def project_public_scene(scene: dict, *, schema_version: int) -> dict:
    source = scene.get('schema_version')
    if (type(source) is not int or source not in VERSIONS
            or type(schema_version) is not int or schema_version not in VERSIONS
            or VERSIONS[source] != VERSIONS[schema_version]
            or source < schema_version):
        raise ValueError('unsupported public observation schema projection')
    projected = deepcopy(scene)
    if source != schema_version:
        del projected['self_status']['cooldown_remaining']
        for bullet in projected['bullets']:
            del bullet['remaining_lifetime']
        projected['schema_version'] = schema_version
    return projected
