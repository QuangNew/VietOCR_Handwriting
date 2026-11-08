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
