import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('shared client configuration contains only a project URL and publishable key', async()=>{
  const config=JSON.parse(await readFile(new URL('../../Mobile/assets/config/supabase.json',import.meta.url),'utf8'));
  assert.deepEqual(Object.keys(config).sort(),['publishableKey','url']);
  const url=new URL(config.url);
  assert.equal(url.protocol,'https:');assert.ok(url.hostname.endsWith('.supabase.co'));
  assert.equal(url.pathname,'/');assert.equal(url.username+url.password+url.search+url.hash,'');
  assert.match(config.publishableKey,/^sb_publishable_[a-zA-Z0-9_-]+$/);
});
