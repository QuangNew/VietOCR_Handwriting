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
