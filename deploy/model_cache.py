# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface-hub>=1,<2", "tiktoken==0.13.0", "nltk==3.9.4", "truststore>=0.10,<1"]
# ///
"""Prepare a portable model cache on a connected machine, or use it in Docker."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


DEFAULT_MODELS = {
    'embedding': 'sentence-transformers/all-MiniLM-L6-v2',
    'auxiliary': 'TaylorAI/bge-micro-v2',
    'whisper': 'base',
    'encoding': 'cl100k_base',
}
EMBEDDING_CACHE = Path('cache/embedding/models')
WHISPER_CACHE = Path('cache/whisper/models')
DEFAULT_BUNDLE = Path(__file__).resolve().parent / 'offline-models'


def sha256(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def validate_bundle(bundle, expected_models=None):
    """Reject incomplete or damaged transfers before attempting model loading."""
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('version') != 1 or not manifest.get('files'):
        raise ValueError('Invalid offline model manifest; prepare the bundle again.')
    if manifest['models'] != (expected_models or DEFAULT_MODELS):
        raise ValueError('Offline models do not match the Docker build model settings.')
    for name, digest in manifest['files'].items():
        path = bundle / name
        # Hugging Face snapshots use relative symlinks into the same cache.
        if not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError(f'Cache file points outside the offline bundle: {name}')
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f'Offline cache is missing or damaged: {name}')
    for directory in (EMBEDDING_CACHE, WHISPER_CACHE, Path('cache/tiktoken'), Path('nltk_data')):
        if not any(name.startswith(f'{directory}/') for name in manifest['files']):
            raise ValueError(f'Offline cache is missing: {directory}')
    return manifest


def download_bundle(bundle, archive):
    # No PyTorch or native inference runtime is needed on the download machine.
    # Honor the machine's trusted certificates, including managed Mac keychains.
    import truststore
    truststore.inject_into_ssl()

    from huggingface_hub import snapshot_download
    import nltk
    import tiktoken

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / 'manifest.json').unlink(missing_ok=True)
    revisions = {}
    for role in ('embedding', 'auxiliary'):
        repo = DEFAULT_MODELS[role]
        print(f'Downloading {repo}...', flush=True)
        snapshot = snapshot_download(
            repo,
            cache_dir=str(bundle / EMBEDDING_CACHE),
            # Keep PyTorch weights/tokenizers; omit alternative export formats.
            ignore_patterns=['onnx/*', 'openvino/*', '*.h5', '*.ot', '*.msgpack'],
        )
        revisions[role] = Path(snapshot).name
    print('Downloading Whisper base...', flush=True)
    snapshot = snapshot_download(
        'Systran/faster-whisper-base',
        cache_dir=str(bundle / WHISPER_CACHE),
        allow_patterns=['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*'],
    )
    revisions['whisper'] = Path(snapshot).name
    print('Downloading tiktoken and NLTK data...', flush=True)
    os.environ['TIKTOKEN_CACHE_DIR'] = str(bundle / 'cache/tiktoken')
    tiktoken.get_encoding(DEFAULT_MODELS['encoding'])
    nltk.download('punkt_tab', download_dir=str(bundle / 'nltk_data'), raise_on_error=True)

    files = {}
    for path in sorted(bundle.rglob('*')):
        relative = path.relative_to(bundle)
        if path.is_file() and '.locks' not in relative.parts and path.name != '.gitkeep':
            if path.name.endswith('.incomplete'):
                raise ValueError(f'Unfinished download: {relative}')
            files[relative.as_posix()] = sha256(path)
    manifest = {'version': 1, 'models': DEFAULT_MODELS, 'revisions': revisions, 'files': files}
    (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_bundle(bundle)
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + '.tmp')
    # Preserve the relative snapshot -> blob symlinks; include both in the tar.
    with tarfile.open(temporary, 'w:gz', dereference=False) as tar:
        for name in ['manifest.json', *files]:
            tar.add(bundle / name, arcname=f'offline-models/{name}', recursive=False)
    temporary.replace(archive)
    checksum = archive.with_name(archive.name + '.sha256')
    checksum.write_text(f'{sha256(archive)}  {archive.name}\n')
    print(f'Bundle ready: {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)', flush=True)
    print(f'Checksum: {checksum}', flush=True)


def warm_cache(bundle):
    """Called inside the image after the Python dependencies are installed."""
    if os.environ.get('USE_SLIM_DOCKER') == 'true' and os.environ.get('USE_CUDA_DOCKER') != 'true':
        print('Slim build: skipping model cache.')
        return
    expected = {
        'embedding': os.environ['RAG_EMBEDDING_MODEL'],
        'auxiliary': os.environ['AUXILIARY_EMBEDDING_MODEL'],
        'whisper': os.environ['WHISPER_MODEL'],
        'encoding': os.environ['TIKTOKEN_ENCODING_NAME'],
    }
    offline = (bundle / 'manifest.json').is_file()
    if not offline and any(path.name != '.gitkeep' for path in bundle.iterdir()):
        raise ValueError('Incomplete offline bundle: manifest.json is missing. Run the download command again.')
    if offline:
        print('Validating and importing offline model cache...', flush=True)
        validate_bundle(bundle, expected)
        for source, destination in (
            (EMBEDDING_CACHE, os.environ['SENTENCE_TRANSFORMERS_HOME']),
            (WHISPER_CACHE, os.environ['WHISPER_MODEL_DIR']),
            (Path('cache/tiktoken'), os.environ['TIKTOKEN_CACHE_DIR']),
            (Path('nltk_data'), '/usr/local/share/nltk_data'),
        ):
            shutil.copytree(bundle / source, destination, symlinks=True, dirs_exist_ok=True)
        # Set these before importing the model libraries. They affect this build
        # process only, so the application's runtime configuration is unchanged.
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        # Fail locally if a library tries an unexpected download during warming.
        import socket

        def no_network(*args, **kwargs):
            raise RuntimeError('Network access is disabled while loading the offline model bundle.')

        socket.create_connection = no_network
        socket.socket.connect = no_network
        socket.socket.connect_ex = no_network
        socket.getaddrinfo = no_network

    from sentence_transformers import SentenceTransformer
    from faster_whisper import WhisperModel
    import tiktoken
    import nltk

    for model in (expected['embedding'], expected['auxiliary']):
        SentenceTransformer(
            model, device='cpu', cache_folder=os.environ['SENTENCE_TRANSFORMERS_HOME'],
            local_files_only=offline,
        )
    WhisperModel(
        expected['whisper'], device='cpu', compute_type='int8',
        download_root=os.environ['WHISPER_MODEL_DIR'], local_files_only=offline,
    )
    tiktoken.get_encoding(expected['encoding'])
    if offline:
        nltk.data.find('tokenizers/punkt_tab/english/')
    else:
        nltk.download('punkt_tab', download_dir='/usr/local/share/nltk_data', raise_on_error=True)
    print(f'Model cache ready ({"offline" if offline else "online"}).', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['download', 'check', 'warm'])
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument('--archive', type=Path, default=DEFAULT_BUNDLE.with_suffix('.tar.gz'))
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if args.command == 'download':
        download_bundle(bundle, args.archive.resolve())
    elif args.command == 'check':
        validate_bundle(bundle)
        print('Offline model bundle checksum validation passed.')
    else:
        warm_cache(bundle)


if __name__ == '__main__':
    main()
