// Isolated PostgreSQL/WASM: no credentials, network, production data or test images.
// PGlite serialises its connection; these tests do NOT claim multi-connection race/load validation.
import { before, after, beforeEach, afterEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { PGlite } from '@electric-sql/pglite';

const db = new PGlite();
const U1 = '10000000-0000-4000-8000-000000000001';
const U2 = '10000000-0000-4000-8000-000000000002';
const S1 = '20000000-0000-4000-8000-000000000001';
const S2 = '20000000-0000-4000-8000-000000000002';
const HASH = 'a'.repeat(64);
const schema = new URL('../../../supabase/migrations/', import.meta.url);
async function scalar(sql, params = []) { return (await db.query(sql, params)).rows[0]?.v; }
async function rpc(sql, params = []) { return scalar(`select ${sql} as v`, params); }
async function claims(user = U1, session = S1, provider = 'google') {
  await db.query("select set_config('request.jwt.claims',$1,true)", [JSON.stringify({ sub: user, session_id: session,
    app_metadata: { provider }, amr: [{method:'oauth',provider,timestamp:Math.floor(Date.now()/1000)}] })]);
}
async function login(user = U1, session = S1) { await claims(user, session); return rpc('public.ocr_gateway_session($1)', [session]); }
async function intent(user = U1, session = S1, requestId = randomUUID(), jobId = randomUUID(), hash = HASH, bytes = 1000) {
  return rpc('public.ocr_v2_create_intent($1,$2,$3,$4,$5,$6,$7,$8,$9)', [user, session, requestId, jobId, hash, bytes, 'image/jpeg', 'auto', 1]);
}
async function reserve(id, user = U1, session = S1, server = 'compute-1') {
  return rpc('public.ocr_v2_reserve($1,$2,$3,$4,60)', [user, session, id, server]);
}
async function commit(id, generation = 1, server = 'compute-1', hash = HASH, bytes = 1000) {
  return rpc('public.ocr_v2_commit($1,$2,$3,$4,$5)', [id, generation, server, hash, bytes]);
}
async function release(id, generation = 1, cancel = true, user = U1) {
  return rpc('public.ocr_v2_release($1,$2,$3,$4)', [user, id, generation, cancel]);
}
async function usage(user = U1) { return scalar("select coalesce((select used from public.ocr_daily_usage where client_id=replace($1,'-','') and day=(clock_timestamp() at time zone 'Asia/Ho_Chi_Minh')::date),0) as v", [user]); }
async function rejects(sql, params, pattern) {
  await db.exec('savepoint expected_error');
  try { await assert.rejects(db.query(sql, params), pattern); }
  finally { await db.exec('rollback to savepoint expected_error;release savepoint expected_error'); }
}

before(async () => {
  await db.exec(`
    create role anon;create role authenticated;create role service_role;
    create schema auth;
    create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,banned_until timestamptz);
    create table auth.sessions(id uuid primary key,user_id uuid references auth.users(id),not_after timestamptz);
    create table auth.identities(user_id uuid references auth.users(id),provider text);
    create function auth.jwt() returns jsonb language sql stable as $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
    create function auth.uid() returns uuid language sql stable as $$ select (auth.jwt()->>'sub')::uuid $$;
    grant usage on schema public,auth to authenticated,anon,service_role;
  `);
  await db.exec(await readFile(new URL('202611030001_ocr_control.sql', schema), 'utf8'));
  await db.exec(`
    insert into public.ocr_clients(id,name,prefix,daily_limit,rate_per_minute) values('legacy','existing identity','voc_',1000,60),('lower','lower cap','voc_',20,2);
    insert into public.ocr_daily_usage values('legacy',(now() at time zone 'Asia/Ho_Chi_Minh')::date,777);
  `);
  for (const name of ['202611090001_policy_caps.sql', '202611090002_gateway_sessions.sql', '202611090003_v2_reservations.sql','202611090004_gateway_flow.sql']) {
    await db.exec('begin');
    try { await db.exec(await readFile(new URL(name, schema), 'utf8')); await db.exec('commit'); }
    catch (e) { await db.exec('rollback'); throw e; }
  }
  for (const [user, session] of [[U1, S1], [U2, S2]]) {
    await db.query('insert into auth.users values($1,$2,now(),null)', [user, `fixture-${user}@example.invalid`]);
    await db.query('insert into auth.sessions values($1,$2,null)', [session, user]);
    await db.query("insert into auth.identities values($1,'google')", [user]);
  }
});
after(() => db.close());
beforeEach(() => db.exec('begin'));
afterEach(() => db.exec('reset role;rollback'));

test('forward caps preserve all usage/identities and retain lower admin limits', async () => {
  assert.deepEqual(await rpc('public.ocr_policy_version()'),{policyVersion:2,dailyImageCap:500,minuteRequestCap:30});
  const legacy = (await db.query("select daily_limit,rate_per_minute from public.ocr_clients where id='legacy'")).rows[0];
  assert.deepEqual(legacy, { daily_limit: 500, rate_per_minute: 30 });
  assert.equal(await scalar("select used as v from public.ocr_daily_usage where client_id='legacy'"), 777);
  assert.equal(await scalar("select daily_limit as v from public.ocr_clients where id='lower'"), 20);
  const account = await login(); assert.equal(account.dailyLimit, 500); assert.equal(account.ratePerMinute, 30);
  assert.equal(account.userId, U1);
  await rejects("update public.ocr_clients set daily_limit=501 where id='legacy'", [], /check constraint/);
});
test('provider, current session, ban and ownership are checked from trusted database state', async () => {
  await login(); await claims(U1, S1, 'email');
  await rejects('select public.ocr_gateway_session($1)', [S1], /google_session_required/);
  await claims(U1, S1);
  await db.query("select set_config('request.jwt.claims',$1,true)", [JSON.stringify({sub:U1,session_id:S1,app_metadata:{provider:'google'},amr:[{method:'password',timestamp:1}]})]);
  await rejects('select public.ocr_gateway_session($1)', [S1], /google_session_required/);
  await claims(U1,S1);
  await rejects('select public.ocr_gateway_session($1)', [S2], /google_session_required/);
  await db.query("update auth.users set banned_until=now()+interval '1 day' where id=$1", [U1]);
  await rejects('select public.ocr_gateway_session($1)', [S1], /google_session_disabled/);
});
test('ordinary Google users may verify only their session and cannot reserve or commit', async () => {
  await claims(); await db.exec('set local role authenticated');
  const session = await rpc('public.ocr_gateway_session($1)', [S1]); assert.equal(session.userId, U1);
  await rejects('select public.ocr_v2_reserve($1,$2,$3,$4,60)', [U1, S1, randomUUID(), 'compute-1'], /permission denied/);
  assert.equal(await scalar("select has_table_privilege('authenticated','public.ocr_v2_intents','INSERT') as v"), false);
  assert.equal(await scalar("select has_function_privilege('anon','public.ocr_gateway_session(uuid)','EXECUTE') as v"), false);
});

test('new gateway adapter scopes ownership, rounds active demand and syncs execution state',async()=>{
 await login(U1,S1);await login(U2,S2);
 const a=await intent(U1,S1),b=await intent(U2,S2);
 const call=(action,user,session,id)=>rpc('public.ocr_v2_gateway($1,$2)',[action,{userId:user,sessionId:session,jobId:id,serverId:'compute-1'}]);
 assert.equal((await call('get',U2,S2,a.intent.id)).error,'intent_not_found');
 assert.equal((await call('reserve',U1,S1,a.intent.id)).generation,1);
 assert.equal((await call('reserve',U2,S2,b.intent.id)).generation,1);
 await commit(a.intent.id);
 await db.query("update public.ocr_jobs set state='running' where id=$1",[a.intent.id]);
 assert.equal((await call('get',U1,S1,a.intent.id)).state,'running');
 assert.equal(await scalar("select has_function_privilege('authenticated','public.ocr_v2_gateway(text,jsonb)','EXECUTE') as v"),false);
 assert.equal((await call('history',U1,S1,a.intent.id)).length,1);
});

test('expired metadata cleanup is bounded and never erases accepted jobs or quota',async()=>{
 await login();const a=await intent(),b=await intent();await reserve(a.intent.id);await commit(a.intent.id);
 await db.exec("update public.ocr_v2_intents set created_at=now()-interval '25 hours'");
 assert.equal(await rpc('public.ocr_v2_expire()'),1);
 assert.equal(await usage(),1);assert.equal(await scalar('select state as v from public.ocr_v2_intents where id=$1',[b.intent.id]),'cancelled');
 assert.equal(await scalar('select state as v from public.ocr_v2_intents where id=$1',[a.intent.id]),'queued');
});
test('gateway and compute roles cannot call each other or the private v1 implementation', async () => {
  assert.equal(await scalar("select has_function_privilege('ocr_gateway','public.ocr_v2_commit(uuid,bigint,text,text,bigint)','EXECUTE') as v"), false);
  assert.equal(await scalar("select has_function_privilege('ocr_compute','public.ocr_v2_reserve(uuid,uuid,uuid,text,integer)','EXECUTE') as v"), false);
  assert.equal(await scalar("select has_function_privilege('service_role','public.ocr_backend_v1(text,jsonb)','EXECUTE') as v"), false);
});
test('intent and reservation do not charge; complete commit charges once and enqueues durable work', async () => {
  await login(); const created = await intent(); const id = created.intent.id;
  assert.equal(created.intent.state, 'awaiting_upload'); assert.equal(await usage(), 0);
  const lease = await reserve(id); assert.equal(lease.generation, 1); assert.equal(await usage(), 0);
  assert.equal((await reserve(id)).duplicate, true);
  const receipt = await commit(id); assert.equal(receipt.accepted, true); assert.equal(await usage(), 1);
  assert.equal((await commit(id)).duplicate, true); assert.equal(await usage(), 1);
  assert.equal((await release(id)).error, 'already_accepted');
  assert.equal(await scalar('select state as v from public.ocr_jobs where id=$1', [id]), 'queued');
  assert.equal(await scalar('select count(*)::int as v from public.ocr_admissions where job_id=$1', [id]), 1);
});
test('idempotency compares bytes/hash/media/layout/version, not only the filename', async () => {
  await login(); const request = randomUUID(); const created = await intent(U1, S1, request);
  assert.equal((await intent(U1, S1, request)).intent.id, created.intent.id);
  assert.equal((await intent(U1, S1, request, randomUUID(), 'b'.repeat(64))).error, 'idempotency_conflict');
  assert.equal((await intent(U1, S1, request, randomUUID(), HASH, 1001)).error, 'idempotency_conflict');
  assert.equal((await rpc('public.ocr_v2_create_intent($1,$2,$3,$4,$5,1000,$6,$7,2)', [U1, S1, request, randomUUID(), HASH, 'image/png', 'line'])).error, 'idempotency_conflict');
});
test('30 in-flight reservations occupy the minute cap before any image is accepted', async () => {
  await login();
  for (let n = 0; n < 30; n++) { const { intent: i } = await intent(); assert.equal((await reserve(i.id)).generation, 1); }
  const { intent: i } = await intent(); assert.equal((await reserve(i.id)).error, 'minute_quota');
  assert.equal(await usage(), 0);
});
test('500/day includes existing accepted jobs and preserves an over-limit legacy account', async () => {
  await login(); await db.query("insert into public.ocr_daily_usage values(replace($1,'-',''),(now() at time zone 'Asia/Ho_Chi_Minh')::date,499)", [U1]);
  const { intent: a } = await intent(); await reserve(a.id); await commit(a.id); assert.equal(await usage(), 500);
  const { intent: b } = await intent(); assert.equal((await reserve(b.id)).error, 'daily_quota');
  assert.equal(await scalar("select used as v from public.ocr_daily_usage where client_id='legacy'"), 777);
});
test('failed/incomplete upload releases its hold; cancelled intents release queue capacity', async () => {
  await login(); await db.query("update public.ocr_clients set rate_per_minute=1 where user_id=$1", [U1]);
  const { intent: a } = await intent(); await reserve(a.id);
  const { intent: b } = await intent(); assert.equal((await reserve(b.id)).error, 'minute_quota');
  assert.equal((await release(a.id)).released, true); assert.equal((await release(a.id)).duplicate, true);
  assert.equal((await reserve(b.id)).generation, 1); assert.equal(await usage(), 0);
});
test('expiry gives a new fencing generation and rejects old/misrouted receipts', async () => {
  await login(); const { intent: a } = await intent(); await reserve(a.id);
  assert.equal((await reserve(a.id, U1, S1, 'other-server')).error, 'lease_owned_by_server');
  await db.query("update public.ocr_v2_reservations set expires_at=now()-interval '1 second' where job_id=$1", [a.id]);
  assert.equal((await commit(a.id)).error, 'stale_lease');
  assert.equal((await reserve(a.id)).generation, 2);
  assert.equal((await commit(a.id, 1)).error, 'stale_lease');
  assert.equal((await commit(a.id, 2, 'other-server')).error, 'stale_lease');
  assert.equal((await commit(a.id, 2)).accepted, true);
});
test('midnight commit uses the actual Vietnam acceptance day, not reservation day', async () => {
  await login(); const { intent: a } = await intent(); await reserve(a.id);
  await db.query("update public.ocr_v2_reservations set reserved_day=(now() at time zone 'Asia/Ho_Chi_Minh')::date-1 where job_id=$1", [a.id]);
  await db.query("insert into public.ocr_daily_usage values(replace($1,'-',''),(now() at time zone 'Asia/Ho_Chi_Minh')::date-1,123)", [U1]);
  assert.equal((await commit(a.id)).accepted, true); assert.equal(await usage(), 1);
  assert.equal(await scalar("select used as v from public.ocr_daily_usage where client_id=replace($1,'-','') and day=(now() at time zone 'Asia/Ho_Chi_Minh')::date-1", [U1]), 123);
});
test('admin lowering a limit or banning/revoking before commit prevents acceptance', async () => {
  await login(); const { intent: a } = await intent(); await reserve(a.id);
  await db.query("update public.ocr_clients set enabled=false where user_id=$1", [U1]);
  assert.equal((await commit(a.id)).error, 'account_disabled'); assert.equal(await usage(), 0);
  await db.query("update public.ocr_clients set enabled=true,daily_limit=1 where user_id=$1", [U1]);
  await db.query("insert into public.ocr_daily_usage values(replace($1,'-',''),(now() at time zone 'Asia/Ho_Chi_Minh')::date,1)", [U1]);
  assert.equal((await commit(a.id)).error, 'daily_quota');
  await db.query('delete from auth.sessions where id=$1', [S1]);
  await rejects('select public.ocr_v2_commit($1,1,$2,$3,1000)', [a.id, 'compute-1', HASH], /google_session_disabled/);
});
test('hash mismatch and cross-account access never create jobs or consume quota', async () => {
  await login(); await login(U2, S2); const { intent: a } = await intent(); await reserve(a.id);
  assert.equal((await commit(a.id, 1, 'compute-1', 'b'.repeat(64))).error, 'image_integrity');
  assert.equal((await reserve(a.id, U2, S2)).error, 'intent_not_found');
  assert.equal((await release(a.id, 1, true, U2)).error, 'intent_not_found'); assert.equal(await usage(), 0);
});
test('v1 uploads cannot bypass active v2 quota reservations during migration', async () => {
  await login(); await db.query('update public.ocr_clients set rate_per_minute=2 where user_id=$1', [U1]);
  const { intent: a } = await intent(); await reserve(a.id);
  const legacy = { id: randomUUID(), clientId: U1.replaceAll('-', ''), idempotencyKey: randomUUID(), imageHash: HASH, layout: 'line', imageBytes: 1000 };
  assert.equal((await rpc("public.ocr_backend('admit',$1)", [legacy])).duplicate, false);
  assert.equal((await rpc("public.ocr_backend('admit',$1)", [{ ...legacy, id: randomUUID(), idempotencyKey: randomUUID() }])).error, 'minute_quota');
  assert.equal((await commit(a.id)).accepted, true);
  assert.equal((await rpc("public.ocr_backend('admit',$1)", [legacy])).duplicate, true);
  assert.equal(await usage(), 2);
});
test('global ingress cap rejects new intents and recovers when a draft intent is cancelled', async () => {
  await login(); await login(U2, S2);
  await db.exec("update public.ocr_settings set value=value||'{\"queueCapacity\":1,\"perClientPending\":1}'");
  const { intent: a } = await intent();
  assert.equal((await intent(U2, S2)).error, 'queue_full');
  assert.equal((await release(a.id, 0)).released, true);
  assert.equal((await intent(U2, S2)).duplicate, false);
  assert.equal(await scalar('select pending::int as v from public.ocr_v2_ingress_capacity'), 1);
});
