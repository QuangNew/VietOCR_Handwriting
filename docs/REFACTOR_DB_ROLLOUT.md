# V2 database rollout / recovery

This checkpoint provides migration source and isolated test results. It has **not** applied these migrations to the linked Supabase production project.

## Forward rollout

1. Back up the schema/data according to the project's Supabase backup policy. Record current identities, per-account lower limits, daily used totals and coordinator owner; do not export tokens/user photos to a public report.
2. Run the contract suites on an isolated database. The `refactor` CI uses PostgreSQL 17 with 32 connections for parallel quota/idempotency tests; WASM tests alone are not the concurrency gate.
3. Apply migrations in order, each as a transaction: `202611090001_policy_caps.sql`, `002_gateway_sessions.sql`, `003_v2_reservations.sql`. Do not edit/replay the original migration against an existing project or reset the database.
4. Confirm identities/history/used counts are preserved and lower limits remain lower. Existing used >500 stays >500 until the next Vietnam day; no usage reset to make tests pass.
5. New C# builds require `ocr_policy_version()` to report policy 2 / 500 / 30 before coordinator readiness. This avoids advertising the new limits while an old database still admits 1000/60. The existing running binary is not redeployed by adding migration files.
6. Verify Google OAuth AMR, session revocation/ban and account ownership with a real test login. A Google identity linked to an email/password session does not qualify as a Google-only app login.
7. Provision least-privilege gateway/compute database connections for the OCR phase. `ocr_gateway`/`ocr_compute` are NOLOGIN privilege roles, not passwords or client tokens. Only gateway procedures may create/reserve/release; only compute may commit. Do not grant these roles to `anon`/`authenticated` or place a service-role credential on Pi/in clients.
8. Keep v2 OCR ingress disabled until C# durable upload/receipts and Rust scheduling/relay are wired. The foundation gateway returns `ocrAvailable:false`. Then cut over clients and retire the direct v1 client creation endpoint as planned.

Legacy v1 and v2 admissions share `ocr_daily_usage`/`ocr_admissions`; the transitional RPC wrapper also counts active v2 reservations. Do not restore a legacy function while those reservations are live.

## Roll back v2 ingress without erasing data

Stop new v2 admission at the gateway and compute ingress; finish/explicitly release every in-flight upload. Allow already accepted inference jobs to finish and keep their consumed credits/results. Confirm no active upload lease remains and no service is still executing a reservation/commit call. This is an operator maintenance sequence, not an automatic fallback that bypasses Pi.

For a staging recovery of migration 003, after those conditions hold:

```sql
begin;
do $$begin
 if exists(select 1 from public.ocr_v2_reservations where state='active' and expires_at>clock_timestamp()) then
  raise exception 'Drain/release active v2 leases before rollback';
 end if;
end$$;
revoke execute on function public.ocr_v2_create_intent(uuid,uuid,uuid,uuid,text,bigint,text,text,integer),
 public.ocr_v2_reserve(uuid,uuid,uuid,text,integer),public.ocr_v2_release(uuid,uuid,bigint,boolean) from ocr_gateway;
revoke execute on function public.ocr_v2_commit(uuid,bigint,text,text,bigint) from ocr_compute;
drop function public.ocr_backend(text,jsonb);
alter function public.ocr_backend_v1(text,jsonb) rename to ocr_backend;
grant execute on function public.ocr_backend(text,jsonb) to service_role;
commit;
```

Keep v2 tables for receipt reconciliation and audit. Keep migrations 001/002 and the 500/30 constraints: rolling back a transport does not authorize raising quota or deleting usage. Do not run `DROP ... CASCADE` or remove accepted jobs/images to undo the refactor. Restore protocol/service version alignment before reopening admission; record the action in the admin audit/runbook.

Before a later full production cutover, rehearse this sequence with interrupted uploads, stale receipts and accepted running jobs in staging. No rollback of hardware/Internet/1,000-client behavior has been claimed by the database unit tests.
