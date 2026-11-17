-- VietOCR v2 additive upgrade. Run once against the existing OCR project.
-- Keeps admins, identities, history and usage; lowers account caps to 500/day,30/min.
-- Schema/permission changes are transactional. Review before running on production.
begin;
do $$begin
 if to_regclass('public.ocr_clients') is null then raise exception 'Install baseline 202611030001 first';end if;
 if to_regclass('public.ocr_v2_intents') is not null then raise exception 'V2 already installed: apply only newer migrations';end if;
end$$;
-- Forward migration: preserve identities, history and every usage counter.
-- Apply as a transaction (the Supabase migration runner does this); never edit the old migration.
alter table public.ocr_clients drop constraint ocr_clients_rate_per_minute_check;
alter table public.ocr_clients drop constraint ocr_clients_daily_limit_check;
update public.ocr_clients set daily_limit=least(daily_limit,500),rate_per_minute=least(rate_per_minute,30)
 where daily_limit>500 or rate_per_minute>30;
alter table public.ocr_clients alter column daily_limit set default 500;
alter table public.ocr_clients alter column rate_per_minute set default 30;
alter table public.ocr_clients add constraint ocr_clients_daily_limit_check check(daily_limit between 1 and 500);
alter table public.ocr_clients add constraint ocr_clients_rate_per_minute_check check(rate_per_minute between 1 and 30);
update public.ocr_settings set value=jsonb_set(jsonb_set(value,'{defaultDailyLimit}',
 to_jsonb(least(coalesce((value->>'defaultDailyLimit')::integer,500),500))),'{defaultRatePerMinute}',
 to_jsonb(least(coalesce((value->>'defaultRatePerMinute')::integer,30),30))),updated_at=clock_timestamp() where id;
-- The new API must not silently serve 500/30 claims while an old database still admits 1000/60.
create or replace function public.ocr_policy_version() returns jsonb
language sql stable security definer set search_path='' as $$
 select '{"policyVersion":2,"dailyImageCap":500,"minuteRequestCap":30}'::jsonb;
$$;
revoke all on function public.ocr_policy_version() from public,anon,authenticated;
grant execute on function public.ocr_policy_version() to service_role;
notify pgrst,'reload schema';


-- Session verification uses the *user's* bearer JWT. The Pi needs only the public publishable key.
-- This RPC is not an OCR admission/upload API and does not consume quota.
create or replace function public.ocr_v2_check_identity(p_user_id uuid,p_session_id uuid)
returns void language plpgsql security definer set search_path='' as $$
begin
 if p_user_id is null or p_session_id is null
  or not exists(select 1 from auth.sessions s where s.id=p_session_id and s.user_id=p_user_id
    and (s.not_after is null or s.not_after>clock_timestamp()))
  or not exists(select 1 from auth.users u where u.id=p_user_id and u.email_confirmed_at is not null
    and (u.banned_until is null or u.banned_until<=clock_timestamp()))
  or not exists(select 1 from auth.identities i where i.user_id=p_user_id and i.provider='google')
 then raise sqlstate 'PT403' using message='google_session_disabled'; end if;
end; $$;
revoke all on function public.ocr_v2_check_identity(uuid,uuid) from public,anon,authenticated;

create or replace function public.ocr_gateway_session(p_session_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare v_uid uuid:=auth.uid();v_client public.ocr_clients;v_email text;v_settings jsonb;
begin
 -- A linked Google identity alone is insufficient: an email/password session of that
 -- same user must not become a Google-only app session. AMR is signed by Supabase.
 if (auth.jwt()->>'session_id')::uuid is distinct from p_session_id
    or not exists(select 1 from jsonb_array_elements(case when jsonb_typeof(auth.jwt()->'amr')='array'
      then auth.jwt()->'amr' else '[]'::jsonb end) a
      where a->>'method'='oauth' and coalesce(a->>'provider',auth.jwt()->'app_metadata'->>'provider')='google')
    or exists(select 1 from jsonb_array_elements(case when jsonb_typeof(auth.jwt()->'amr')='array'
      then auth.jwt()->'amr' else '[]'::jsonb end) a where a->>'method' in ('password','otp','anonymous','sso/saml'))
 then raise sqlstate 'PT403' using message='google_session_required';end if;
 perform public.ocr_v2_check_identity(v_uid,p_session_id);
 select email into v_email from auth.users where id=v_uid;
 select value into v_settings from public.ocr_settings where id;
 -- Do not update/lock the identity row on every stream auth check.
 select * into v_client from public.ocr_clients where user_id=v_uid;
 if not found then
  insert into public.ocr_clients(id,name,prefix,user_id,email,daily_limit,rate_per_minute)
   values(replace(v_uid::text,'-',''),left(v_email,80),'ocr_'||replace(v_uid::text,'-',''),v_uid,v_email,
    least(coalesce((v_settings->>'defaultDailyLimit')::int,500),500),
    least(coalesce((v_settings->>'defaultRatePerMinute')::int,30),30))
   on conflict(user_id) do nothing;
  select * into v_client from public.ocr_clients where user_id=v_uid;
 end if;
 if not v_client.enabled then raise sqlstate 'PT403' using message='account_disabled';end if;
 return jsonb_build_object('userId',v_uid,'clientId',v_client.id,'ocrId','ocr_'||v_client.id,
  'dailyLimit',least(v_client.daily_limit,500),'ratePerMinute',least(v_client.rate_per_minute,30),
  'usedToday',coalesce((select used from public.ocr_daily_usage where client_id=v_client.id
   and day=(clock_timestamp() at time zone 'Asia/Ho_Chi_Minh')::date),0));
end; $$;
revoke all on function public.ocr_gateway_session(uuid) from public,anon;
grant execute on function public.ocr_gateway_session(uuid) to authenticated;
notify pgrst,'reload schema';


-- V2 admission is separate from the existing inference queue. No image bodies in Postgres.
-- Trusted services get procedure grants only. Do NOT grant these roles to authenticated/anon.
do $$begin
 if not exists(select 1 from pg_roles where rolname='ocr_gateway') then create role ocr_gateway nologin;end if;
 if not exists(select 1 from pg_roles where rolname='ocr_compute') then create role ocr_compute nologin;end if;
end$$;
grant usage on schema public to ocr_gateway,ocr_compute;

create table public.ocr_v2_intents (
 id uuid primary key,client_id text not null references public.ocr_clients(id),
 request_id uuid not null,session_id uuid not null,server_id text,
 image_hash text not null check(image_hash ~ '^[0-9a-f]{64}$'),image_bytes bigint not null check(image_bytes between 16 and 67108864),
 media_type text not null check(media_type in ('image/jpeg','image/png','image/webp')),
 layout text not null check(layout in ('auto','line')),image_version integer not null check(image_version>0),
 state text not null default 'awaiting_upload' check(state in ('awaiting_upload','upload_granted','uploading','queued','running','succeeded','failed','cancelled')),
 lease_generation bigint not null default 0,created_at timestamptz not null default now(),accepted_at timestamptz,
 unique(client_id,request_id)
);
create index ocr_v2_intents_pending on public.ocr_v2_intents(client_id,created_at)
 where state in ('awaiting_upload','upload_granted','uploading');
create index ocr_jobs_client_pending on public.ocr_jobs(client_id) where state in ('queued','running');

create table public.ocr_v2_reservations (
 job_id uuid primary key references public.ocr_v2_intents(id),client_id text not null references public.ocr_clients(id),
 generation bigint not null check(generation>0),state text not null check(state in ('active','committed','released')),
 reserved_day date not null,expires_at timestamptz not null,committed_at timestamptz
);
create index ocr_v2_reservations_account on public.ocr_v2_reservations(client_id,expires_at) where state='active';
-- Short counter update after per-account checks, not SELECT COUNT/SUM under the settings-row lock.
create table public.ocr_v2_ingress_capacity (id boolean primary key default true check(id),pending bigint not null check(pending>=0));
insert into public.ocr_v2_ingress_capacity values(true,0);
alter table public.ocr_v2_intents enable row level security;
alter table public.ocr_v2_reservations enable row level security;
alter table public.ocr_v2_ingress_capacity enable row level security;
revoke all on public.ocr_v2_intents,public.ocr_v2_reservations,public.ocr_v2_ingress_capacity from public,anon,authenticated,ocr_gateway,ocr_compute;

create or replace function public.ocr_v2_create_intent(
 p_user_id uuid,p_session_id uuid,p_request_id uuid,p_job_id uuid,p_hash text,p_bytes bigint,p_media text,p_layout text,p_version integer)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_client public.ocr_clients;v_job public.ocr_v2_intents;v_settings jsonb;
begin
 perform public.ocr_v2_check_identity(p_user_id,p_session_id);
 select * into v_client from public.ocr_clients where user_id=p_user_id for update;
 if not found or not v_client.enabled then return '{"error":"account_disabled","status":403}';end if;
 if p_request_id is null or p_job_id is null or p_request_id='00000000-0000-0000-0000-000000000000'::uuid
  or p_job_id='00000000-0000-0000-0000-000000000000'::uuid or p_hash is null or p_hash !~ '^[0-9a-f]{64}$'
  or p_bytes is null or p_bytes<16 or p_bytes>67108864 or p_media is null or p_media not in ('image/jpeg','image/png','image/webp')
  or p_layout is null or p_layout not in ('auto','line') or p_version is null or p_version<1
 then return '{"error":"invalid_intent","status":400}';end if;
 select * into v_job from public.ocr_v2_intents where client_id=v_client.id and request_id=p_request_id;
 if found then
  if (v_job.image_hash,v_job.image_bytes,v_job.media_type,v_job.layout,v_job.image_version)
   is distinct from (p_hash,p_bytes,p_media,p_layout,p_version)
  then return '{"error":"idempotency_conflict","status":409}';end if;
  return jsonb_build_object('intent',to_jsonb(v_job),'duplicate',true);
 end if;
 select value into v_settings from public.ocr_settings where id;
 if not coalesce((v_settings->>'acceptingRequests')::boolean,false) then return '{"error":"maintenance","status":503,"retryAfter":30}';end if;
 if p_bytes>(v_settings->>'maxUploadMiB')::bigint*1048576 then return '{"error":"image_size","status":413}';end if;
 if (select count(*) from public.ocr_v2_intents where client_id=v_client.id and state in ('awaiting_upload','upload_granted','uploading'))
   +(select count(*) from public.ocr_jobs where client_id=v_client.id and state in ('queued','running'))>=(v_settings->>'perClientPending')::int
 then return '{"error":"account_pending_limit","status":429,"retryAfter":3}';end if;
 update public.ocr_v2_ingress_capacity set pending=pending+1 where id and pending<(v_settings->>'queueCapacity')::bigint;
 if not found then return '{"error":"queue_full","status":429,"retryAfter":3}';end if;
 insert into public.ocr_v2_intents(id,client_id,request_id,session_id,image_hash,image_bytes,media_type,layout,image_version)
  values(p_job_id,v_client.id,p_request_id,p_session_id,p_hash,p_bytes,p_media,p_layout,p_version) returning * into v_job;
 return jsonb_build_object('intent',to_jsonb(v_job),'duplicate',false);
end; $$;

create or replace function public.ocr_v2_reserve(p_user_id uuid,p_session_id uuid,p_job_id uuid,p_server_id text,p_ttl_seconds integer default 60)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_client public.ocr_clients;v_job public.ocr_v2_intents;v_res public.ocr_v2_reservations;
 v_now timestamptz;v_day date;v_used integer;v_minute integer;v_reserved integer;
begin
 perform public.ocr_v2_check_identity(p_user_id,p_session_id);
 select * into v_client from public.ocr_clients where user_id=p_user_id for update;
 if not found or not v_client.enabled then return '{"error":"account_disabled","status":403}';end if;
 select * into v_job from public.ocr_v2_intents where id=p_job_id and client_id=v_client.id for update;
 if not found then return '{"error":"intent_not_found","status":404}';end if;
 v_now:=clock_timestamp();v_day:=(v_now at time zone 'Asia/Ho_Chi_Minh')::date;
 if p_server_id is null or length(p_server_id) not between 1 and 80 or p_ttl_seconds is null or p_ttl_seconds not between 15 and 120
 then return '{"error":"invalid_lease","status":400}';end if;
 select * into v_res from public.ocr_v2_reservations where job_id=p_job_id;
 if v_res.state='committed' then return jsonb_build_object('accepted',true,'generation',v_res.generation);end if;
 if v_job.state not in ('awaiting_upload','upload_granted','uploading') then return '{"error":"intent_state","status":409}';end if;
 if v_res.state='active' and v_res.expires_at>v_now then
  if v_job.server_id<>p_server_id then return '{"error":"lease_owned_by_server","status":409}';end if;
  return jsonb_build_object('generation',v_res.generation,'expiresAt',v_res.expires_at,'duplicate',true);
 end if;
 v_used:=coalesce((select used from public.ocr_daily_usage where client_id=v_client.id and day=v_day),0);
 select count(*) into v_reserved from public.ocr_v2_reservations where client_id=v_client.id and state='active' and expires_at>v_now;
 if v_used+v_reserved>=least(v_client.daily_limit,500) then return jsonb_build_object('error','daily_quota','status',429,'retryAfter',
  greatest(1,ceil(extract(epoch from (((v_day+1)::timestamp at time zone 'Asia/Ho_Chi_Minh')-v_now)))));end if;
 select count(*) into v_minute from public.ocr_admissions where client_id=v_client.id and admitted_at>v_now-interval '60 seconds';
 if v_minute+v_reserved>=least(v_client.rate_per_minute,30) then return '{"error":"minute_quota","status":429,"retryAfter":60}';end if;
 update public.ocr_v2_intents set state='upload_granted',server_id=p_server_id,session_id=p_session_id,lease_generation=lease_generation+1
  where id=p_job_id returning * into v_job;
 insert into public.ocr_v2_reservations(job_id,client_id,generation,state,reserved_day,expires_at)
  values(p_job_id,v_client.id,v_job.lease_generation,'active',v_day,v_now+make_interval(secs=>p_ttl_seconds))
  on conflict(job_id) do update set generation=excluded.generation,state='active',reserved_day=excluded.reserved_day,expires_at=excluded.expires_at,committed_at=null;
 return jsonb_build_object('generation',v_job.lease_generation,'expiresAt',v_now+make_interval(secs=>p_ttl_seconds),'duplicate',false);
end; $$;

create or replace function public.ocr_v2_commit(p_job_id uuid,p_generation bigint,p_server_id text,p_hash text,p_bytes bigint)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_client public.ocr_clients;v_job public.ocr_v2_intents;v_res public.ocr_v2_reservations;
 v_now timestamptz;v_day date;v_used integer;v_minute integer;v_other_reserved integer;
begin
 -- Always lock account -> intent -> reservation, the same order as reserve/cancel.
 select * into v_client from public.ocr_clients where id=(select client_id from public.ocr_v2_intents where id=p_job_id) for update;
 select * into v_job from public.ocr_v2_intents where id=p_job_id for update;
 if not found then return '{"error":"intent_not_found","status":404}';end if;
 select * into v_res from public.ocr_v2_reservations where job_id=p_job_id for update;
 if not found or p_generation is distinct from v_res.generation or p_server_id is distinct from v_job.server_id
 then return '{"error":"stale_lease","status":409}';end if;
 if p_hash is distinct from v_job.image_hash or p_bytes is distinct from v_job.image_bytes then return '{"error":"image_integrity","status":409}';end if;
 if v_res.state='committed' then return jsonb_build_object('accepted',true,'duplicate',true,'jobId',p_job_id);end if;
 perform public.ocr_v2_check_identity(v_client.user_id,v_job.session_id);
 if not v_client.enabled then return '{"error":"account_disabled","status":403}';end if;
 v_now:=clock_timestamp();v_day:=(v_now at time zone 'Asia/Ho_Chi_Minh')::date;
 if v_res.state<>'active' or v_res.expires_at<=v_now or v_job.state not in ('upload_granted','uploading')
 then return '{"error":"stale_lease","status":409}';end if;
 -- Recheck quota at *acceptance*, including a lease crossing midnight or an admin lowering a limit.
 v_used:=coalesce((select used from public.ocr_daily_usage where client_id=v_client.id and day=v_day),0);
 select count(*) into v_other_reserved from public.ocr_v2_reservations where client_id=v_client.id and job_id<>p_job_id and state='active' and expires_at>v_now;
 if v_used+v_other_reserved>=least(v_client.daily_limit,500) then return '{"error":"daily_quota","status":429,"retryAfter":60}';end if;
 select count(*) into v_minute from public.ocr_admissions where client_id=v_client.id and admitted_at>v_now-interval '60 seconds';
 if v_minute+v_other_reserved>=least(v_client.rate_per_minute,30) then return '{"error":"minute_quota","status":429,"retryAfter":60}';end if;
 insert into public.ocr_jobs(id,client_id,idempotency_key,image_hash,layout,state,image_bytes,created_at)
  values(p_job_id::text,v_client.id,'v2:'||v_job.request_id::text,p_hash,v_job.layout,'queued',p_bytes,v_job.created_at);
 insert into public.ocr_daily_usage values(v_client.id,v_day,1) on conflict(client_id,day) do update set used=public.ocr_daily_usage.used+1;
 insert into public.ocr_admissions(job_id,client_id,admitted_at) values(p_job_id::text,v_client.id,v_now);
 update public.ocr_v2_reservations set state='committed',committed_at=v_now where job_id=p_job_id;
 update public.ocr_v2_intents set state='queued',accepted_at=v_now where id=p_job_id;
 update public.ocr_v2_ingress_capacity set pending=pending-1 where id;
 return jsonb_build_object('accepted',true,'duplicate',false,'jobId',p_job_id);
end; $$;

create or replace function public.ocr_v2_release(p_user_id uuid,p_job_id uuid,p_generation bigint,p_cancel boolean default false)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_client public.ocr_clients;v_job public.ocr_v2_intents;v_res public.ocr_v2_reservations;
begin
 select * into v_client from public.ocr_clients where user_id=p_user_id for update;
 select * into v_job from public.ocr_v2_intents where id=p_job_id and client_id=v_client.id for update;
 if not found then return '{"error":"intent_not_found","status":404}';end if;
 select * into v_res from public.ocr_v2_reservations where job_id=p_job_id for update;
 if v_res.state='committed' or v_job.state in ('queued','running','succeeded','failed') then return '{"error":"already_accepted","status":409}';end if;
 if v_job.state='cancelled' then return '{"released":true,"duplicate":true}';end if;
 if p_generation is distinct from v_job.lease_generation then return '{"error":"stale_lease","status":409}';end if;
 update public.ocr_v2_reservations set state='released' where job_id=p_job_id;
 update public.ocr_v2_intents set state=case when p_cancel then 'cancelled' else 'awaiting_upload' end where id=p_job_id;
 if p_cancel then update public.ocr_v2_ingress_capacity set pending=pending-1 where id;end if;
 return '{"released":true}';
end; $$;

-- Transitional v1 and v2 share the same quota: v1 must account for in-flight v2 reservations.
-- Keep the existing RPC surface/admin intact; this private implementation cannot be called directly.
alter function public.ocr_backend(text,jsonb) rename to ocr_backend_v1;
revoke all on function public.ocr_backend_v1(text,jsonb) from public,anon,authenticated,service_role;
create function public.ocr_backend(action text,p jsonb default '{}') returns jsonb
language plpgsql security definer set search_path='' as $$
declare v_client public.ocr_clients;v_now timestamptz;v_day date;v_reserved integer;v_used integer;v_minute integer;
begin
 if action='admit' then
  select * into v_client from public.ocr_clients where id=p->>'clientId' for update;
  if found and v_client.enabled and not exists(select 1 from public.ocr_jobs where client_id=v_client.id and idempotency_key=p->>'idempotencyKey') then
   v_now:=clock_timestamp();v_day:=(v_now at time zone 'Asia/Ho_Chi_Minh')::date;
   select count(*) into v_reserved from public.ocr_v2_reservations where client_id=v_client.id and state='active' and expires_at>v_now;
   v_used:=coalesce((select used from public.ocr_daily_usage where client_id=v_client.id and day=v_day),0);
   if v_used+v_reserved>=least(v_client.daily_limit,500) then return '{"error":"daily_quota","status":429,"retryAfter":60}';end if;
   select count(*) into v_minute from public.ocr_admissions where client_id=v_client.id and admitted_at>v_now-interval '60 seconds';
   if v_minute+v_reserved>=least(v_client.rate_per_minute,30) then return '{"error":"minute_quota","status":429,"retryAfter":60}';end if;
  end if;
 elsif action='saveSettings' and ((p->'value'->>'defaultDailyLimit')::integer not between 1 and 500
   or (p->'value'->>'defaultRatePerMinute')::integer not between 1 and 30) then
  raise sqlstate 'PT400' using message='account_limits_exceed_policy';
 end if;
 return public.ocr_backend_v1(action,p);
end; $$;
revoke all on function public.ocr_backend(text,jsonb) from public,anon,authenticated;
grant execute on function public.ocr_backend(text,jsonb) to service_role;

revoke all on function public.ocr_v2_create_intent(uuid,uuid,uuid,uuid,text,bigint,text,text,integer),
 public.ocr_v2_reserve(uuid,uuid,uuid,text,integer),public.ocr_v2_commit(uuid,bigint,text,text,bigint),
 public.ocr_v2_release(uuid,uuid,bigint,boolean) from public,anon,authenticated;
grant execute on function public.ocr_v2_create_intent(uuid,uuid,uuid,uuid,text,bigint,text,text,integer),
 public.ocr_v2_reserve(uuid,uuid,uuid,text,integer),public.ocr_v2_release(uuid,uuid,bigint,boolean) to ocr_gateway;
grant execute on function public.ocr_v2_commit(uuid,bigint,text,text,bigint) to ocr_compute;
notify pgrst,'reload schema';

-- Compute is the DB credential boundary. Pi holds a separate machine credential,
-- never a Supabase service key or a JWT signing key. Only these fixed operations
-- can be invoked by the authenticated Pi through compute's internal API.
alter table public.ocr_clients add column if not exists v2_last_granted timestamptz;

create or replace function public.ocr_v2_gateway(action text,p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=(p->>'userId')::uuid;s uuid:=(p->>'sessionId')::uuid;
 c public.ocr_clients;j public.ocr_v2_intents;r jsonb;next_client text;
begin
 perform public.ocr_v2_check_identity(u,s);
 select * into c from public.ocr_clients where user_id=u;
 if not found or not c.enabled then return '{"error":"account_disabled","status":403}';end if;
 if action='create' then
  return public.ocr_v2_create_intent(u,s,(p->>'requestId')::uuid,(p->>'jobId')::uuid,
   p->>'sha256',(p->>'imageBytes')::bigint,p->>'mediaType',p->>'layout',(p->>'imageVersion')::int);
 elsif action='history' then
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.created_at desc) from
   (select i.* from public.ocr_v2_intents i where i.client_id=c.id order by i.created_at desc limit 100) x),'[]'::jsonb);
 end if;
 select * into j from public.ocr_v2_intents where id=(p->>'jobId')::uuid and client_id=c.id;
 if not found then return '{"error":"intent_not_found","status":404}';end if;
 if action='get' then return to_jsonb(j);
 elsif action='reserve' then
  -- Follow account -> intent -> lease ordering even for the demand heartbeat.
  perform 1 from public.ocr_clients where id=c.id for update;
  -- Active clients announce demand by polling grant. An abandoned draft cannot
  -- block everyone; round-robin considers demand from the last 15 seconds only.
  update public.ocr_v2_intents set demand_at=clock_timestamp() where id=j.id;
  if j.state='awaiting_upload' or not exists(select 1 from public.ocr_v2_reservations where job_id=j.id and state='active' and expires_at>clock_timestamp()) then
   perform pg_advisory_xact_lock(81740921);
   select a.client_id into next_client from public.ocr_v2_intents a
    join public.ocr_clients b on b.id=a.client_id
    where b.enabled and a.state in ('awaiting_upload','upload_granted','uploading')
     and a.demand_at>clock_timestamp()-interval '15 seconds'
     and not exists(select 1 from public.ocr_v2_reservations q where q.job_id=a.id and q.state='active' and q.expires_at>clock_timestamp())
    order by b.v2_last_granted asc nulls first,a.demand_at,a.created_at limit 1;
   if next_client is distinct from c.id then return '{"error":"queue_wait","status":429,"retryAfter":2}';end if;
  end if;
  r:=public.ocr_v2_reserve(u,s,j.id,p->>'serverId',120);
  if not r ? 'error' then update public.ocr_clients set v2_last_granted=clock_timestamp() where id=c.id;end if;
  return r;
 elsif action='release' then
  return public.ocr_v2_release(u,j.id,(p->>'generation')::bigint,coalesce((p->>'cancel')::boolean,false));
 else raise sqlstate 'PT400' using message='unknown_gateway_operation';end if;
end;$$;
alter table public.ocr_v2_intents add column if not exists demand_at timestamptz;

create or replace function public.ocr_v2_sync_job() returns trigger
language plpgsql security definer set search_path='' as $$begin
 update public.ocr_v2_intents set state=new.state where id::text=new.id and accepted_at is not null;
 return new;
end;$$;
create trigger ocr_v2_job_state after update of state on public.ocr_jobs
 for each row execute function public.ocr_v2_sync_job();

create or replace function public.ocr_v2_expire() returns integer
language plpgsql security definer set search_path='' as $$
declare j record;n int:=0;r jsonb;
begin
 -- Bounded maintenance, same lock ordering as reserve. Accepted jobs never expire here.
 for j in select i.id,i.lease_generation,c.user_id from public.ocr_v2_intents i
  join public.ocr_clients c on c.id=i.client_id
  where i.state in ('awaiting_upload','upload_granted','uploading') and i.created_at<clock_timestamp()-interval '24 hours'
  and not exists(select 1 from public.ocr_v2_reservations q where q.job_id=i.id and q.state='active' and q.expires_at>clock_timestamp())
  order by i.created_at limit 50
 loop
  r:=public.ocr_v2_release(j.user_id,j.id,j.lease_generation,true);
  if r->>'released'='true' then n:=n+1;end if;
 end loop;
 return n;
end;$$;

revoke all on function public.ocr_v2_gateway(text,jsonb),public.ocr_v2_expire(),public.ocr_v2_sync_job()
 from public,anon,authenticated;
grant execute on function public.ocr_v2_gateway(text,jsonb),public.ocr_v2_expire(),
 public.ocr_v2_commit(uuid,bigint,text,text,bigint) to service_role;
notify pgrst,'reload schema';

commit;
