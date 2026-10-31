"""Fixed u876 full-state continuation bindings; no alternate learning algorithm."""
import hashlib
import json
from pathlib import Path

BASE_UPDATE, BASE_STEPS, END_UPDATE = 876, 4316928, 1900
BASE_SHA = '9592d8e24e2798dc7fa36db7ee657763e2a6d598ced3b6e2f88b8d95b7e82f9e'
BASE_SOURCE = '7f9e3b806ab47a9d144de119f17d09909c393e0b'
BASE_PROTOCOL = 'e89baff13e23c00a785a013403f2e7958f665a00d0c2228856c5973b6aa6ff67'
PARENT_CONTRACT = 'a5b28a10b4f65567c272b9307a6e68a5162c2ff8a06d35f2fba8a94155f96d75'
BATCH_LIBRARY = '348975b9d8b249a370c3aee21b19747ffc9d1bc072e4d831a427b40844c0d9bf'
BATCH_MANIFEST = 'a79b3312c4e3fdfdbfa50509caa54fb6158e36c2e734a5fe1b2c43c29a698e09'
WRAPPER = 'tank_game/laika_60hz/training/source/lib.rs'
BATCH_SOURCE = 'tank_game/laika_60hz/training/source/batch.rs'


def periodic_panel(update):
    return update in (1132,1388,1644)


def panel_deadline(*, now, used_seconds, batch_deadline, panel_cap=180, total_cap=900):
    return min(now+min(panel_cap,max(0,total_cap-used_seconds)),batch_deadline-2)


def recovery_parameters(settings):
    if not settings.get('approved') or not settings.get('approval_record'):
        raise RuntimeError('specific deliberate continuation approval required')
    if (settings.get('prior_charged_seconds') != 205 or settings.get('whole_seconds_remaining') != 6088
            or settings.get('evaluation_seconds_remaining') != 720 or settings.get('started_cases_remaining') != 400
            or settings.get('skip_partial_baseline') is not True):
        raise ValueError('prior consumption must remain charged; no budget reset or baseline rerun')
    return 6088,720,400


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arguments(context, output, resume):
    from tank_game.laika_60hz.training.extension import arguments as retained_arguments
    result = retained_arguments(context, output, resume)
    result[result.index('--threads')+1] = '16'
    return result


def require_storage_approval(storage):
    if not storage.get('approved'):
        raise RuntimeError('specific storage approval required before launch')
    cap = storage.get('cap_bytes')
    if cap != 18*1024**2:
        raise RuntimeError('only the declared18MiB cap is accepted')
    if (not storage.get('approval_record') or storage.get('mac_backup_cap_bytes') != 10*1024**2
            or storage.get('combined_cap_bytes') != 50000000
            or cap+storage['mac_backup_cap_bytes'] > storage['combined_cap_bytes']):
        raise RuntimeError('approval/cap binding mismatch')
    return cap


def validate_source_bindings(old, new):
    if set(new)-set(old) != {BATCH_SOURCE} or set(old)-set(new):
        raise ValueError('unexpected native source set')
    for name, original in old.items():
        expected = ('3a0fd85bef33b43cfac8e1938fa1851c52ddd04259f09a3e7e163bf7eca9bec6'
                    if name == WRAPPER else original)
        if new[name] != expected:
            raise ValueError('native source mismatch: '+name)
    if (old[WRAPPER] != 'dded9504758470fe8a876593a4d93896fbc565b6d918cc7c7cacb0e355ddd5cf'
            or new[BATCH_SOURCE] != '1b1c731a92d5b27fe327af548efc8abb879165d803adf89c1bbf0bc80c8f23f6'):
        raise ValueError('unqualified sampler source change')


def validate_assets(old_assets, batch_assets, source_root):
    old_assets, batch_assets, source_root = map(Path, (old_assets, batch_assets, source_root))
    old = json.loads((old_assets/'manifest.json').read_text())
    new = json.loads((batch_assets/'manifest.json').read_text())
    if (digest(batch_assets/'manifest.json') != BATCH_MANIFEST
            or digest(batch_assets/new['library']) != BATCH_LIBRARY
            or digest(old_assets/old['library']) != '86cd34f971879efd4b660ed15501d60114497f371ceede533ac33ffa13870b97'):
        raise ValueError('unqualified native artifact binding')
    validate_source_bindings(old['source_sha256'], new['source_sha256'])
    if any(digest(source_root/name) != value for name,value in new['source_sha256'].items()):
        raise ValueError('actual native sources do not match qualified sampler')
    binding = {'parent_environment_contract': PARENT_CONTRACT, 'workers':16,
               'batch_library_sha256':BATCH_LIBRARY, 'batch_manifest_sha256':BATCH_MANIFEST,
               'qualification_trace_sha256':'80f0615859c178530cf932efd85292e54df0736eb260a52463f2b18c4852c804',
               'only_source_changes':[WRAPPER,BATCH_SOURCE]}
    binding['binding_sha256'] = hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
    return binding
