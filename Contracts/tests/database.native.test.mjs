// Real PostgreSQL concurrency gate. Run only against an explicitly named, disposable local *_test DB.
// Never uses Supabase credentials or the production project's database.
import { before, after, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import pg from 'pg';

const address = process.env.VIETOCR_TEST_PG_URL;
let pool;
const U = '10000000-0000-4000-8000-000000000001';
const S = '20000000-0000-4000-8000-000000000001';
const CLIENT = U.replaceAll('-', '');
const HASH = 'b'.repeat(64);
const options = { skip: !address };
before(async () => {
  if (!address) return;
  const url = new URL(address);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || !url.pathname.endsWith('_test')) {
    throw new Error('Native database tests require a disposable loopback database whose name ends in _test');
  }
  pool = new pg.Pool({ connectionString: address, max: 32, statement_timeout: 15000 });
  await pool.query(`
    create role anon;create role authenticated;create role service_role;
    create schema auth;
    create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,banned_until timestamptz);
    create table auth.sessions(id uuid primary key,user_id uuid references auth.users(id),not_after timestamptz);
    create table auth.identities(user_id uuid references auth.users(id),provider text);
    create function auth.jwt() returns jsonb language sql stable as $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
    create function auth.uid() returns uuid language sql stable as $$ select (auth.jwt()->>'sub')::uuid $$;
    grant usage on schema public,auth to authenticated,anon,service_role;
  `);
  for (const file of ['202611030001_ocr_control.sql', '202611090001_policy_caps.sql', '202611090002_gateway_sessions.sql', '202611090003_v2_reservations.sql','202611090004_gateway_flow.sql']) {
    const sql = await readFile(new URL(`../../supabase/migrations/${file}`, import.meta.url), 'utf8');
    const c = await pool.connect();
    try { await c.query('begin'); await c.query(sql); await c.query('commit'); }
    catch (error) { await c.query('rollback'); throw error; }
    finally { c.release(); }
  }
  await pool.query('insert into auth.users values($1,$2,now(),null)', [U, 'race-fixture@example.invalid']);
  await pool.query('insert into auth.sessions values($1,$2,null)', [S, U]);
  await pool.query("insert into auth.identities values($1,'google')", [U]);
  await pool.query("insert into public.ocr_clients(id,name,prefix,user_id,email) values($1,'native race','ocr_',$2,'race-fixture@example.invalid')", [CLIENT, U]);
});
after(async () => { if (pool) await pool.end(); });
beforeEach(async () => {
  if (!pool) return;
  await pool.query('truncate public.ocr_v2_reservations,public.ocr_v2_intents,public.ocr_jobs,public.ocr_admissions,public.ocr_daily_usage cascade');
  await pool.query('update public.ocr_v2_ingress_capacity set pending=0');
  await pool.query('update public.ocr_clients set daily_limit=500,rate_per_minute=30,enabled=true where id=$1', [CLIENT]);
});
async function call(name, values) {
  const { rows } = await pool.query(`select public.${name}(${values.map((_, i) => `$${i + 1}`).join(',')}) as value`, values);
  return rows[0].value;
}
async function create() {
  const id = randomUUID();
  const reply = await call('ocr_v2_create_intent', [U, S, randomUUID(), id, HASH, 2048, 'image/jpeg', 'auto', 1]);
  assert.equal(reply.intent.id, id); return id;
}
const reserve = id => call('ocr_v2_reserve', [U, S, id, 'compute-1', 120]);
const commit = id => call('ocr_v2_commit', [id, 1, 'compute-1', HASH, 2048]);
async function used() {
  return (await pool.query("select coalesce((select used from public.ocr_daily_usage where client_id=$1 and day=(now() at time zone 'Asia/Ho_Chi_Minh')::date),0) as n", [CLIENT])).rows[0].n;
}
test('80 simultaneous admissions reserve at most 30 minute slots; 3x concurrent receipts charge once', options, async () => {
  const ids = await Promise.all(Array.from({ length: 80 }, create));
  const leases = await Promise.all(ids.map(reserve));
  const accepted = ids.filter((_, i) => leases[i].generation === 1);
  assert.equal(accepted.length, 30); assert.equal(leases.filter(v => v.error === 'minute_quota').length, 50);
  assert.equal(await used(), 0);
  const receipts = await Promise.all(accepted.flatMap(id => [commit(id), commit(id), commit(id)]));
  assert.equal(receipts.filter(v => v.accepted).length, 90);
  assert.equal(receipts.filter(v => v.duplicate === false).length, 30);
  assert.equal(await used(), 30);
});
test('500/day remains atomic with 64 simultaneous callers and 499 already used', options, async () => {
  await pool.query("insert into public.ocr_daily_usage values($1,(now() at time zone 'Asia/Ho_Chi_Minh')::date,499)", [CLIENT]);
  const ids = await Promise.all(Array.from({ length: 64 }, create));
  const leases = await Promise.all(ids.map(reserve));
  assert.equal(leases.filter(v => v.generation === 1).length, 1);
  const id = ids[leases.findIndex(v => v.generation === 1)];
  await Promise.all([commit(id), commit(id), commit(id)]); assert.equal(await used(), 500);
});
test('legacy uploads racing v2 leases still share the same 30/minute account budget', options, async () => {
  const ids = await Promise.all(Array.from({ length: 40 }, create));
  const actions = ids.map(id => reserve(id));
  for (let n = 0; n < 40; n++) {
    actions.push(call('ocr_backend', ['admit', { id: randomUUID(), clientId: CLIENT, idempotencyKey: randomUUID(), imageHash: HASH, layout: 'auto', imageBytes: 2048 }]));
  }
  const values = await Promise.all(actions);
  const holds = values.filter(v => v.generation === 1).length;
  const legacy = values.filter(v => v.job).length;
  assert.equal(holds + legacy, 30); assert.equal(await used(), legacy);
});
test('duplicate parallel intent creation leaves one job and one ingress capacity unit', options, async () => {
  const request = randomUUID();
  const replies = await Promise.all(Array.from({ length: 64 }, () => call('ocr_v2_create_intent', [U, S, request, randomUUID(), HASH, 2048, 'image/jpeg', 'auto', 1])));
  assert.equal(new Set(replies.map(v => v.intent.id)).size, 1);
  assert.equal((await pool.query('select pending::integer as n from public.ocr_v2_ingress_capacity')).rows[0].n, 1);
});
