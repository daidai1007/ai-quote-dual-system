"""Test trusted pins and absence of developer data in the legacy launcher."""
from pathlib import Path
import hashlib,json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop_client'),str(ROOT/'packaging'),str(ROOT/'tests')]
from update_test_support import LocalSource
from client_update_core import atomic_json,digest
from prepare_legacy_upgrade import prepare

class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='legacy-tool-prep-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=LocalSource(self.root);self.addCleanup(self.source.close)
        self.origin='http://192.168.35.212:8898';version=self.source.envelope['release']['version']
        self.source.resign(dict(self.source.envelope['release'],url=self.origin+'/'+version+'/AIQuoteDualSystem-'+version+'.zip'))
        self.config=dict(self.source.config,lan_http_origin=self.origin,manifest_url=self.origin+'/stable/manifest.json')
        self.config_file=self.root/'config.json';atomic_json(self.config_file,self.config)
        self.manifest=self.source.web/'manifest.json';self.output=self.root/'tool'
        self.entry=hashlib.sha256((self.source.source/'AIQuoteDualSystem_layout_v0.exe').read_bytes()).hexdigest()
    def run_prepare(self):return prepare(self.manifest,self.config_file,self.output,self.entry)
    def test_signed_program_is_reused_without_business_configuration(self):
        old=digest(self.manifest);result=self.run_prepare()
        self.assertEqual(digest(self.manifest),old);self.assertFalse(result['client_rebuilt'])
        self.assertEqual(set(p.name for p in self.output.iterdir()),{'manifest.json','python-casefold.json','LegacyClientUpgrade.cs','AIQuoteDualSystem_CompatUpgrade.exe','AIQuoteDualSystem_CompatUpgrade.exe.config','使用说明.txt','SHA256SUMS.txt'})
        for path in self.output.iterdir():
            self.assertNotIn(b'keep-this',path.read_bytes());self.assertNotIn(b'BEGIN PRIVATE KEY',path.read_bytes())
        mapping=json.loads((self.output/'python-casefold.json').read_text(encoding='utf-8'))
        for name in ('C:\\旧客户端\\Straße','G:\\客户 İΣς𐐀'):
            self.assertEqual(''.join(mapping.get(str(ord(c)),c) for c in name),name.casefold())
        script=(self.output/'LegacyClientUpgrade.cs').read_text(encoding='utf-8-sig')
        self.assertNotIn('__PACKAGE_SHA256__',script)
        self.assertNotIn('ExecutionPolicy Bypass',script)
        self.assertNotIn('powershell.exe',script.lower())
        self.assertTrue(result['launcher_compiled']);self.assertFalse(result['powershell_invoked'])
    def test_wrong_entry_hash_rejected(self):
        self.entry='0'*64
        with self.assertRaises(AssertionError):self.run_prepare()
    def test_changed_package_rejected(self):
        package=self.source.web/Path(self.source.envelope['release']['url']).name
        package.write_bytes(package.read_bytes()+b'changed')
        with self.assertRaises(AssertionError):self.run_prepare()
    def test_replaced_verification_key_rejected(self):
        self.config['public_key']='A'*44;atomic_json(self.config_file,self.config)
        with self.assertRaises(Exception):self.run_prepare()
    def test_other_origin_not_allowed(self):
        self.config.update(lan_http_origin='http://192.168.35.213:8898',manifest_url='http://192.168.35.213:8898/stable/manifest.json')
        atomic_json(self.config_file,self.config)
        with self.assertRaises(Exception):self.run_prepare()
    def test_existing_tool_is_not_replaced(self):
        self.output.mkdir();(self.output/'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):self.run_prepare()
        self.assertEqual((self.output/'keep.txt').read_text(),'keep')

if __name__=='__main__':unittest.main(verbosity=2)
