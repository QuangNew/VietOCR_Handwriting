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

