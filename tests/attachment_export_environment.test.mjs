import test from 'node:test';
import assert from 'node:assert/strict';
import {attachmentEnvironmentChange} from '../api/attachment_service.mjs';

const saved={product_code:'JS',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
  coating_type:'橘纹',quote_date:'2026-09-20',cabinet_body_thickness_mm:1.5,waste_factor:1.2,model_code:'旧规格文本'};

test('export ignores model display text but rejects attachment cost environment changes',()=>{
  assert.equal(attachmentEnvironmentChange({...saved,model_code:'800/600/1800'},saved),null);
  assert.equal(attachmentEnvironmentChange({...saved,width_mm:801},saved),'width_mm');
  assert.equal(attachmentEnvironmentChange({...saved,waste_factor:1.3},saved),'waste_factor');
});
