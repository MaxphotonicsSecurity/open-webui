"""Checks for interrupted downloads, damaged transfers, and portable HF symlinks."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('model_cache', Path(__file__).resolve().parents[1] / 'model_cache.py')
model_cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_cache)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / 'offline-models'
        self.files = {}
        for relative in (
            'cache/embedding/models/models--example/blobs/weights',
            'cache/whisper/models/model.bin',
            'cache/tiktoken/encoding',
            'nltk_data/tokenizers/punkt_tab/english/abbrev_types.txt',
        ):
            path = self.bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'example resource')
            self.files[relative] = model_cache.sha256(path)
        self.snapshot = self.bundle / 'cache/embedding/models/models--example/snapshots/revision/model.bin'
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.symlink_to('../../blobs/weights')
        self.files[self.snapshot.relative_to(self.bundle).as_posix()] = model_cache.sha256(self.snapshot)
        self.write_manifest()

    def write_manifest(self, models=None):
        (self.bundle / 'manifest.json').write_text(json.dumps({
            'version': 1, 'models': models or model_cache.DEFAULT_MODELS, 'files': self.files,
        }))

    def test_accepts_hugging_face_relative_symlinks(self):
        model_cache.validate_bundle(self.bundle)

    def test_rejects_damaged_download(self):
        self.snapshot.write_bytes(b'corrupted after transfer')
        with self.assertRaisesRegex(ValueError, 'missing or damaged'):
            model_cache.validate_bundle(self.bundle)

    def test_rejects_missing_download(self):
        self.snapshot.resolve().unlink()
        with self.assertRaisesRegex(ValueError, 'missing or damaged'):
            model_cache.validate_bundle(self.bundle)

    def test_rejects_changed_model_settings(self):
        expected = dict(model_cache.DEFAULT_MODELS, embedding='another/model')
        with self.assertRaisesRegex(ValueError, 'do not match'):
            model_cache.validate_bundle(self.bundle, expected)

    def test_rejects_incomplete_bundle(self):
        self.files = {key: value for key, value in self.files.items() if not key.startswith('cache/tiktoken/')}
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'missing: cache/tiktoken'):
            model_cache.validate_bundle(self.bundle)

    def test_rejects_external_symlink(self):
        outside = self.bundle.parent / 'outside'
        outside.write_bytes(b'example resource')
        self.snapshot.unlink()
        self.snapshot.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'outside the offline bundle'):
            model_cache.validate_bundle(self.bundle)

    def test_interrupted_download_does_not_fall_back_to_network(self):
        (self.bundle / 'manifest.json').unlink()
        from unittest.mock import patch
        settings = {
            'RAG_EMBEDDING_MODEL': model_cache.DEFAULT_MODELS['embedding'],
            'AUXILIARY_EMBEDDING_MODEL': model_cache.DEFAULT_MODELS['auxiliary'],
            'WHISPER_MODEL': 'base', 'TIKTOKEN_ENCODING_NAME': 'cl100k_base',
        }
        with patch.dict('os.environ', settings, clear=True):
            with self.assertRaisesRegex(ValueError, 'manifest.json is missing'):
                model_cache.warm_cache(self.bundle)


if __name__ == '__main__':
    unittest.main()
