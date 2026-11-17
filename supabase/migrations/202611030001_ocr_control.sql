-- Primary database for VietOCR. No images, passwords or bearer tokens in audit records.
create table if not exists public.ocr_admins (
 id text primary key, username text unique not null, password_hash text not null,
 created_at timestamptz not null default now()
);
create table if not exists public.ocr_clients (
 id text primary key, name text not null check(length(name) between 1 and 80),
 prefix text not null, key_hash text unique, user_id uuid unique references auth.users(id) on delete restrict,
 email text, rate_per_minute integer not null default 60 check(rate_per_minute between 1 and 60),
 daily_limit integer not null default 1000 check(daily_limit between 1 and 1000),
 enabled boolean not null default true, created_at timestamptz not null default now()
);
create table if not exists public.ocr_jobs (
 id text primary key, client_id text not null references public.ocr_clients(id),
 idempotency_key text, image_hash text not null, layout text not null,
 state text not null check(state in ('queued','running','succeeded','failed','cancelled')),
 image_bytes bigint not null, created_at timestamptz not null default now(),
 started_at timestamptz, finished_at timestamptz, worker_id text, result_text text, error text,
 queue_ms double precision, inference_ms double precision, total_ms double precision,
 attempts integer not null default 0, width integer not null default 0, height integer not null default 0,
 unique(client_id,idempotency_key)
);
create index if not exists ocr_jobs_queue on public.ocr_jobs(state,created_at);
create index if not exists ocr_jobs_retention on public.ocr_jobs(finished_at);
create index if not exists ocr_jobs_client on public.ocr_jobs(client_id,created_at desc);
create table if not exists public.ocr_daily_usage (
 client_id text not null references public.ocr_clients(id), day date not null, used integer not null default 0,
 primary key(client_id,day)
);
create table if not exists public.ocr_admissions (
 job_id text primary key, client_id text not null references public.ocr_clients(id), admitted_at timestamptz not null default now()
);
create index if not exists ocr_admissions_client_time on public.ocr_admissions(client_id,admitted_at);
create table if not exists public.ocr_settings (
 id boolean primary key default true check(id), value jsonb not null, updated_at timestamptz not null default now()
);
insert into public.ocr_settings(id,value) values(true,'{
 "acceptingRequests":true,"dispatchPaused":false,"queueCapacity":1000,"perClientPending":100,
 "jobTimeoutSeconds":120,"retentionHours":24,"reserveRamMiB":1024,"reserveVramMiB":1024,
 "workerBudgetMiB":300,"initialWorkers":1,"maxUploadMiB":16,"maxPixels":16000000,
 "spoolMiB":1024,"defaultDailyLimit":1000,"defaultRatePerMinute":60
}') on conflict do nothing;
create table if not exists public.ocr_lease (
 id boolean primary key default true check(id), owner text not null, expires_at timestamptz not null
);
create table if not exists public.ocr_audit (
 id bigint generated always as identity primary key, actor text not null, action text not null,
 target text, details jsonb not null default '{}', created_at timestamptz not null default now()
);
create index if not exists ocr_audit_time on public.ocr_audit(created_at desc);

alter table public.ocr_admins enable row level security;
alter table public.ocr_clients enable row level security;
alter table public.ocr_jobs enable row level security;
alter table public.ocr_daily_usage enable row level security;
alter table public.ocr_admissions enable row level security;
alter table public.ocr_settings enable row level security;
alter table public.ocr_lease enable row level security;
alter table public.ocr_audit enable row level security;
-- Apps may read their own history/usage, never edit jobs, credentials, limits or roles.
revoke all on public.ocr_admins,public.ocr_clients,public.ocr_jobs,public.ocr_daily_usage,
 public.ocr_admissions,public.ocr_settings,public.ocr_lease,public.ocr_audit from anon,authenticated;
grant select on public.ocr_jobs,public.ocr_daily_usage to authenticated;
create policy "own OCR results" on public.ocr_jobs for select to authenticated
 using (client_id in (select id from public.ocr_clients where user_id=(select auth.uid())));
-- Column grants keep hashes inaccessible even to the account that owns the record.
grant select(id,name,prefix,user_id,email,rate_per_minute,daily_limit,enabled,created_at) on public.ocr_clients to authenticated;
create policy "own OCR identity" on public.ocr_clients for select to authenticated using(user_id=(select auth.uid()));
create policy "own OCR usage" on public.ocr_daily_usage for select to authenticated
 using(client_id in (select id from public.ocr_clients where user_id=(select auth.uid())));

create or replace function public.ocr_client_json(c public.ocr_clients) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('id',c.id,'name',c.name,'prefix',c.prefix,'userId',c.user_id,'email',c.email,
 'ocrId',case when c.user_id is not null then 'ocr_'||c.id else null end,
 'ratePerMinute',c.rate_per_minute,'dailyLimit',c.daily_limit,'enabled',c.enabled,'createdAt',c.created_at,
 'usedToday',coalesce((select used from public.ocr_daily_usage where client_id=c.id and day=(now() at time zone 'Asia/Ho_Chi_Minh')::date),0));
$$;
create or replace function public.ocr_job_json(j public.ocr_jobs, summary boolean default false) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('id',j.id,'clientId',j.client_id,'clientName',c.name,'idempotencyKey',j.idempotency_key,
 'imageHash',j.image_hash,'layout',j.layout,'state',j.state,'imageBytes',j.image_bytes,'createdAt',j.created_at,
 'startedAt',j.started_at,'finishedAt',j.finished_at,'workerId',j.worker_id,'text',case when summary then null else j.result_text end,
 'error',j.error,'queueMs',j.queue_ms,'inferenceMs',j.inference_ms,'totalMs',j.total_ms,'attempts',j.attempts,'width',j.width,'height',j.height)
 from public.ocr_clients c where c.id=j.client_id;
$$;

-- Only the private C# server may call this function. Browser/app credentials cannot execute it.
create or replace function public.ocr_backend(action text, p jsonb default '{}') returns jsonb
language plpgsql security definer set search_path='' as $$
declare c public.ocr_clients; j public.ocr_jobs; s jsonb; result jsonb; n integer; used integer;
 t timestamptz:=clock_timestamp(); d date:=(clock_timestamp() at time zone 'Asia/Ho_Chi_Minh')::date;
begin
 if action='ping' then
  update public.ocr_lease set expires_at=t+interval '45 seconds' where id and owner=p->>'owner' and expires_at>t;
  return jsonb_build_object('alive',found);
 elsif action='lease' then
  insert into public.ocr_lease values(true,p->>'owner',t+interval '45 seconds')
   on conflict(id) do update set owner=excluded.owner,expires_at=excluded.expires_at
    where public.ocr_lease.expires_at<t or public.ocr_lease.owner=excluded.owner;
  return jsonb_build_object('alive',found);
 elsif action='release' then delete from public.ocr_lease where owner=p->>'owner'; return '{}';
 elsif action='admin' then
  select jsonb_build_object('id',id,'username',username,'passwordHash',password_hash) into result
   from public.ocr_admins where username=p->>'username'; return result;
 elsif action='createAdmin' then
  insert into public.ocr_admins(id,username,password_hash) values(p->>'id',p->>'username',p->>'hash'); return '{}';
 elsif action='password' then
  update public.ocr_admins set password_hash=p->>'hash' where id=p->>'id'; return '{}';
 elsif action='clients' then
  select coalesce(jsonb_agg(public.ocr_client_json(x) order by x.created_at desc),'[]') into result from public.ocr_clients x;
  return result;
 elsif action='authenticate' then
  select * into c from public.ocr_clients where key_hash=p->>'hash' and enabled and user_id is null;
  return case when c.id is null then null else public.ocr_client_json(c) end;
 elsif action='googleUser' then
  s:=(select value from public.ocr_settings where id);
  insert into public.ocr_clients(id,name,prefix,user_id,email,rate_per_minute,daily_limit)
   values(replace(p->>'userId','-',''),left(p->>'email',80),'ocr_'||replace(p->>'userId','-',''),
    (p->>'userId')::uuid,p->>'email',(s->>'defaultRatePerMinute')::int,(s->>'defaultDailyLimit')::int)
   on conflict(user_id) do update set email=excluded.email returning * into c;
  return public.ocr_client_json(c);
 elsif action='createClient' then
  insert into public.ocr_clients(id,name,prefix,key_hash,rate_per_minute,daily_limit)
   values(p->>'id',p->>'name',p->>'prefix',p->>'hash',(p->>'ratePerMinute')::int,(p->>'dailyLimit')::int) returning * into c;
  result:=public.ocr_client_json(c);
 elsif action='updateClient' then
  update public.ocr_clients set name=p->>'name',enabled=(p->>'enabled')::boolean,
   rate_per_minute=(p->>'ratePerMinute')::int,daily_limit=(p->>'dailyLimit')::int where id=p->>'id' returning * into c;
  if c.id is null then raise exception 'Client not found'; end if;
  result:=public.ocr_client_json(c);
 elsif action='rotateClient' then
  update public.ocr_clients set key_hash=p->>'hash',prefix=p->>'prefix' where id=p->>'id' and user_id is null returning * into c;
  if c.id is null then raise exception 'Only service keys can be rotated'; end if;
  result:=public.ocr_client_json(c);
 elsif action='revoke' then update public.ocr_clients set enabled=false where id=p->>'id'; result:='{}';
 elsif action='settings' then return (select value from public.ocr_settings where id);
 elsif action='saveSettings' then
  update public.ocr_settings set value=p->'value',updated_at=t where id; result:=p->'value';
 elsif action='audit' then
  return (select coalesce(jsonb_agg(x order by x.id desc),'[]') from (select * from public.ocr_audit order by id desc limit 200)x);
 elsif action='recordAudit' then result:='{}';
 elsif action='find' then
  select * into j from public.ocr_jobs where
   case when p->>'idem' is not null then client_id=p->>'client' and idempotency_key=p->>'idem'
   else id=p->>'id' and (p->>'client' is null or client_id=p->>'client') end;
  return case when j.id is null then null else public.ocr_job_json(j) end;
 elsif action='jobs' then
  return (select coalesce(jsonb_agg(public.ocr_job_json(x,true) order by x.created_at desc),'[]') from
   (select * from public.ocr_jobs where (not coalesce((p->>'pending')::bool,false) or state in ('queued','running'))
    and (p->>'client' is null or client_id=p->>'client') order by created_at desc limit (p->>'limit')::int)x);
 elsif action='admit' then
  -- Serialise both quota checks and insertion. Idempotent retries do not spend another credit.
  select * into c from public.ocr_clients where id=p->>'clientId' for update;
  if not found or not c.enabled then return '{"error":"account_disabled","status":403}'; end if;
  select * into j from public.ocr_jobs where client_id=c.id and idempotency_key=p->>'idempotencyKey';
  if found then
   if j.image_hash<>p->>'imageHash' or j.layout<>p->>'layout' then return '{"error":"idempotency_conflict","status":409}'; end if;
   return jsonb_build_object('job',public.ocr_job_json(j),'duplicate',true);
  end if;
  -- Lock global settings until admission commits: queue/spool caps hold across coordinators.
  select value into s from public.ocr_settings where id for update;
  if not (s->>'acceptingRequests')::bool then return '{"error":"maintenance","status":503,"retryAfter":30}'; end if;
  used:=coalesce((select u.used from public.ocr_daily_usage u where client_id=c.id and day=d),0);
  if used>=c.daily_limit then return jsonb_build_object('error','daily_quota','status',429,'retryAfter',
   greatest(1,ceil(extract(epoch from (((d+1)::timestamp at time zone 'Asia/Ho_Chi_Minh')-t))))); end if;
  select count(*) into n from public.ocr_admissions where client_id=c.id and admitted_at>t-interval '60 seconds';
  if n>=c.rate_per_minute then return jsonb_build_object('error','minute_quota','status',429,'retryAfter',
   greatest(1,ceil(extract(epoch from ((select min(admitted_at) from public.ocr_admissions where client_id=c.id and admitted_at>t-interval '60 seconds')+interval '60 seconds'-t))))); end if;
  if (select count(*) from public.ocr_jobs where state in ('queued','running'))>=(s->>'queueCapacity')::int
   or (select count(*) from public.ocr_jobs where client_id=c.id and state in ('queued','running'))>=(s->>'perClientPending')::int
   or coalesce((select sum(image_bytes) from public.ocr_jobs where state in ('queued','running')),0)+(p->>'imageBytes')::bigint>(s->>'spoolMiB')::bigint*1048576
  then return '{"error":"queue_full","status":429,"retryAfter":3}'; end if;
  insert into public.ocr_jobs(id,client_id,idempotency_key,image_hash,layout,state,image_bytes,created_at)
   values(p->>'id',c.id,p->>'idempotencyKey',p->>'imageHash',p->>'layout','queued',(p->>'imageBytes')::bigint,t) returning * into j;
  insert into public.ocr_daily_usage values(c.id,d,1) on conflict(client_id,day) do update set used=public.ocr_daily_usage.used+1;
  insert into public.ocr_admissions(job_id,client_id,admitted_at) values(j.id,c.id,t);
  return jsonb_build_object('job',public.ocr_job_json(j),'duplicate',false);
 elsif action='usage' then
  select * into c from public.ocr_clients where id=p->>'id';
  return public.ocr_client_json(c)||jsonb_build_object('timezone','Asia/Ho_Chi_Minh','resetsAt',((d+1)::timestamp at time zone 'Asia/Ho_Chi_Minh'),
   'usedLastMinute',(select count(*) from public.ocr_admissions where client_id=c.id and admitted_at>t-interval '60 seconds'));
 elsif action='start' then
  update public.ocr_jobs set state='running',worker_id=p->>'worker',started_at=t,
   queue_ms=extract(epoch from(t-created_at))*1000,attempts=attempts+1 where id=p->>'id' and state='queued' returning * into j;
  return case when j.id is null then null else public.ocr_job_json(j) end;
 elsif action='finish' then
  update public.ocr_jobs set state=p->>'state',result_text=p->>'text',error=p->>'error',finished_at=t,
   inference_ms=(p->>'elapsed')::double precision,total_ms=extract(epoch from(t-created_at))*1000,
   width=(p->>'width')::int,height=(p->>'height')::int where id=p->>'id' and state in ('queued','running'); return '{}';
 elsif action='requeue' then update public.ocr_jobs set state='queued',started_at=null,worker_id=null where id=p->>'id' and state='running'; return '{}';
 elsif action='cleanup' then
  delete from public.ocr_jobs where finished_at<t-make_interval(hours=>(p->>'hours')::int) and state in ('succeeded','failed','cancelled');
  delete from public.ocr_admissions where admitted_at<t-interval '2 minutes';
  delete from public.ocr_daily_usage where day<d-35;
  delete from public.ocr_audit where created_at<t-interval '90 days'; return '{}';
 elsif action='window' then
  return (select coalesce(jsonb_agg(public.ocr_job_json(x,true)),'[]') from
   (select * from public.ocr_jobs where finished_at>=(p->>'since')::timestamptz order by finished_at desc limit 20000)x);
 elsif action='totals' then
  select jsonb_build_object('completed',count(*) filter(where state='succeeded'),'failed',count(*) filter(where state='failed'),
   'cancelled',count(*) filter(where state='cancelled'),'matched',count(*),'perMinute',count(*) filter(where state='succeeded' and finished_at>=t-interval '1 minute'),
   'inferenceMs',avg(inference_ms) filter(where state='succeeded'),'queueMs',avg(queue_ms) filter(where state='succeeded'))
   into result from public.ocr_jobs where finished_at>=(p->>'since')::timestamptz; return result;
 else raise exception 'Unknown OCR action';
 end if;
 insert into public.ocr_audit(actor,action,target,details) values(coalesce(p->>'actor','system'),action,p->>'id',
  case when action='saveSettings' then p->'value' else jsonb_build_object('name',p->>'name','enabled',p->'enabled','dailyLimit',p->'dailyLimit','ratePerMinute',p->'ratePerMinute') end);
 return result;
end; $$;
revoke all on function public.ocr_backend(text,jsonb) from public,anon,authenticated;
grant execute on function public.ocr_backend(text,jsonb) to service_role;
revoke all on function public.ocr_client_json(public.ocr_clients),public.ocr_job_json(public.ocr_jobs,boolean) from public,anon,authenticated;
notify pgrst,'reload schema';
