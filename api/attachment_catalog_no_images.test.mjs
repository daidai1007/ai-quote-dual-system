import assert from 'node:assert/strict';
import test from 'node:test';
import {createAttachmentService} from './attachment_service.mjs';

test('attachment catalogue returns only prices and calculation rules', async () => {
  const statements=[];
  const responses=[
    [{data_version:'v2',status:'ACTIVE'}],
    [{attachment_price_id:1,item_name:'侧板',rules:[]}],
  ];
  const service=createAttachmentService({
    env:{},calculateBase:async()=>({}),
    runPsql:async sql=>{statements.push(sql);return JSON.stringify(responses.shift());},
  });
  const result=await service.catalog();
  assert.equal(statements.length,2);
  assert.equal(statements.some(sql=>/attachment_image|image_data|base64/i.test(sql)),false);
  assert.equal(Object.hasOwn(result,'attachment_images'),false);
  assert.equal(result.items[0].attachment_price_id,1);
});
