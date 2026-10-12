"""Offline regression: raw V2 catalog metadata must survive automatic bases."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
import layout_refresh as layout

class CatalogIdentity(unittest.TestCase):
    def window(self):
        catalog=[dict(attachment_price_id=100+i,item_name='固定底座',category_level1='底座',
            category_level2='固定底座',width_mm=width,height_mm=200,depth_mm=600,
            data_version='v2-current',price=300) for i,width in enumerate((800,1000))]
        return SimpleNamespace(attachments=[dict(item_name='固定底座',category_level1='底座',
            category_level2='固定底座',catalog_version='v2-current'),
            dict(item_name='分段板',attachment_price_id=200,catalog_version='v2-current',
                 manual_inputs={'分段板高度':150},quantity=1)],
            ganged_cabinets=[dict(width_mm=width,height_mm=2000,depth_mm=600,base_height_mm=200)
                              for width in (800,1000)],
            _attachment_catalog_cache=catalog,selected_product_code=lambda:'JP_SINGLE')

    def test_automatic_raw_catalog_bases_keep_v2_identity_and_child_height(self):
        window=self.window()
        original=copy.deepcopy(window._attachment_catalog_cache)
        payload=layout._build_ganged_attachment_payload(window,[{'quote_id':'offline'}])
        self.assertEqual(len(payload['attachments']),3)
        bases=[row for row in window.attachments if row.get('ganged_fixed_base_match')]
        self.assertEqual([row['catalog_version'] for row in bases],['v2-current']*2)
        self.assertEqual([row['ganged_fixed_base_index'] for row in bases],[0,1])
        self.assertEqual([row['manual_inputs']['底座高度'] for row in payload['attachments'][1:]],[200]*2)
        self.assertEqual(window._attachment_catalog_cache,original)

    def test_real_legacy_catalog_rows_are_not_silently_accepted(self):
        window=self.window()
        window.attachments.append(dict(item_name='旧目录附件',attachment_price_id=99))
        with self.assertRaisesRegex(ValueError,'新旧目录数据'):
            layout._build_ganged_attachment_payload(window,[{'quote_id':'offline'}])

    def test_data_version_only_is_also_authoritative_v2_metadata(self):
        window=self.window()
        window.attachments=[dict(item_name='分段板',attachment_price_id=200,
                                data_version='v2-current',quantity=1)]
        payload=layout._build_ganged_attachment_payload(window,[{'quote_id':'offline'}])
        self.assertIsNotNone(payload)
        self.assertEqual(payload['attachments'][0]['attachment_price_id'],200)

if __name__=='__main__':unittest.main()
