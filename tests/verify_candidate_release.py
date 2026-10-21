"""Unpublished candidates are tested without changing the active LAN feed."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop_client'), str(ROOT / 'tests')]
from update_test_support import LocalSource
from verify_first_install_bundle import verify_candidate_feed
from client_update_core import UpdateError
import tempfile


class CandidateReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='quote-candidate-test-')
        self.addCleanup(self.temp.cleanup)
        self.source = LocalSource(Path(self.temp.name))
        self.addCleanup(self.source.close)
        self.manifest = self.source.web / 'manifest.json'

    def test_signed_candidate_uses_local_transport_and_keeps_inputs(self):
        before = self.manifest.read_bytes()
        config = dict(self.source.config)
        result = verify_candidate_feed(self.manifest, config, '2026.10.20.05')
        self.assertTrue(result['candidate_manifest_checked'])
        self.assertTrue(result['candidate_feed_local_simulation'])
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertEqual(config, self.source.config)

    def test_wrong_candidate_version_is_not_accepted(self):
        with self.assertRaises(AssertionError):
            verify_candidate_feed(self.manifest, self.source.config, '2026.10.21.01')

    def test_modified_signature_is_not_accepted(self):
        self.manifest.write_text(self.manifest.read_text(encoding='utf-8').replace('signature', 'invalid_signature'), encoding='utf-8')
        with self.assertRaises(UpdateError):
            verify_candidate_feed(self.manifest, self.source.config, '2026.10.20.05')

    def test_modified_package_is_not_accepted(self):
        package = self.source.web / 'AIQuoteDualSystem-2026.10.20.05.zip'
        package.write_bytes(package.read_bytes() + b'tampered')
        with self.assertRaises(AssertionError):
            verify_candidate_feed(self.manifest, self.source.config, '2026.10.20.05')


if __name__ == '__main__':
    unittest.main(verbosity=2)
